#!/usr/bin/env python3
"""
audio_stream.py — Stream Mac system audio to iPhone over HTTP.

Uses macOS ScreenCaptureKit to capture system audio directly (no BlackHole needed),
pipes through ffmpeg for AAC encoding, serves via HTTP on port 8888.

Bulletproofed:
  - Process health monitoring with auto-restart
  - Watchdog detects hung pipelines
  - /health endpoint for monitoring
  - Minimal latency: small buffers, reduced backlog
  - Clean shutdown with proper process cleanup
  - Supports VST plugins via FL Studio ASIO (captures all system audio)
"""
import subprocess
import sys
import os
import signal
import threading
import time
import json
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 8888

# ── Audio capture state ──────────────────────────────────────────────────────
chunks = []
chunks_lock = threading.Lock()
MAX_CHUNKS = 600  # ~12s buffer (tighter = less latency on reconnect)

# ── Health tracking ──────────────────────────────────────────────────────────
_health = {
    "started_at": None,
    "capture_restarts": 0,
    "last_chunk_time": 0,
    "chunks_total": 0,
    "sck_pid": None,
    "ffmpeg_pid": None,
    "status": "starting",
}
_health_lock = threading.Lock()


def _update_health(**kwargs):
    with _health_lock:
        _health.update(kwargs)


def _get_health():
    with _health_lock:
        return dict(_health)


# ── Process cleanup helper ───────────────────────────────────────────────────
def _kill_proc(proc):
    """Kill a subprocess gracefully, then forcefully."""
    if proc is None:
        return
    try:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


# ── Audio capture via ScreenCaptureKit ────────────────────────────────────────
def capture_loop_sck():
    """Capture system audio via SCK helper → ffmpeg AAC → chunks.

    Auto-restarts pipeline on any failure. Watchdog detects stalls.
    Captures ALL system audio including VST plugins running in FL Studio.
    """
    helper = os.path.join(os.path.dirname(__file__), "sck_capture.py")
    python = sys.executable

    while True:
        sck_proc = None
        ffmpeg_proc = None
        try:
            _update_health(status="starting_capture")

            # sck_capture.py writes interleaved f32le PCM (48kHz stereo) to stdout
            sck_proc = subprocess.Popen(
                [python, helper],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,  # unbuffered for lowest latency
            )

            # Pipe into ffmpeg for AAC encoding
            # - Apple AudioToolbox AAC (aac_at) = highest quality, same as Apple Music
            # - 320k CBR = crystal clear, no compression artifacts
            # - Native 48kHz stereo, no resampling
            # - alimiter prevents clipping from float32 peaks > 1.0
            # - Low-latency flags: nobuffer, flush_packets, low_delay
            ffmpeg_proc = subprocess.Popen(
                [
                    "ffmpeg", "-y",
                    "-fflags", "+nobuffer+flush_packets",
                    "-flags", "+low_delay",
                    "-f", "f32le",
                    "-ar", "48000",
                    "-ac", "2",
                    "-i", "pipe:0",
                    "-af", "alimiter=limit=0.95:level=false",
                    "-acodec", "aac_at",
                    "-b:a", "320k",
                    "-ar", "48000",
                    "-ac", "2",
                    "-flush_packets", "1",
                    "-f", "adts",
                    "pipe:1",
                ],
                stdin=sck_proc.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )

            _update_health(
                status="streaming",
                sck_pid=sck_proc.pid,
                ffmpeg_pid=ffmpeg_proc.pid,
            )
            print(f"Pipeline started: sck={sck_proc.pid}, ffmpeg={ffmpeg_proc.pid}", flush=True)

            # Read encoded AAC data in small chunks for minimal latency
            consecutive_empty = 0
            while True:
                data = ffmpeg_proc.stdout.read(4096)  # smaller reads = lower latency
                if not data:
                    # Check if processes died
                    if ffmpeg_proc.poll() is not None:
                        rc = ffmpeg_proc.returncode
                        print(f"ffmpeg exited with code {rc}", flush=True)
                        break
                    if sck_proc.poll() is not None:
                        rc = sck_proc.returncode
                        print(f"sck_capture exited with code {rc}", flush=True)
                        break
                    consecutive_empty += 1
                    if consecutive_empty > 100:  # ~5s of no data
                        print("Pipeline stalled (no data for 5s), restarting", flush=True)
                        break
                    time.sleep(0.05)
                    continue

                consecutive_empty = 0
                now = time.time()
                with chunks_lock:
                    chunks.append(data)
                    if len(chunks) > MAX_CHUNKS:
                        del chunks[: len(chunks) - MAX_CHUNKS]
                _update_health(last_chunk_time=now, chunks_total=_health.get("chunks_total", 0) + 1)

        except Exception as e:
            print(f"Capture error: {e}", flush=True)
        finally:
            # Clean up both processes
            _kill_proc(sck_proc)
            _kill_proc(ffmpeg_proc)
            _update_health(
                status="restarting",
                sck_pid=None,
                ffmpeg_pid=None,
                capture_restarts=_health.get("capture_restarts", 0) + 1,
            )

        print("Restarting capture pipeline in 1s...", flush=True)
        time.sleep(1)


