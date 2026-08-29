"""AudioGenerator-compatible orchestration for Chatterbox Multilingual TTS."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ...cache import CacheManager
from ...exceptions import CacheError
from ...utils.ffmpeg_audio import (
    AUDIO_MIX_VERSION,
    INTERMEDIATE_AUDIO_FORMAT_VERSION,
    create_silent_audio,
    mix_audio_tracks,
)
from ...utils.ffmpeg_params import AudioParams
from ...utils.logger import logger
from .chatterbox_provider import (
    CHATTERBOX_DEFAULT_LANGUAGE,
    CHATTERBOX_DEFAULT_MODEL,
    CHATTERBOX_LANGUAGES,
    ChatterboxTTSProvider,
)
from .generator import _estimate_silent_duration


class ChatterboxAudioGenerator:
    """Generate Chatterbox speech while preserving existing audio pipeline contracts."""

    def __init__(
        self,
        config: Dict[str, Any],
        temp_dir: Path,
        audio_params: AudioParams,
        cache_manager: CacheManager,
    ) -> None:
        self.config = config
        self.temp_dir = temp_dir
        self.voice_config = config.get("voice", {}) or {}
        self.audio_params = audio_params
        self.intermediate_audio_params = audio_params.for_intermediate()
        self.cache_manager = cache_manager
        self.provider = ChatterboxTTSProvider(
            model=str(self.voice_config.get("model", CHATTERBOX_DEFAULT_MODEL)),
            device=str(self.voice_config.get("device", "cpu")),
        )
        self._engine_version_cache: str | None = None

    async def _get_engine_version(self) -> str:
        if self._engine_version_cache is None:
            self._engine_version_cache = await self.provider.engine_version()
        return self._engine_version_cache

    async def generate_audio(
        self,
        text: str,
        line_config: Dict[str, Any],
        output_filename: str,
    ) -> tuple[Path, List[Tuple[int, str]], List[Dict[str, Any]]]:
        """Generate one line with the same return contract as the VOICEVOX generator."""

        speech_wav_path_base = self.temp_dir / f"{output_filename}_speech"
        voice_usage: List[Tuple[int, str]] = []
        voice_layers = line_config.get("voice_layers")
        sound_effects = line_config.get("sound_effects", [])
        layer_voice_segments: List[Dict[str, Any]] = []

        if isinstance(voice_layers, list) and voice_layers:
            return await self._generate_voice_layers(
                text=text,
                line_config=line_config,
                output_filename=output_filename,
                voice_layers=voice_layers,
                sound_effects=sound_effects,
            )

        required_speech_duration_for_ses = await self._required_sfx_duration(
            text, sound_effects
        )
        voice_enabled = bool(self.voice_config.get("enabled", True))

        if text.strip() and voice_enabled:
            speech_wav_path, speech_duration = await self._generate_speech(
                text=text,
                line_config=line_config,
            )
            layer_voice_segments.append(
                {
                    "speaker_name": line_config.get("speaker_name"),
                    "audio_path": speech_wav_path,
                    "start_time": 0.0,
                    "duration": speech_duration,
                    "volume": 1.0,
                    "layer_origin": None,
                }
            )
        else:
            speech_wav_path = speech_wav_path_base.with_suffix(".wav")
            silent_duration = max(
                _estimate_silent_duration(text, line_config, self.voice_config),
                required_speech_duration_for_ses,
                0.001,
            )
            logger.info(
                "[Audio] Using silent WAV for %s with duration %.3fs",
                speech_wav_path.name,
                silent_duration,
            )
            await create_silent_audio(
                str(speech_wav_path),
                silent_duration,
                self.intermediate_audio_params,
            )
            speech_duration = silent_duration

        if not sound_effects:
            return speech_wav_path, voice_usage, layer_voice_segments

        mixed_wav_path = await self._mix_sound_effects(
            output_filename=output_filename,
            speech_wav_path=speech_wav_path,
            speech_duration=speech_duration,
            sound_effects=sound_effects,
        )
        return mixed_wav_path, voice_usage, layer_voice_segments

    async def _generate_speech(
        self,
        *,
        text: str,
        line_config: Dict[str, Any],
    ) -> tuple[Path, float]:
        language = str(
            line_config.get(
                "language",
                self.voice_config.get("language", CHATTERBOX_DEFAULT_LANGUAGE),
            )
            or CHATTERBOX_DEFAULT_LANGUAGE
        ).strip().lower()
        if language not in CHATTERBOX_LANGUAGES:
            raise ValueError(
                f"Unsupported Chatterbox language {language!r}. "
                f"Supported languages: {list(CHATTERBOX_LANGUAGES)}"
            )

        reference_audio = line_config.get(
            "reference_audio", self.voice_config.get("reference_audio")
        )
        reference_path: Path | None = None
        reference_hash = "none"
        if reference_audio:
            reference_path = Path(str(reference_audio)).expanduser().resolve()
            if not reference_path.is_file():
                raise ValueError(
                    "Chatterbox reference_audio does not exist or is not a file: "
                    f"{reference_path}"
                )
            reference_hash = _sha256_file(reference_path)

        exaggeration = float(
            line_config.get(
                "exaggeration", self.voice_config.get("exaggeration", 0.5)
            )
        )
        cfg_weight = float(
            line_config.get("cfg_weight", self.voice_config.get("cfg_weight", 0.5))
        )
        engine_version = await self._get_engine_version()
        key_data = {
            "kind": "chatterbox_speech",
            "provider": self.provider.provider_id,
            "text": text,
            "language": language,
            "model": self.provider.model_name,
            "device": self.provider.device,
            "reference_audio_sha256": reference_hash,
            "exaggeration": exaggeration,
            "cfg_weight": cfg_weight,
            "chatterbox_engine_version": engine_version,
            "audio_params": self.intermediate_audio_params.__dict__,
            "intermediate_audio_format_version": INTERMEDIATE_AUDIO_FORMAT_VERSION,
            "audio_mix_version": AUDIO_MIX_VERSION,
        }

        async def creator_func(output_path: Path) -> Path:
            logger.info(
                "[Audio] Chatterbox language=%s model=%s reference=%s -> %s",
                language,
                self.provider.model_name,
                reference_path.name if reference_path else "default",
                output_path.name,
            )
            await self.provider.synthesize(
                text=text,
                speaker=None,
                filepath=str(output_path),
                language=language,
                reference_audio=str(reference_path) if reference_path else None,
                provider_options={
                    "exaggeration": exaggeration,
                    "cfg_weight": cfg_weight,
                },
            )
            return output_path

        try:
            speech_wav_path = await self.cache_manager.get_or_create(
                key_data=key_data,
                file_name="voice_speech",
                extension="wav",
                creator_func=creator_func,
            )
            duration = float(
                await self.cache_manager.get_or_create_media_duration(speech_wav_path)
            )
            return speech_wav_path, duration
        except (CacheError, OSError, RuntimeError, ValueError) as exc:
            logger.error(
                "[Audio] Chatterbox synthesis failed (language=%s, model=%s): %s. "
                "Aborting render to avoid silent output.",
                language,
                self.provider.model_name,
                exc,
            )
            raise RuntimeError(
                "Chatterbox synthesis failed; render aborted to avoid silent output: "
                f"{exc}"
            ) from exc

    async def _generate_voice_layers(
        self,
        *,
        text: str,
        line_config: Dict[str, Any],
        output_filename: str,
        voice_layers: List[Dict[str, Any]],
        sound_effects: List[Dict[str, Any]],
    ) -> tuple[Path, List[Tuple[int, str]], List[Dict[str, Any]]]:
        audio_tracks: List[Tuple[str, float, float]] = []
        voice_usage: List[Tuple[int, str]] = []
        segments: List[Dict[str, Any]] = []
        max_end_time = 0.0

        for idx, layer in enumerate(voice_layers):
            if not isinstance(layer, dict):
                continue
            layer_text = str(
                layer.get("reading")
                or layer.get("read")
                or layer.get("text")
                or text
            )
            layer_config = {
                key: value
                for key, value in line_config.items()
                if key not in {"voice_layers", "sound_effects"}
            }
            layer_config.update(layer)
            layer_config["sound_effects"] = []
            layer_path, _, layer_segments = await self.generate_audio(
                layer_text,
                layer_config,
                f"{output_filename}_voice{idx + 1}",
            )
            start_time = float(layer.get("start_time", 0.0))
            volume = float(layer.get("volume", 1.0))
            duration = float(
                await self.cache_manager.get_or_create_media_duration(layer_path)
            )
            audio_tracks.append((str(layer_path), start_time, volume))
            max_end_time = max(max_end_time, start_time + duration)
            speaker_name = layer.get("speaker_name") or layer_config.get("speaker_name")
            for segment in layer_segments or [{}]:
                item = dict(segment)
                item["speaker_name"] = item.get("speaker_name") or speaker_name
                item["audio_path"] = item.get("audio_path") or layer_path
                item["start_time"] = start_time + float(item.get("start_time", 0.0))
                item["duration"] = float(item.get("duration", duration))
                item["volume"] = float(item.get("volume", volume))
                item["layer_origin"] = idx
                segments.append(item)

        for se in sound_effects:
            se_path = str(se["path"])
            start_time = float(se.get("start_time", 0.0))
            volume = float(se.get("volume", 1.0))
            duration = float(
                await self.cache_manager.get_or_create_media_duration(Path(se_path))
            )
            audio_tracks.append((se_path, start_time, volume))
            max_end_time = max(max_end_time, start_time + duration)

        if not audio_tracks:
            silent = self.temp_dir / f"{output_filename}_speech.wav"
            await create_silent_audio(
                str(silent), 0.001, self.intermediate_audio_params
            )
            return silent, voice_usage, segments

        output = self.temp_dir / f"{output_filename}_mixed.wav"
        await mix_audio_tracks(
            audio_tracks,
            str(output),
            total_duration=max(max_end_time, 0.001),
            audio_params=self.intermediate_audio_params,
        )
        return output, voice_usage, segments

    async def _required_sfx_duration(
        self,
        text: str,
        sound_effects: List[Dict[str, Any]],
    ) -> float:
        if text.strip() or not sound_effects:
            return 0.0
        required = 0.0
        for se in sound_effects:
            duration = float(
                await self.cache_manager.get_or_create_media_duration(Path(se["path"]))
            )
            required = max(required, float(se.get("start_time", 0.0)) + duration)
        return max(required, 0.001)

    async def _mix_sound_effects(
        self,
        *,
        output_filename: str,
        speech_wav_path: Path,
        speech_duration: float,
        sound_effects: List[Dict[str, Any]],
    ) -> Path:
        tracks: List[Tuple[str, float, float]] = [
            (str(speech_wav_path), 0.0, 1.0)
        ]
        max_end_time = speech_duration
        for se in sound_effects:
            path = str(se["path"])
            start_time = float(se.get("start_time", 0.0))
            volume = float(se.get("volume", 1.0))
            duration = float(
                await self.cache_manager.get_or_create_media_duration(Path(path))
            )
            tracks.append((path, start_time, volume))
            max_end_time = max(max_end_time, start_time + duration)

        output = self.temp_dir / f"{output_filename}_mixed.wav"
        await mix_audio_tracks(
            tracks,
            str(output),
            total_duration=max_end_time,
            audio_params=self.intermediate_audio_params,
        )
        return output


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
