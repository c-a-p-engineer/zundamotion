"""Named output presets for common video delivery targets."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from zundamotion.exceptions import ValidationError


EXPORT_PRESETS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "youtube_1080p": {
        "video": {"width": 1920, "height": 1080, "fps": 30, "crf": 20, "cq": 20},
        "audio": {"audio_sample_rate": 48000, "audio_channels": 2, "audio_bitrate_kbps": 192},
    },
    "youtube_1440p": {
        "video": {"width": 2560, "height": 1440, "fps": 30, "crf": 20, "cq": 20},
        "audio": {"audio_sample_rate": 48000, "audio_channels": 2, "audio_bitrate_kbps": 192},
    },
    "shorts_1080x1920": {
        "video": {"width": 1080, "height": 1920, "fps": 30, "crf": 20, "cq": 20},
        "audio": {"audio_sample_rate": 48000, "audio_channels": 2, "audio_bitrate_kbps": 192},
    },
    "draft_720p": {
        "video": {"width": 1280, "height": 720, "fps": 30, "crf": 30, "cq": 30},
        "audio": {"audio_sample_rate": 48000, "audio_channels": 2, "audio_bitrate_kbps": 128},
    },
}


def apply_export_preset(config: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a named export preset into config without overriding explicit values."""

    preset_name = config.get("export_preset")
    if not preset_name:
        return config
    key = str(preset_name).strip().lower()
    preset = EXPORT_PRESETS.get(key)
    if preset is None:
        raise ValidationError(
            f"Unknown export_preset '{preset_name}'. Available: {', '.join(sorted(EXPORT_PRESETS))}."
        )

    merged = config
    video_cfg = merged.setdefault("video", {})
    for name, value in deepcopy(preset["video"]).items():
        video_cfg.setdefault(name, value)
    for name, value in deepcopy(preset["audio"]).items():
        video_cfg.setdefault(name, value)
    return merged
