"""
Face animation utilities: mouth (RMS-based) timeline and random blink scheduler.

This module avoids external deps and relies on stdlib (wave, struct, random).
"""
from __future__ import annotations

import contextlib
import hashlib
import random
import wave
from pathlib import Path
from typing import Dict, List, Optional
import struct


def _wav_to_mono_samples(path: Path) -> tuple[List[float], int]:
    """Decode a PCM WAV into mono float samples and return (samples, sample_rate).

    Supports 8/16/24/32-bit PCM. For multi-channel, averages channels.
    """
    with contextlib.closing(wave.open(str(path), "rb")) as wf:
        nch = wf.getnchannels()
        sw = wf.getsampwidth()  # bytes per sample
        sr = wf.getframerate()
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)

    if nframes == 0 or sr <= 0:
        return [], sr

    # Helper to iterate per-frame samples across channels
    samples: List[float] = []
    frame_bytes = sw * nch
    # Normalization factors to keep roughly comparable amplitudes across widths
    if sw == 1:
        # unsigned 8-bit [0..255] => center 128 => [-128..127]
        def read_sample(b: bytes) -> int:
            return b[0] - 128
        max_abs = 128.0
    elif sw == 2:
        def read_sample(b: bytes) -> int:
            return struct.unpack('<h', b)[0]
        max_abs = 32768.0
    elif sw == 3:
        def read_sample(b: bytes) -> int:
            # 24-bit little-endian signed
            x = int.from_bytes(b, 'little', signed=True)
            return x
        max_abs = float(1 << 23)
    elif sw == 4:
        def read_sample(b: bytes) -> int:
            return struct.unpack('<i', b)[0]
        max_abs = float(1 << 31)
    else:
        # Fallback: treat as bytes centered
        def read_sample(b: bytes) -> int:
            return int.from_bytes(b, 'little', signed=True)
        max_abs = float(1 << (8 * sw - 1))

    for i in range(0, len(raw), frame_bytes):
        frame = raw[i:i + frame_bytes]
        if len(frame) < frame_bytes:
            break
        acc = 0.0
        # per-channel
        for ch in range(nch):
            s = read_sample(frame[ch * sw:(ch + 1) * sw])
            acc += float(s)
        mono = acc / max(1, nch)
        # scale to [-1, 1] range approximately
        samples.append(mono / max_abs)
    return samples, sr


def compute_mouth_timeline(
    audio_path: Path,
    fps: int = 15,
    thr_half_ratio: float = 0.2,
    thr_open_ratio: float = 0.5,
) -> List[Dict[str, float | str]]:
    """Compute mouth state timeline using RMS per window at given FPS.

    Returns list of segments: [{start, end, state in {"close","half","open"}}]
    """
    if not audio_path or not Path(audio_path).exists():
        return []
    if thr_open_ratio <= thr_half_ratio:
        # enforce order
        thr_open_ratio = max(thr_half_ratio + 1e-6, thr_open_ratio)

    samples, sr = _wav_to_mono_samples(Path(audio_path))
    if sr <= 0 or fps <= 0:
        return []
    if not samples:
        return [{"start": 0.0, "end": 0.0, "state": "close"}]

    # frames per window based on sample rate
    win_frames = max(1, int(sr / fps))
    nwin = max(1, (len(samples) + win_frames - 1) // win_frames)

    # First pass: collect RMS per window and find max
    rms_vals: List[float] = []
    for i in range(nwin):
        start = i * win_frames
        end = min(len(samples), (i + 1) * win_frames)
        if end <= start:
            rms_vals.append(0.0)
            continue
        seg = samples[start:end]
        # Compute RMS
        s2 = 0.0
        for v in seg:
            s2 += v * v
        rms = (s2 / (end - start)) ** 0.5
        rms_vals.append(rms)
    max_rms = max(rms_vals) if rms_vals else 0.0
    if max_rms <= 1e-9:
        # silence
        return [
            {"start": 0.0, "end": (nwin / fps), "state": "close"},
        ]

    # Second pass: threshold per window, then merge consecutive segments
    def state_for(v: float) -> str:
        r = v / max_rms
        if r >= thr_open_ratio:
            return "open"
        if r >= thr_half_ratio:
            return "half"
        return "close"

    segments: List[Dict[str, float | str]] = []
    cur_state: Optional[str] = None
    cur_start: float = 0.0
    for i, v in enumerate(rms_vals):
        s = state_for(v)
        if cur_state is None:
            cur_state = s
            cur_start = i / fps
            continue
        if s == cur_state:
            continue
        # flush
        segments.append({"start": cur_start, "end": i / fps, "state": cur_state})
        cur_state = s
        cur_start = i / fps
    # tail
    if cur_state is None:
        return []
    segments.append({"start": cur_start, "end": nwin / fps, "state": cur_state})
    return segments


def generate_blink_timeline(
    duration: float,
    fps: int = 30,
    min_interval_sec: float = 2.0,
    max_interval_sec: float = 5.0,
    close_frames: int = 2,
    seed: Optional[int] = None,
) -> List[Dict[str, float | str]]:
    """Generate random blink intervals within [0, duration]. Baseline is eyes open.

    Returns list of segments: [{start, end, state=="close"}]
    """
    if duration <= 0:
        return []
    rnd = random.Random(seed)
    t = 0.0
    segments: List[Dict[str, float | str]] = []
    close_dur = max(1, close_frames) / max(1, fps)
    while True:
        interval = rnd.uniform(min_interval_sec, max_interval_sec)
        t += interval
        if t >= duration:
            break
        start = t
        end = min(duration, start + close_dur)
        segments.append({"start": start, "end": end, "state": "close"})
    return segments


def deterministic_seed_from_text(text: str) -> int:
    """Create deterministic seed from text using MD5."""
    h = hashlib.md5(text.encode("utf-8")).hexdigest()
    # take 8 bytes
    return int(h[:8], 16)
