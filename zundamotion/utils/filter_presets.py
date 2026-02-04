"""Preset filter definitions for audio/video processing."""

from __future__ import annotations

from typing import Dict, List


VIDEO_FILTER_PRESETS: Dict[str, List[str]] = {
    "invert": ["negate"],
    "sepia": [
        "colorchannelmixer="
        "0.393:0.769:0.189:0:"
        "0.349:0.686:0.168:0:"
        "0.272:0.534:0.131",
    ],
    "grayscale": ["format=gray"],
    "high_contrast": ["eq=contrast=1.6:brightness=0.05:saturation=1.0"],
    "night": ["eq=brightness=-0.10:contrast=1.2:saturation=0.6"],
}


AUDIO_FILTER_PRESETS: Dict[str, List[str]] = {
    "phone": ["highpass=f=300", "lowpass=f=3400"],
    "echo": ["aecho=0.8:0.9:1000:0.3"],
    "radio": [
        "highpass=f=200",
        "lowpass=f=4000",
        "acompressor=threshold=0.4:ratio=3:attack=20:release=250",
    ],
    "muffled": ["lowpass=f=1200"],
}


def get_video_filter_chain(preset: str) -> List[str]:
    """Return FFmpeg filter chain for a video preset."""
    key = (preset or "").strip().lower()
    if not key:
        return []
    return VIDEO_FILTER_PRESETS.get(key, [])


def get_audio_filter_chain(preset: str) -> List[str]:
    """Return FFmpeg filter chain for an audio preset."""
    key = (preset or "").strip().lower()
    if not key:
        return []
    return AUDIO_FILTER_PRESETS.get(key, [])
