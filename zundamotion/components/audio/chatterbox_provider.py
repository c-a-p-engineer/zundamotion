"""Optional Chatterbox Multilingual TTS provider.

The heavy Chatterbox/Torch runtime is imported only when synthesis starts so
VOICEVOX-only installs, authoring commands and normal CI remain lightweight.
"""

from __future__ import annotations

import asyncio
from importlib import metadata
from pathlib import Path
from typing import Any, Mapping

from .provider import TTSProviderCapabilities

CHATTERBOX_LANGUAGES: tuple[str, ...] = (
    "ar",
    "da",
    "de",
    "el",
    "en",
    "es",
    "fi",
    "fr",
    "he",
    "hi",
    "it",
    "ja",
    "ko",
    "ms",
    "nl",
    "no",
    "pl",
    "pt",
    "ru",
    "sv",
    "sw",
    "tr",
    "zh",
)
CHATTERBOX_DEFAULT_MODEL = "v3"
CHATTERBOX_DEFAULT_LANGUAGE = "en"
CHATTERBOX_SUPPORTED_DEVICES = ("cpu", "cuda", "mps")


class ChatterboxTTSProvider:
    """Lazy in-process adapter for Chatterbox Multilingual V3."""

    provider_id = "chatterbox"

    def __init__(
        self,
        *,
        model: str = CHATTERBOX_DEFAULT_MODEL,
        device: str = "cpu",
    ) -> None:
        self.model_name = str(model or CHATTERBOX_DEFAULT_MODEL).strip()
        self.device = str(device or "cpu").strip().lower()
        if self.device not in CHATTERBOX_SUPPORTED_DEVICES:
            raise ValueError(
                "Chatterbox device must be one of "
                f"{list(CHATTERBOX_SUPPORTED_DEVICES)}, got {self.device!r}."
            )
        self._model: Any | None = None
        self._synthesis_lock: asyncio.Lock | None = None

    @property
    def capabilities(self) -> TTSProviderCapabilities:
        return TTSProviderCapabilities(
            provider_id=self.provider_id,
            languages=CHATTERBOX_LANGUAGES,
            supports_speed=False,
            supports_pitch=False,
            supports_speaker_listing=False,
            supports_engine_version=True,
            supports_word_alignment=False,
            supports_voice_cloning=True,
            supports_exaggeration=True,
            supports_cfg_weight=True,
            output_watermarked=True,
            optional_runtime=True,
        )

    async def list_speakers(self, **options: Any) -> Mapping[int, Mapping[str, Any]]:
        """Chatterbox has no numeric speaker catalog compatible with VOICEVOX."""

        return {}

    async def engine_version(self, **options: Any) -> str:
        try:
            return metadata.version("chatterbox-tts")
        except metadata.PackageNotFoundError:
            return "unavailable"

    async def synthesize(
        self,
        *,
        text: str,
        speaker: int | None,
        filepath: str,
        speed: float = 1.0,
        pitch: float = 0.0,
        language: str | None = None,
        reference_audio: str | None = None,
        provider_options: Mapping[str, Any] | None = None,
        **options: Any,
    ) -> None:
        del speaker, speed, pitch, options
        language_id = str(language or CHATTERBOX_DEFAULT_LANGUAGE).strip().lower()
        if language_id not in CHATTERBOX_LANGUAGES:
            raise ValueError(
                f"Unsupported Chatterbox language {language_id!r}. "
                f"Supported languages: {list(CHATTERBOX_LANGUAGES)}"
            )

        prompt_path: str | None = None
        if reference_audio:
            prompt = Path(reference_audio).expanduser().resolve()
            if not prompt.is_file():
                raise ValueError(
                    f"Chatterbox reference_audio does not exist or is not a file: {prompt}"
                )
            prompt_path = str(prompt)

        provider_options = dict(provider_options or {})
        exaggeration = float(provider_options.get("exaggeration", 0.5))
        cfg_weight = float(provider_options.get("cfg_weight", 0.5))
        if exaggeration < 0:
            raise ValueError("Chatterbox exaggeration must be greater than or equal to 0.")
        if not 0 <= cfg_weight <= 1:
            raise ValueError("Chatterbox cfg_weight must be between 0 and 1.")

        if self._synthesis_lock is None:
            self._synthesis_lock = asyncio.Lock()
        async with self._synthesis_lock:
            await asyncio.to_thread(
                self._synthesize_sync,
                text,
                language_id,
                filepath,
                prompt_path,
                exaggeration,
                cfg_weight,
            )

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        except ImportError as exc:
            raise RuntimeError(
                "Chatterbox provider requires the optional 'chatterbox-tts' runtime. "
                "Install the supported optional runtime described in "
                "docs/guides/tts_provider.md."
            ) from exc

        self._model = ChatterboxMultilingualTTS.from_pretrained(
            device=self.device,
            t3_model=self.model_name,
        )
        return self._model

    def _synthesize_sync(
        self,
        text: str,
        language_id: str,
        filepath: str,
        reference_audio: str | None,
        exaggeration: float,
        cfg_weight: float,
    ) -> None:
        try:
            import torchaudio
        except ImportError as exc:
            raise RuntimeError(
                "Chatterbox provider requires torchaudio from the optional runtime."
            ) from exc

        model = self._load_model()
        wav = model.generate(
            text,
            language_id=language_id,
            audio_prompt_path=reference_audio,
            exaggeration=exaggeration,
            cfg_weight=cfg_weight,
        )
        output = Path(filepath)
        output.parent.mkdir(parents=True, exist_ok=True)
        torchaudio.save(str(output), wav, model.sr)
