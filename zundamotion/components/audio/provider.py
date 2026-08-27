"""TTS provider contract shared by concrete speech backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class TTSProviderCapabilities:
    """Machine-readable provider features used for authoring decisions."""

    provider_id: str
    languages: tuple[str, ...]
    supports_speed: bool = True
    supports_pitch: bool = True
    supports_speaker_listing: bool = False
    supports_engine_version: bool = False
    supports_word_alignment: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "languages": list(self.languages),
            "supports_speed": self.supports_speed,
            "supports_pitch": self.supports_pitch,
            "supports_speaker_listing": self.supports_speaker_listing,
            "supports_engine_version": self.supports_engine_version,
            "supports_word_alignment": self.supports_word_alignment,
        }


class TTSProvider(Protocol):
    """Minimal asynchronous synthesis boundary.

    Audio mixing, cache policy and timeline responsibilities stay outside this
    interface.  A provider only exposes its speech backend capabilities and I/O.
    """

    provider_id: str

    @property
    def capabilities(self) -> TTSProviderCapabilities: ...

    async def list_speakers(self, **options: Any) -> Mapping[int, Mapping[str, Any]]: ...

    async def engine_version(self, **options: Any) -> str: ...

    async def synthesize(
        self,
        *,
        text: str,
        speaker: int,
        filepath: str,
        speed: float = 1.0,
        pitch: float = 0.0,
        **options: Any,
    ) -> None: ...
