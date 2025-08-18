import os
from pathlib import Path
from typing import Any, Dict

from ..utils.ffmpeg_utils import (
    create_silent_audio,
    get_audio_duration,
    mix_audio_tracks,
)
from .voicevox_client import generate_voice


class AudioGenerator:
    def __init__(self, config: Dict[str, Any], temp_dir: Path):
        self.config = config
        self.temp_dir = temp_dir
        self.voice_config = config.get("voice", {})
        self.voicevox_url = os.getenv(
            "VOICEVOX_URL", self.voice_config.get("url", "http://127.0.0.1:50021")
        )

    def generate_audio(
        self, text: str, line_config: Dict[str, Any], output_filename: str
    ) -> tuple[Path, int, str]:  # Returns (audio_path, speaker_id, text)
        """
        Generates a single audio file for a line of text.

        Args:
            text (str): The text of the line.
            line_config (Dict[str, Any]): The specific config for this line.
            output_filename (str): The base name for the output file (e.g., "scene1_1").

        Returns:
            Path: The path to the generated wav file.
        """
        speech_wav_path = self.temp_dir / f"{output_filename}_speech.wav"
        speech_duration = 0.0  # Initialize speech_duration

        # Determine the required duration for the speech track based on SEs if text is empty
        required_speech_duration_for_ses = 0.0
        sound_effects = line_config.get("sound_effects", [])
        if not text.strip() and sound_effects:
            for se in sound_effects:
                se_path = se["path"]
                se_start_time = se.get("start_time", 0.0)
                se_duration = get_audio_duration(se_path)
                required_speech_duration_for_ses = max(
                    required_speech_duration_for_ses, se_start_time + se_duration
                )
            # Ensure a minimum duration if only SEs are present and text is empty
            if required_speech_duration_for_ses == 0.0:
                required_speech_duration_for_ses = (
                    0.001  # A very small duration to ensure a valid audio file
                )

        if text.strip():  # Only generate voice if text is not empty
            # --- Determine speaker ID based on character expression ---
            speaker_name_from_line = line_config.get(
                "speaker_name"
            )  # Assumes 'speaker_name' is in the script line
            characters_in_line = line_config.get("characters", [])

            # Default speaker ID from line_config or global voice_config
            final_speaker_id = line_config.get(
                "speaker_id", self.voice_config.get("speaker")
            )

            if speaker_name_from_line and speaker_name_from_line in self.config.get(
                "characters", {}
            ):
                char_config = self.config["characters"][speaker_name_from_line]
                char_expression = None

                # Find the expression for this character in the line's characters list
                for char_data in characters_in_line:
                    if char_data.get("name") == speaker_name_from_line:
                        char_expression = char_data.get("expression")
                        break

                if char_expression and char_expression in char_config.get(
                    "voice_styles", {}
                ):
                    final_speaker_id = char_config["voice_styles"][char_expression]
                    print(
                        f"[Audio] Using speaker ID {final_speaker_id} for character '{speaker_name_from_line}' with expression '{char_expression}'."
                    )
                else:
                    # Fallback to default speaker if expression not found or not specified
                    final_speaker_id = char_config.get(
                        "default_speaker_id", final_speaker_id
                    )
                    print(
                        f"[Audio] Using default speaker ID {final_speaker_id} for character '{speaker_name_from_line}'."
                    )
            else:
                # If speaker_name is not provided or not found, use the original speaker_id logic
                # This might need to be more sophisticated if multiple characters are present and one is speaking.
                # For now, if no explicit speaker_name, we stick to the original speaker_id.
                print(
                    f"[Audio] Using original speaker ID {final_speaker_id} (speaker_name not specified or character not found)."
                )

            speaker = final_speaker_id  # Assign the determined speaker ID
            speed = line_config.get("speed", self.voice_config.get("speed"))
            pitch = line_config.get("pitch", self.voice_config.get("pitch"))

            print(f"[Audio] Generating for '{text[:20]}...' -> {speech_wav_path.name}")
            generate_voice(
                text=text,
                speaker=speaker,
                filepath=str(speech_wav_path),
                speed=speed,
                pitch=pitch,
                voicevox_url=self.voicevox_url,
            )
            speech_duration = get_audio_duration(str(speech_wav_path))
        else:
            # If text is empty, create a silent WAV file with duration based on SEs
            print(
                f"[Audio] Empty text, creating silent WAV for {speech_wav_path.name} with duration {required_speech_duration_for_ses}s"
            )
            create_silent_audio(str(speech_wav_path), required_speech_duration_for_ses)
            speech_duration = required_speech_duration_for_ses
            speaker = 0  # Default speaker ID for silent audio
            text = ""  # Empty text for silent audio

        # Handle sound effects
        # sound_effects = line_config.get("sound_effects", []) # Already retrieved above
        if not sound_effects:
            return (
                speech_wav_path,
                speaker,
                text,
            )  # No sound effects, return speech audio directly

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
            se_volume = se.get("volume", 0.0)  # Corrected default volume
            audio_tracks_to_mix.append((se_path, se_start_time, se_volume))
            se_duration = get_audio_duration(se_path)
            max_end_time = max(max_end_time, se_start_time + se_duration)

        # The previous 'if speech_duration == 0 and sound_effects:' block is now handled
        # by required_speech_duration_for_ses and max_end_time calculation.
        # Removing the redundant block.
        # if speech_duration == 0 and sound_effects:
        #     if (
        #         not audio_tracks_to_mix
        #     ):  # Should not happen if sound_effects is not empty and speech_duration is 0
        #         max_end_time = 0.0
        #     else:
        #         # Recalculate max_end_time considering only SEs if speech_duration is 0
        #         # This line is redundant if max_end_time is already correctly calculated above
        #         # but ensures the max is taken if only SEs are present.
        #         max_end_time = max(
        #             se_start_time + get_audio_duration(se_path) for se in sound_effects
        #         )

        # Mix all audio tracks
        mixed_wav_path = self.temp_dir / f"{output_filename}_mixed.wav"
        mix_audio_tracks(
            audio_tracks_to_mix, str(mixed_wav_path), total_duration=max_end_time
        )

        return mixed_wav_path, speaker, text
