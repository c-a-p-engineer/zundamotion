import os
from pathlib import Path
from typing import Any, Dict

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
    ) -> Path:
        """
        Generates a single audio file for a line of text.

        Args:
            text (str): The text of the line.
            line_config (Dict[str, Any]): The specific config for this line.
            output_filename (str): The base name for the output file (e.g., "scene1_1").

        Returns:
            Path: The path to the generated wav file.
        """
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

        wav_path = self.temp_dir / f"{output_filename}.wav"

        print(f"[Audio] Generating for '{text[:20]}...' -> {wav_path.name}")
        generate_voice(
            text=text,
            speaker=speaker,
            filepath=str(wav_path),
            speed=speed,
            pitch=pitch,
            voicevox_url=self.voicevox_url,
        )
        return wav_path
