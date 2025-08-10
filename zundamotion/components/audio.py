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
        speaker = line_config.get("speaker", self.voice_config.get("speaker"))
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
