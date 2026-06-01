"use client";

/**
 * Global audio player store.
 *
 * Module-level state so the currently playing beat persists across
 * React component unmount/mount cycles (page navigation).
 *
 * Any page can call `globalAudio.play(beat)` and the persistent
 * player in ClientShell will show the controls.
 */

import { useEffect, useState, useCallback } from "react";

export interface GlobalBeat {
  stem: string;
  title: string;
  artist: string;
  filename: string;
}

// ── Module-level store ──────────────────────────────────────────

let _currentBeat: GlobalBeat | null = null;
let _audio: HTMLAudioElement | null = null;
let _playing = false;
let _loading = false;
let _currentTime = 0;
let _duration = 0;
let _muted = false;
let _error: string | null = null;
let _retryCount = 0;
const MAX_RETRIES = 2;
const _listeners = new Set<() => void>();

// ── Queue & Shuffle state ───────────────────────────────────────
let _queue: GlobalBeat[] = [];          // ordered list (matches beats page)
let _shuffled: GlobalBeat[] = [];        // shuffled copy when shuffle is on
let _shuffle = false;                    // shuffle toggle

function _buildShuffled(current: GlobalBeat) {
  // Fisher-Yates shuffle of the whole queue, then ensure current is first
  const copy = [..._queue];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  const idx = copy.findIndex((b) => b.stem === current.stem);
  if (idx > 0) {
    const [item] = copy.splice(idx, 1);
    copy.unshift(item);
  }
  _shuffled = copy;
}

function _activeQueue(): GlobalBeat[] {
  return _shuffle ? _shuffled : _queue;
}

function _currentIndex(): number {
  if (!_currentBeat) return -1;
  return _activeQueue().findIndex((b) => b.stem === _currentBeat!.stem);
}

function _notify() {
  _listeners.forEach((fn) => fn());
}

/**
 * Build authed URL for audio file using relative path (Next.js proxy).
 * Uses the same pattern as useApi.ts → authedUrl().
 */
function _authedAudioUrl(filename: string): string {
  const token = typeof window !== "undefined" ? localStorage.getItem("fy3-token") : null;
  const path = `/files/beats/${encodeURIComponent(filename)}`;
  return token ? `${path}?token=${token}` : path;
}

function _removeListeners(audio: HTMLAudioElement) {
  audio.onloadedmetadata = null;
  audio.ontimeupdate = null;
  audio.onended = null;
  audio.onerror = null;
  audio.oncanplay = null;
  audio.onplay = null;
  audio.onpause = null;
}

function _cleanup() {
  if (_audio) {
    try {
      _audio.pause();
      _removeListeners(_audio);
      _audio.removeAttribute("src");
      _audio.load();
    } catch {
      // ignore — element may already be dead
    }
    _audio = null;
  }
  _playing = false;
  _loading = false;
  _currentTime = 0;
  _duration = 0;
  _error = null;
  _retryCount = 0;
}

function _createAndPlay(beat: GlobalBeat) {
  _cleanup();
  _currentBeat = beat;
  _loading = true;
  _error = null;
  _notify();

  const url = _authedAudioUrl(beat.filename);
  const audio = new Audio();
  audio.preload = "auto";
  audio.crossOrigin = "anonymous";
  audio.muted = _muted;

  audio.onloadedmetadata = () => {
    _duration = audio.duration || 0;
    _notify();
  };

  audio.oncanplay = () => {
    _loading = false;
    _notify();
  };

  audio.ontimeupdate = () => {
    _currentTime = audio.currentTime;
    // throttle: only notify every ~250ms worth of change
    _notify();
  };

  audio.onplay = () => {
    _playing = true;
    _loading = false;
    _error = null;
    _notify();
  };

  audio.onpause = () => {
    _playing = false;
    _notify();
  };

  audio.onended = () => {
    _playing = false;
    _currentTime = 0;
    _notify();
    // Auto-advance to next beat
    const idx = _currentIndex();
    const q = _activeQueue();
    if (idx >= 0 && idx < q.length - 1) {
      setTimeout(() => _createAndPlay(q[idx + 1]), 300);
    }
  };

  audio.onerror = () => {
    const code = audio.error?.code;
    const msg = audio.error?.message || "Unknown error";
    console.error(`[GlobalAudio] Error loading "${beat.filename}": code=${code} ${msg}`);

    // Retry on network errors (code 2 = MEDIA_ERR_NETWORK)
    if (code === 2 && _retryCount < MAX_RETRIES) {
      _retryCount++;
      console.log(`[GlobalAudio] Retrying (${_retryCount}/${MAX_RETRIES})...`);
      _loading = true;
      _notify();
      setTimeout(() => {
        if (_currentBeat?.stem === beat.stem) {
          // Refresh token in case it expired
          const freshUrl = _authedAudioUrl(beat.filename);
          audio.src = freshUrl;
          audio.load();
          audio.play().catch(() => {});
        }
      }, 1000 * _retryCount);
      return;
    }

    _playing = false;
    _loading = false;
    _error = code === 4 ? "Format not supported" : code === 2 ? "Network error" : `Playback error (${code})`;
    _notify();
  };

  _audio = audio;

  // Set src AFTER attaching listeners
  audio.src = url;
  audio.load();

  // Play with user-interaction context
  const playPromise = audio.play();
  if (playPromise !== undefined) {
    playPromise
      .then(() => {
        _playing = true;
        _loading = false;
        _retryCount = 0;
        _notify();
      })
      .catch((err) => {
        // NotAllowedError = autoplay blocked, AbortError = play() interrupted
        console.warn(`[GlobalAudio] play() rejected: ${err.name} — ${err.message}`);
        if (err.name === "NotAllowedError") {
          // Don't mark as error — user just needs to interact
          _playing = false;
          _loading = false;
          _error = null;
        } else {
          _playing = false;
          _loading = false;
        }
        _notify();
      });
  }

  _notify();
}

