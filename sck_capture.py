#!/usr/bin/env python3
"""
sck_capture.py — Capture macOS system audio using ScreenCaptureKit.

Writes raw PCM audio (float32 INTERLEAVED, 48kHz, stereo) to stdout.
No BlackHole or virtual audio device needed — captures ALL system audio directly.

NOTE: ScreenCaptureKit outputs NON-INTERLEAVED (planar) float32.
      We interleave L/R channels before writing to stdout so ffmpeg
      can decode it as standard f32le stereo.

Features:
  - Heartbeat watchdog: exits if no audio received for 10s (parent auto-restarts)
  - Clean SIGTERM handling for graceful shutdown
  - Minimal latency NSRunLoop (50ms ticks)

Requires: pyobjc-framework-ScreenCaptureKit, numpy
"""
import sys
import os
import time
import signal
import threading
import ctypes
import ctypes.util

import numpy as np
import objc
from Foundation import NSObject, NSRunLoop, NSDate, NSDefaultRunLoopMode
import ScreenCaptureKit as SCK
import CoreMedia

# ── libdispatch for GCD queue ────────────────────────────────────────────────
_libdispatch = ctypes.cdll.LoadLibrary(ctypes.util.find_library("dispatch"))
_libdispatch.dispatch_queue_create.restype = ctypes.c_void_p
_libdispatch.dispatch_queue_create.argtypes = [ctypes.c_char_p, ctypes.c_void_p]

# ── CoreMedia C functions for buffer extraction ──────────────────────────────
_cm = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreMedia.framework/CoreMedia")
_cm.CMSampleBufferGetDataBuffer.restype = ctypes.c_void_p
_cm.CMSampleBufferGetDataBuffer.argtypes = [ctypes.c_void_p]
_cm.CMBlockBufferGetDataLength.restype = ctypes.c_size_t
_cm.CMBlockBufferGetDataLength.argtypes = [ctypes.c_void_p]
_cm.CMBlockBufferCopyDataBytes.restype = ctypes.c_int32
_cm.CMBlockBufferCopyDataBytes.argtypes = [
    ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_void_p
]

_stdout_fd = sys.stdout.buffer.fileno()

# ── Watchdog: track last audio callback time ─────────────────────────────────
_last_audio_time = time.monotonic()
_last_audio_lock = threading.Lock()
_WATCHDOG_TIMEOUT = 10.0  # seconds without audio → exit (parent restarts us)
_shutdown = threading.Event()


def _update_heartbeat():
    global _last_audio_time
    with _last_audio_lock:
        _last_audio_time = time.monotonic()


def _watchdog_thread():
    """Exit if no audio callbacks received for WATCHDOG_TIMEOUT seconds."""
    while not _shutdown.is_set():
        time.sleep(2)
        with _last_audio_lock:
            elapsed = time.monotonic() - _last_audio_time
        if elapsed > _WATCHDOG_TIMEOUT:
            print(f"WATCHDOG: No audio for {elapsed:.1f}s, exiting for restart",
                  file=sys.stderr, flush=True)
            os._exit(2)  # exit code 2 = watchdog timeout


