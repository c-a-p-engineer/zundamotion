"""Factory for provider-specific audio generators."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from ...cache import CacheManager
from ...utils.ffmpeg_params import AudioParams
from .chatterbox_generator import ChatterboxAudioGenerator
from .generator import AudioGenerator as VoicevoxAudioGenerator

SUPPORTED_TTS_PROVIDERS: tuple[str, ...] = ("voicevox", "chatterbox")
DEFAULT_TTS_PROVIDER = "voicevox"


def resolve_tts_provider(config: Dict[str, Any]) -> str:
    voice_cfg = config.get("voice", {}) if isinstance(config, dict) else {}
    provider = str(voice_cfg.get("provider", DEFAULT_TTS_PROVIDER) or DEFAULT_TTS_PROVIDER)
    provider = provider.strip().lower()
    if provider not in SUPPORTED_TTS_PROVIDERS:
        raise ValueError(
            f"Unsupported voice.provider {provider!r}. "
            f"Supported providers: {list(SUPPORTED_TTS_PROVIDERS)}"
        )
    return provider


def create_audio_generator(
    config: Dict[str, Any],
    temp_dir: Path,
    audio_params: AudioParams,
    cache_manager: CacheManager,
):
    provider = resolve_tts_provider(config)
    if provider == "chatterbox":
        return ChatterboxAudioGenerator(config, temp_dir, audio_params, cache_manager)
    return VoicevoxAudioGenerator(config, temp_dir, audio_params, cache_manager)
