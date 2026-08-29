from __future__ import annotations

from zundamotion.components.audio.chatterbox_provider import (
    CHATTERBOX_LANGUAGES,
    ChatterboxTTSProvider,
)
from zundamotion.components.audio.provider import TTSProviderCapabilities
from zundamotion.components.audio.voicevox_client import VoicevoxTTSProvider


def test_voicevox_provider_exposes_machine_readable_capabilities() -> None:
    provider = VoicevoxTTSProvider("http://voicevox:50021/")

    assert provider.provider_id == "voicevox"
    assert provider.base_url == "http://voicevox:50021"
    assert provider.capabilities == TTSProviderCapabilities(
        provider_id="voicevox",
        languages=("ja",),
        supports_speed=True,
        supports_pitch=True,
        supports_speaker_listing=True,
        supports_engine_version=True,
        supports_word_alignment=False,
    )
    assert provider.capabilities.as_dict()["languages"] == ["ja"]


def test_chatterbox_provider_exposes_23_languages_without_loading_runtime() -> None:
    provider = ChatterboxTTSProvider(device="cpu")
    capabilities = provider.capabilities

    assert provider.provider_id == "chatterbox"
    assert len(CHATTERBOX_LANGUAGES) == 23
    assert {"en", "ja", "es", "fr", "de", "ar", "hi", "sw", "zh"}.issubset(
        CHATTERBOX_LANGUAGES
    )
    assert capabilities.supports_voice_cloning is True
    assert capabilities.supports_exaggeration is True
    assert capabilities.supports_cfg_weight is True
    assert capabilities.output_watermarked is True
    assert capabilities.optional_runtime is True
    assert capabilities.supports_speed is False
    assert capabilities.supports_pitch is False
    assert provider._model is None
