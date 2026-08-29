"""Provider-aware voice configuration validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from ...exceptions import ValidationError
from ..audio.chatterbox_provider import (
    CHATTERBOX_DEFAULT_LANGUAGE,
    CHATTERBOX_LANGUAGES,
    CHATTERBOX_SUPPORTED_DEVICES,
)
from ..audio.factory import DEFAULT_TTS_PROVIDER, SUPPORTED_TTS_PROVIDERS


def validate_voice_config(config: Dict[str, Any]) -> None:
    voice_cfg = config.get("voice", {}) or {}
    if not isinstance(voice_cfg, dict):
        raise ValidationError("'voice' section must be a dictionary.")

    provider = str(
        voice_cfg.get("provider", DEFAULT_TTS_PROVIDER) or DEFAULT_TTS_PROVIDER
    ).strip().lower()
    if provider not in SUPPORTED_TTS_PROVIDERS:
        raise ValidationError(
            f"'voice.provider' must be one of {list(SUPPORTED_TTS_PROVIDERS)}, "
            f"got {provider!r}."
        )
    if provider != "chatterbox":
        return

    _validate_chatterbox_settings(voice_cfg, "voice")
    script = config.get("script", {}) or {}
    for scene_idx, scene in enumerate(script.get("scenes", []) or []):
        if not isinstance(scene, dict):
            continue
        scene_id = scene.get("id", scene_idx)
        for line_idx, line in enumerate(scene.get("lines", []) or []):
            if not isinstance(line, dict):
                continue
            label = f"scene {scene_id!r}, line {line_idx}"
            _validate_chatterbox_settings(line, label, require_language=False)
            for layer_idx, layer in enumerate(line.get("voice_layers", []) or []):
                if isinstance(layer, dict):
                    _validate_chatterbox_settings(
                        layer,
                        f"{label}, voice_layers[{layer_idx}]",
                        require_language=False,
                    )


def _validate_chatterbox_settings(
    cfg: Dict[str, Any],
    label: str,
    *,
    require_language: bool = True,
) -> None:
    language = cfg.get("language")
    if language is None and require_language:
        language = CHATTERBOX_DEFAULT_LANGUAGE
    if language is not None:
        normalized = str(language).strip().lower()
        if normalized not in CHATTERBOX_LANGUAGES:
            raise ValidationError(
                f"{label}.language must be one of {list(CHATTERBOX_LANGUAGES)}, "
                f"got {language!r}."
            )

    if "device" in cfg:
        device = str(cfg.get("device") or "").strip().lower()
        if device not in CHATTERBOX_SUPPORTED_DEVICES:
            raise ValidationError(
                f"{label}.device must be one of {list(CHATTERBOX_SUPPORTED_DEVICES)}, "
                f"got {device!r}."
            )

    model = cfg.get("model")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise ValidationError(f"{label}.model must be a non-empty string.")

    reference_audio = cfg.get("reference_audio")
    if reference_audio is not None:
        if not isinstance(reference_audio, str) or not reference_audio.strip():
            raise ValidationError(f"{label}.reference_audio must be a non-empty path.")
        path = Path(reference_audio).expanduser()
        if not path.is_file():
            raise ValidationError(
                f"{label}.reference_audio file {reference_audio!r} does not exist."
            )

    _validate_number(cfg, "exaggeration", label, minimum=0.0)
    _validate_number(cfg, "cfg_weight", label, minimum=0.0, maximum=1.0)
    _validate_neutral_unsupported_value(cfg, "speed", label, neutral=1.0)
    _validate_neutral_unsupported_value(cfg, "pitch", label, neutral=0.0)


def _validate_number(
    cfg: Dict[str, Any],
    key: str,
    label: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> None:
    if key not in cfg:
        return
    value = cfg.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValidationError(f"{label}.{key} must be a number.")
    number = float(value)
    if minimum is not None and number < minimum:
        raise ValidationError(f"{label}.{key} must be >= {minimum}.")
    if maximum is not None and number > maximum:
        raise ValidationError(f"{label}.{key} must be <= {maximum}.")


def _validate_neutral_unsupported_value(
    cfg: Dict[str, Any],
    key: str,
    label: str,
    *,
    neutral: float,
) -> None:
    if key not in cfg:
        return
    value = cfg.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValidationError(f"{label}.{key} must be a number.")
    if float(value) != neutral:
        raise ValidationError(
            f"{label}.{key}={value!r} is not supported by the Chatterbox provider; "
            f"use the neutral value {neutral}."
        )