# ── HTML page with audio player ──────────────────────────────────────────────
def get_player_html(host):
    return f"""<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FL Studio Audio</title>
<style>
body {{
    background: #1a1a2e; color: #e0e0e0; font-family: -apple-system, sans-serif;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    min-height: 100vh; margin: 0; padding: 20px; box-sizing: border-box;
}}
h1 {{ color: #ff6b35; font-size: 24px; margin-bottom: 8px; }}
p {{ color: #888; font-size: 14px; margin: 4px 0; }}
audio {{ width: 90%; max-width: 400px; margin: 20px 0; }}
.status {{ font-size: 18px; margin: 10px 0; transition: all 0.3s; }}
.dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%;
        margin-right: 8px; }}
.dot.live {{ background: #4caf50; animation: pulse 1.5s infinite; }}
.dot.connecting {{ background: #ff9800; animation: pulse 0.5s infinite; }}
.dot.error {{ background: #f44336; }}
@keyframes pulse {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:0.3; }} }}
#info {{ color: #555; font-size: 12px; margin-top: 15px; }}
</style>
</head>
<body>
<h1>🎹 FL Studio Audio</h1>
<p>Streaming from your Mac (AAC 320kbps)</p>
<audio id="player" controls autoplay>
    <source src="http://{host}:{PORT}/stream" type="audio/aac">
</audio>
<div class="status" id="statusDiv"><span class="dot live" id="dot"></span><span id="statusText">Live</span></div>
<p>If no sound: tap play, turn up volume</p>
<div id="info"></div>
<script>
(function() {{
    var a = document.getElementById('player');
    var dot = document.getElementById('dot');
    var statusText = document.getElementById('statusText');
    var info = document.getElementById('info');
    var reconnects = 0;
    var maxRetry = 1500;  // start fast, back off
    var retryMs = 1500;

    function setStatus(state, text) {{
        dot.className = 'dot ' + state;
        statusText.textContent = text;
    }}

    function reconnect() {{
        reconnects++;
        setStatus('connecting', 'Reconnecting (#' + reconnects + ')...');
        var newSrc = 'http://{host}:{PORT}/stream?t=' + Date.now();
        a.src = newSrc;
        a.load();
        a.play().catch(function() {{}});
        retryMs = Math.min(retryMs * 1.3, 8000);  // backoff up to 8s
    }}

    a.addEventListener('playing', function() {{
        setStatus('live', 'Live');
        retryMs = 1500;  // reset backoff
        info.textContent = reconnects > 0 ? 'Reconnected (' + reconnects + ' total)' : '';
    }});

    a.addEventListener('error', function() {{
        setStatus('error', 'Disconnected');
        setTimeout(reconnect, retryMs);
    }});

    a.addEventListener('stalled', function() {{
        setStatus('connecting', 'Buffering...');
        setTimeout(function() {{
            if (a.readyState < 3) reconnect();
        }}, 3000);
    }});

    a.addEventListener('waiting', function() {{
        setStatus('connecting', 'Buffering...');
    }});

    // Periodic health check — if audio stalls silently, force reconnect
    setInterval(function() {{
        if (!a.paused && a.readyState >= 2) {{
            var ct = a.currentTime;
            setTimeout(function() {{
                if (!a.paused && a.currentTime === ct && a.readyState >= 2) {{
                    reconnect();
                }}
            }}, 4000);
        }}
    }}, 10000);

    // Keep-alive: prevent iOS Safari from suspending audio
    document.addEventListener('visibilitychange', function() {{
        if (!document.hidden && a.paused) {{
            a.play().catch(function() {{}});
        }}
    }});
}})();
</script>
</body>
</html>"""