class AudioHandler(NSObject):
    """SCStreamOutput delegate — receives audio buffers and interleaves channels."""

    def stream_didOutputSampleBuffer_ofType_(self, stream, sample_buffer, output_type):
        if output_type != 1:  # SCStreamOutputTypeAudio
            return
        try:
            _update_heartbeat()

            buf_ptr = objc.pyobjc_id(sample_buffer)
            block = _cm.CMSampleBufferGetDataBuffer(buf_ptr)
            if not block:
                return
            length = _cm.CMBlockBufferGetDataLength(block)
            if length == 0:
                return

            # Read raw planar data
            raw = (ctypes.c_char * length)()
            status = _cm.CMBlockBufferCopyDataBytes(block, 0, length, raw)
            if status != 0:
                return

            raw_bytes = bytes(raw)

            # Non-interleaved (planar): first half = Left, second half = Right
            half = length // 2
            left = np.frombuffer(raw_bytes, dtype=np.float32, count=half // 4)
            right = np.frombuffer(raw_bytes, dtype=np.float32, offset=half, count=half // 4)

            # Interleave L/R → LRLRLRLR (what ffmpeg f32le expects)
            interleaved = np.empty(left.size + right.size, dtype=np.float32)
            interleaved[0::2] = left
            interleaved[1::2] = right

            os.write(_stdout_fd, interleaved.tobytes())
        except BrokenPipeError:
            # Parent process closed our stdout — exit cleanly
            os._exit(0)
        except Exception as e:
            print(f"AudioHandler error: {e}", file=sys.stderr, flush=True)

    def stream_didStopWithError_(self, stream, error):
        print(f"Stream stopped with error: {error}", file=sys.stderr, flush=True)
        os._exit(1)


def main():
    # ── Signal handlers for clean shutdown ────────────────────────────────
    def _handle_signal(signum, frame):
        _shutdown.set()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # ── Start watchdog ────────────────────────────────────────────────────
    wd = threading.Thread(target=_watchdog_thread, daemon=True)
    wd.start()

    # ── Get shareable content ─────────────────────────────────────────────
    ready = threading.Event()
    result = [None, None]

    def on_content(content, error):
        result[0] = content
        result[1] = error
        ready.set()

    SCK.SCShareableContent.getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(
        True, True, on_content
    )
    ready.wait(timeout=10)

    content, error = result
    if error or content is None:
        print(f"Failed to get shareable content: {error}", file=sys.stderr, flush=True)
        sys.exit(1)

    displays = content.displays()
    if not displays:
        print("No displays found", file=sys.stderr, flush=True)
        sys.exit(1)

    display = displays[0]
    filt = SCK.SCContentFilter.alloc().initWithDisplay_excludingWindows_(display, [])

    # ── Configure stream ──────────────────────────────────────────────────
    conf = SCK.SCStreamConfiguration.alloc().init()
    conf.setCapturesAudio_(True)
    conf.setExcludesCurrentProcessAudio_(True)
    conf.setSampleRate_(48000)
    conf.setChannelCount_(2)
    # Minimize video overhead — we only want audio
    conf.setWidth_(2)
    conf.setHeight_(2)
    conf.setMinimumFrameInterval_(CoreMedia.CMTimeMake(1, 1))  # 1 fps (minimum)
    conf.setShowsCursor_(False)

    stream = SCK.SCStream.alloc().initWithFilter_configuration_delegate_(filt, conf, None)

    handler = AudioHandler.alloc().init()
    queue_ptr = _libdispatch.dispatch_queue_create(b"sck_audio", None)
    queue_obj = objc.objc_object(c_void_p=queue_ptr)

    ok, err = stream.addStreamOutput_type_sampleHandlerQueue_error_(
        handler, 1, queue_obj, None
    )
    if not ok:
        print(f"addStreamOutput failed: {err}", file=sys.stderr, flush=True)
        sys.exit(1)

    # ── Start capture ─────────────────────────────────────────────────────
    start_done = threading.Event()
    start_err = [None]

    def on_start(e):
        start_err[0] = e
        start_done.set()

    stream.startCaptureWithCompletionHandler_(on_start)
    start_done.wait(timeout=10)

    if start_err[0]:
        print(f"Start error: {start_err[0]}", file=sys.stderr, flush=True)
        sys.exit(1)

    _update_heartbeat()  # Reset watchdog now that capture started
    print("SCK audio capture running (interleaved f32le 48kHz stereo)", file=sys.stderr, flush=True)

    # ── Run loop — pump at 50ms for low latency ──────────────────────────
    try:
        while not _shutdown.is_set():
            NSRunLoop.currentRunLoop().runMode_beforeDate_(
                NSDefaultRunLoopMode,
                NSDate.dateWithTimeIntervalSinceNow_(0.05),  # 50ms tick → low latency
            )
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        print("Stopping SCK capture...", file=sys.stderr, flush=True)
        stop_done = threading.Event()
        stream.stopCaptureWithCompletionHandler_(lambda e: stop_done.set())
        stop_done.wait(timeout=3)


if __name__ == "__main__":
    main()
