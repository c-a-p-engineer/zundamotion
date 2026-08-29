from __future__ import annotations

from pathlib import Path

import pytest

from zundamotion.components.audio.chatterbox_generator import ChatterboxAudioGenerator
from zundamotion.components.audio.factory import resolve_tts_provider
from zundamotion.components.config.validate_voice import validate_voice_config
from zundamotion.exceptions import ValidationError


def _config(tmp_path: Path, **voice_overrides):
    voice = {
        "provider": "chatterbox",
        "language": "en",
        "device": "cpu",
        "model": "multilingual_v2",
        "exaggeration": 0.5,
        "cfg_weight": 0.5,
    }
    voice.update(voice_overrides)
    return {
        "voice": voice,
        "script": {
            "scenes": [
                {
                    "id": "multilingual",
                    "lines": [
                        {"text": "Hello", "language": "en"},
                        {"text": "Hola", "language": "es"},
                        {"text": "こんにちは", "language": "ja"},
                    ],
                }
            ]
        },
    }


def test_resolve_tts_provider_keeps_voicevox_default() -> None:
    assert resolve_tts_provider({"voice": {}}) == "voicevox"
    assert resolve_tts_provider({}) == "voicevox"
    assert resolve_tts_provider({"voice": {"provider": "ChatterBox"}}) == "chatterbox"


def test_chatterbox_multilingual_config_validates_without_runtime(tmp_path: Path) -> None:
    config = _config(tmp_path)
    validate_voice_config(config)


def test_chatterbox_rejects_unknown_language(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config["script"]["scenes"][0]["lines"][0]["language"] = "xx"

    with pytest.raises(ValidationError, match="language"):
        validate_voice_config(config)


def test_chatterbox_rejects_missing_reference_audio(tmp_path: Path) -> None:
    config = _config(tmp_path, reference_audio=str(tmp_path / "missing.wav"))

    with pytest.raises(ValidationError, match="reference_audio"):
        validate_voice_config(config)


def test_chatterbox_accepts_reference_audio(tmp_path: Path) -> None:
    reference = tmp_path / "speaker.wav"
    reference.write_bytes(b"reference")
    config = _config(tmp_path, reference_audio=str(reference))

    validate_voice_config(config)


def test_chatterbox_rejects_invalid_device_and_cfg_weight(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="device"):
        validate_voice_config(_config(tmp_path, device="auto"))
    with pytest.raises(ValidationError, match="cfg_weight"):
        validate_voice_config(_config(tmp_path, cfg_weight=1.5))
