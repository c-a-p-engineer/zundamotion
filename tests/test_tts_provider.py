from __future__ import annotations

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