export const globalAudio = {
  play(beat: GlobalBeat) {
    if (!beat?.stem || !beat?.filename) {
      console.warn("[GlobalAudio] play() called with invalid beat", beat);
      return;
    }

    // If same beat and audio element exists, just resume
    if (_currentBeat?.stem === beat.stem && _audio) {
      if (_audio.paused) {
        _audio.play()
          .then(() => { _playing = true; _error = null; _notify(); })
          .catch((err) => {
            console.warn("[GlobalAudio] resume rejected:", err.name);
            // If resume fails, recreate from scratch
            _createAndPlay(beat);
          });
      }
      return;
    }

    _createAndPlay(beat);
  },

  /** Set the full ordered queue so autoplay / next / prev work across the library. */
  setQueue(beats: GlobalBeat[], currentBeat?: GlobalBeat) {
    _queue = beats;
    if (_shuffle && currentBeat) _buildShuffled(currentBeat);
    else if (_shuffle && _currentBeat) _buildShuffled(_currentBeat);
    _notify();
  },

  playNext() {
    const idx = _currentIndex();
    const q = _activeQueue();
    if (idx < 0 || idx >= q.length - 1) return;
    _createAndPlay(q[idx + 1]);
  },

  playPrev() {
    const idx = _currentIndex();
    const q = _activeQueue();
    // If more than 3s in, restart current track; else go back one
    if (_audio && _currentTime > 3) {
      _audio.currentTime = 0;
      _currentTime = 0;
      _notify();
      return;
    }
    if (idx <= 0) return;
    _createAndPlay(q[idx - 1]);
  },

  toggleShuffle() {
    _shuffle = !_shuffle;
    if (_shuffle && _currentBeat) _buildShuffled(_currentBeat);
    _notify();
  },

  pause() {
    if (_audio && !_audio.paused) {
      _audio.pause();
      _playing = false;
      _notify();
    }
  },

  toggle() {
    if (!_audio && _currentBeat) {
      // Audio element was lost — recreate
      _createAndPlay(_currentBeat);
      return;
    }
    if (_playing) {
      globalAudio.pause();
    } else if (_audio) {
      _audio.play()
        .then(() => { _playing = true; _notify(); })
        .catch(() => {
          // Recreate on failure
          if (_currentBeat) _createAndPlay(_currentBeat);
        });
    }
  },

  seek(time: number) {
    if (_audio && isFinite(time) && _duration > 0) {
      const t = Math.max(0, Math.min(_duration, time));
      _audio.currentTime = t;
      _currentTime = t;
      _notify();
    }
  },

  seekRatio(ratio: number) {
    if (_audio && _duration > 0) {
      const t = Math.max(0, Math.min(1, ratio)) * _duration;
      _audio.currentTime = t;
      _currentTime = t;
      _notify();
    }
  },

  toggleMute() {
    _muted = !_muted;
    if (_audio) _audio.muted = _muted;
    _notify();
  },

  close() {
    _cleanup();
    _currentBeat = null;
    _notify();
  },

  /** Skip forward/backward in seconds */
  skip(seconds: number) {
    if (_audio && _duration > 0) {
      const t = Math.max(0, Math.min(_duration, _audio.currentTime + seconds));
      _audio.currentTime = t;
      _currentTime = t;
      _notify();
    }
  },

  get beat() { return _currentBeat; },
  get isPlaying() { return _playing; },
  get isLoading() { return _loading; },
  get currentTime() { return _currentTime; },
  get duration() { return _duration; },
  get isMuted() { return _muted; },
  get error() { return _error; },
  get isShuffle() { return _shuffle; },
  get hasNext() {
    const idx = _currentIndex();
    return idx >= 0 && idx < _activeQueue().length - 1;
  },
  get hasPrev() {
    return _currentIndex() > 0 || (_audio ? _currentTime > 3 : false);
  },
  get queueLength() { return _activeQueue().length; },
  get queueIndex() { return _currentIndex(); },
};

// ── Hook ────────────────────────────────────────────────────────

export function useGlobalAudio() {
  const [, setTick] = useState(0);

  useEffect(() => {
    const listener = () => setTick((t) => t + 1);
    _listeners.add(listener);
    return () => { _listeners.delete(listener); };
  }, []);

  return {
    beat: _currentBeat,
    isPlaying: _playing,
    isLoading: _loading,
    currentTime: _currentTime,
    duration: _duration,
    isMuted: _muted,
    error: _error,
    isShuffle: _shuffle,
    hasNext: globalAudio.hasNext,
    hasPrev: globalAudio.hasPrev,
    queueLength: globalAudio.queueLength,
    queueIndex: globalAudio.queueIndex,
    play: useCallback((beat: GlobalBeat) => globalAudio.play(beat), []),
    pause: useCallback(() => globalAudio.pause(), []),
    toggle: useCallback(() => globalAudio.toggle(), []),
    seek: useCallback((time: number) => globalAudio.seek(time), []),
    seekRatio: useCallback((ratio: number) => globalAudio.seekRatio(ratio), []),
    toggleMute: useCallback(() => globalAudio.toggleMute(), []),
    close: useCallback(() => globalAudio.close(), []),
    skip: useCallback((s: number) => globalAudio.skip(s), []),
    playNext: useCallback(() => globalAudio.playNext(), []),
    playPrev: useCallback(() => globalAudio.playPrev(), []),
    toggleShuffle: useCallback(() => globalAudio.toggleShuffle(), []),
    setQueue: useCallback((beats: GlobalBeat[], current?: GlobalBeat) => globalAudio.setQueue(beats, current), []),
  };
}