# ── HTTP Handler ─────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path.startswith("/player"):
            host = self.headers.get("Host", "").split(":")[0] or "192.168.1.158"
            html = get_player_html(host).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(html)
            return

        if self.path.startswith("/health"):
            h = _get_health()
            h["uptime_s"] = round(time.time() - h["started_at"], 1) if h["started_at"] else 0
            h["chunk_age_s"] = round(time.time() - h["last_chunk_time"], 1) if h["last_chunk_time"] else None
            h["buffer_chunks"] = len(chunks)
            body = json.dumps(h, indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path.startswith("/stream"):
            self.send_response(200)
            self.send_header("Content-Type", "audio/aac")
            self.send_header("Cache-Control", "no-cache, no-store")
            self.send_header("Connection", "close")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("icy-name", "FL Studio Audio")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()

            # Send only last ~2s of backlog (not 100 chunks) for minimal join-latency
            with chunks_lock:
                backlog = list(chunks[-25:])
                pos = len(chunks)

            for c in backlog:
                try:
                    self._send_chunk(c)
                except Exception:
                    return

            while True:
                with chunks_lock:
                    new_data = chunks[pos:]
                    pos = len(chunks)
                if new_data:
                    for c in new_data:
                        try:
                            self._send_chunk(c)
                        except Exception:
                            return
                else:
                    time.sleep(0.02)  # 20ms poll = lower latency than 50ms
            return

        self.send_error(404)

    def _send_chunk(self, data):
        self.wfile.write(f"{len(data):x}\r\n".encode())
        self.wfile.write(data)
        self.wfile.write(b"\r\n")
        self.wfile.flush()

    def log_message(self, *args):
        pass


# ── Main ─────────────────────────────────────────────────────────────────────
class ThreadedHTTPServer(HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def process_request(self, request, client_address):
        t = threading.Thread(target=self.process_request_thread, args=(request, client_address))
        t.daemon = True
        t.start()

    def process_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            pass
        try:
            self.shutdown_request(request)
        except Exception:
            pass


if __name__ == "__main__":
    _update_health(started_at=time.time())

    print("Using ScreenCaptureKit for system audio capture", flush=True)
    print("Captures ALL system audio including FL Studio + VST plugins", flush=True)
    cap = threading.Thread(target=capture_loop_sck, daemon=True)
    cap.start()
    time.sleep(1)

    try:
        lan_ip = subprocess.check_output(
            "ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1",
            shell=True, text=True
        ).strip()
    except Exception:
        lan_ip = "127.0.0.1"

    print(f"Audio stream: http://{lan_ip}:{PORT}/", flush=True)
    print(f"Health check: http://{lan_ip}:{PORT}/health", flush=True)

    def _shutdown(signum, frame):
        print("Shutting down...", flush=True)
        # Kill any child sck_capture / ffmpeg processes
        try:
            subprocess.run(["pkill", "-P", str(os.getpid())],
                           capture_output=True, timeout=3)
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    httpd = ThreadedHTTPServer(("0.0.0.0", PORT), Handler)
    httpd.serve_forever()
