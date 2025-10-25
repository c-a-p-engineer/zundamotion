import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ...cache import CacheManager  # CacheManagerをインポート
from ...utils.ffmpeg_params import AudioParams
from ...utils.ffmpeg_probe import get_audio_duration
from ...utils.ffmpeg_audio import create_silent_audio, mix_audio_tracks

from ...utils.logger import logger  # loggerをインポート
from .voicevox_client import generate_voice


class AudioGenerator:
    def __init__(
        self,
        config: Dict[str, Any],
        temp_dir: Path,
        audio_params: AudioParams,
        cache_manager: CacheManager,  # CacheManagerインスタンスを受け取る
    ):
        self.config = config
        self.temp_dir = temp_dir
        self.voice_config = config.get("voice", {})
        self.voicevox_url = os.getenv(
            "VOICEVOX_URL", self.voice_config.get("url", "http://127.0.0.1:50021")
        )
        self.audio_params = audio_params
        self.cache_manager = cache_manager  # インスタンス変数として保持

    async def generate_audio(
        self, text: str, line_config: Dict[str, Any], output_filename: str
    ) -> tuple[Path, List[Tuple[int, str]], List[Dict[str, Any]]]:
        """
        Generates a single audio file for a line of text.

        Args:
            text (str): The text of the line.
            line_config (Dict[str, Any]): The specific config for this line.
            output_filename (str): The base name for the output file (e.g., "scene1_1").

        Returns:
            Path: The path to the generated wav file.
            List[Tuple[int, str]]: Pairs of (speaker_id, text) for reporting.
            List[Dict[str, Any]]: Voice layer metadata for lip-sync (per layer).
        """
        speech_wav_path_base = self.temp_dir / f"{output_filename}_speech"
        speech_duration = 0.0  # Initialize speech_duration
        voice_usage: List[Tuple[int, str]] = []

        voice_layers = line_config.get("voice_layers")
        sound_effects = line_config.get("sound_effects", [])
        layer_voice_segments: List[Dict[str, Any]] = []

        if isinstance(voice_layers, list) and voice_layers:
            audio_tracks_to_mix: List[Tuple[str, float, float]] = []
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
                layer_output = f"{output_filename}_voice{idx+1}"

                layer_line_config: Dict[str, Any] = {
                    key: value
                    for key, value in line_config.items()
                    if key not in {"voice_layers", "sound_effects"}
                }
                layer_line_config.update(layer)
                layer_line_config["sound_effects"] = []

                (
                    layer_audio_path,
                    layer_usage,
                    layer_segments,
                ) = await self.generate_audio(layer_text, layer_line_config, layer_output)
                voice_usage.extend(layer_usage)

                start_time = float(layer.get("start_time", 0.0))
                volume = float(layer.get("volume", 1.0))
                audio_tracks_to_mix.append((str(layer_audio_path), start_time, volume))

                try:
                    layer_duration = await get_audio_duration(str(layer_audio_path))
                except Exception:
                    layer_duration = 0.0
                max_end_time = max(max_end_time, start_time + layer_duration)
                layer_speaker = layer.get("speaker_name") or layer_line_config.get(
                    "speaker_name"
                )

                if layer_segments:
                    for seg in layer_segments:
                        seg_info = dict(seg)
                        seg_info["start_time"] = start_time + float(
                            seg_info.get("start_time", 0.0)
                        )
                        seg_info.setdefault("duration", layer_duration)
                        seg_info.setdefault("volume", volume)
                        seg_info.setdefault("speaker_name", layer_speaker)
                        seg_info["layer_origin"] = idx
                        layer_voice_segments.append(seg_info)
                else:
                    layer_voice_segments.append(
                        {
                            "speaker_name": layer_speaker,
                            "audio_path": layer_audio_path,
                            "start_time": start_time,
                            "duration": layer_duration,
                            "volume": volume,
                            "layer_origin": idx,
                        }
                    )

            for se in sound_effects:
                se_path = se["path"]
                se_start_time = float(se.get("start_time", 0.0))
                se_volume = float(se.get("volume", 1.0))
                audio_tracks_to_mix.append((se_path, se_start_time, se_volume))
                se_duration = await get_audio_duration(se_path)
                max_end_time = max(max_end_time, se_start_time + se_duration)

            if not audio_tracks_to_mix:
                silent_path = speech_wav_path_base.with_suffix(".wav")
                await create_silent_audio(
                    str(silent_path),
                    0.001,
                    self.audio_params,
                )
                return silent_path, voice_usage

            total_duration = max(max_end_time, 0.001)
            mixed_wav_path = self.temp_dir / f"{output_filename}_mixed.wav"
            await mix_audio_tracks(
                audio_tracks_to_mix,
                str(mixed_wav_path),
                total_duration=total_duration,
                audio_params=self.audio_params,
            )
            return mixed_wav_path, voice_usage, layer_voice_segments

        # Determine the required duration for the speech track based on SEs if text is empty
        required_speech_duration_for_ses = 0.0
        if not text.strip() and sound_effects:
            for se in sound_effects:
                se_path = se["path"]
                se_start_time = se.get("start_time", 0.0)
                se_duration = await get_audio_duration(se_path)
                required_speech_duration_for_ses = max(
                    required_speech_duration_for_ses, se_start_time + se_duration
                )
            # Ensure a minimum duration if only SEs are present and text is empty
            if required_speech_duration_for_ses == 0.0:
                required_speech_duration_for_ses = (
                    0.001  # A very small duration to ensure a valid audio file
                )

        if text.strip():  # Only generate voice if text is not empty
            # speaker_id, speed, and pitch should already be merged into line_config by script_loader.py
            # Use values directly from line_config, falling back to global voice_config if not present
            speaker = line_config.get("speaker_id", self.voice_config.get("speaker"))
            speed = line_config.get("speed", self.voice_config.get("speed"))
            pitch = line_config.get("pitch", self.voice_config.get("pitch"))

            if speaker is None:
                raise ValueError(
                    f"Speaker ID not found for line: '{text[:30]}...'. "
                    "Please ensure 'speaker_id' is defined in defaults or line_config."
                )

            # VOICEVOX合成パラメータをキャッシュキーに含める
            voice_key_data = {
                "text": text,
                "speaker": speaker,
                "speed": speed,
                "pitch": pitch,
                "voicevox_url": self.voicevox_url,
                "audio_params": self.audio_params.__dict__,  # AudioParamsもキャッシュキーに含める
            }

            async def creator_func(output_path: Path) -> Path:
                logger.info(
                    f"[Audio] Generating for '{text[:20]}...' with speaker_id={speaker}, speed={speed}, pitch={pitch} -> {output_path.name}"
                )
                await generate_voice(
                    text=text,
                    speaker=speaker,
                    filepath=str(output_path),
                    speed=speed,
                    pitch=pitch,
                    voicevox_url=self.voicevox_url,
                )
                return output_path

            speech_wav_path = await self.cache_manager.get_or_create(
                key_data=voice_key_data,
                file_name=f"{output_filename}_speech",
                extension="wav",
                creator_func=creator_func,
            )
            speech_duration = await get_audio_duration(str(speech_wav_path))
            voice_usage.append((int(speaker), text))
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
            # If text is empty, create a silent WAV file with duration based on SEs
            speech_wav_path = speech_wav_path_base.with_suffix(
                ".wav"
            )  # キャッシュを使わないので、ここでパスを確定
            logger.info(
                f"[Audio] Empty text, creating silent WAV for {speech_wav_path.name} with duration {required_speech_duration_for_ses}s"
            )
            await create_silent_audio(
                str(speech_wav_path),
                required_speech_duration_for_ses,
                self.audio_params,
            )
            speech_duration = required_speech_duration_for_ses

        # Handle sound effects
        # sound_effects = line_config.get("sound_effects", []) # Already retrieved above
        if not sound_effects:
            return speech_wav_path, voice_usage, layer_voice_segments

        # Prepare audio tracks for mixing
        audio_tracks_to_mix = []
        # Always add speech track, even if silent, to ensure it's part of the mix
        audio_tracks_to_mix.append(
            (str(speech_wav_path), 0.0, 1.0)
        )  # (path, start_time, volume)

        max_end_time = speech_duration

        for se in sound_effects:
            se_path = se["path"]
            se_start_time = se.get("start_time", 0.0)
            se_volume = se.get("volume", 1.0)
            audio_tracks_to_mix.append((se_path, se_start_time, se_volume))
            se_duration = await get_audio_duration(se_path)
            max_end_time = max(max_end_time, se_start_time + se_duration)

        # Mix all audio tracks
        mixed_wav_path = self.temp_dir / f"{output_filename}_mixed.wav"
        await mix_audio_tracks(
            audio_tracks_to_mix,
            str(mixed_wav_path),
            total_duration=max_end_time,
            audio_params=self.audio_params,
        )

        return mixed_wav_path, voice_usage, layer_voice_segments
