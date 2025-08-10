import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from .components.audio import AudioGenerator
from .components.script_loader import load_script_and_config
from .components.subtitle import SubtitleGenerator
from .components.video import VideoRenderer
from .utils.ffmpeg_utils import get_audio_duration


class GenerationPipeline:
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def run(self, output_path: str, keep_intermediate: bool = False):
        """
        Executes the full video generation pipeline.

        Args:
            output_path (str): The final output video file path.
            keep_intermediate (bool): If True, intermediate files are not deleted.
        """
        with tempfile.TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            print(f"Using temporary directory: {temp_dir}")

            # Initialize components
            audio_gen = AudioGenerator(self.config, temp_dir)
            subtitle_gen = SubtitleGenerator(self.config)
            video_renderer = VideoRenderer(self.config, temp_dir)

            all_clips: List[Path] = []
            script = self.config.get("script", {})
            bg_default = self.config.get("background", {}).get("default")

            # Process each scene and line
            for scene in script.get("scenes", []):
                scene_id = scene["id"]
                bg_image = scene.get("bg", bg_default)

                for idx, line in enumerate(scene.get("lines", []), start=1):
                    line_id = f"{scene_id}_{idx}"
                    text = line["text"]

                    # 1. Generate Audio
                    audio_path = audio_gen.generate_audio(text, line, line_id)

                    # 2. Get Audio Duration
                    duration = get_audio_duration(str(audio_path))

                    # 3. Generate Subtitle Filter
                    drawtext_filter = subtitle_gen.get_drawtext_filter(
                        text, duration, line
                    )

                    # 4. Render Video Clip
                    clip_path = video_renderer.render_clip(
                        audio_path, duration, drawtext_filter, bg_image, line_id
                    )
                    all_clips.append(clip_path)

            # 5. Concatenate all clips
            video_renderer.concat_clips(all_clips, output_path)

            if keep_intermediate:
                intermediate_dir = Path(output_path).parent / "intermediate"
                shutil.copytree(temp_dir, intermediate_dir)
                print(f"Intermediate files saved to: {intermediate_dir}")


def run_generation(script_path: str, output_path: str, keep_intermediate: bool = False):
    """
    High-level function to run the entire generation process.
    """
    # Get the path to the default config file
    default_config_path = Path(__file__).parent / "templates" / "config.yaml"

    # Load script and config
    config = load_script_and_config(script_path, str(default_config_path))

    # Create and run the pipeline
    pipeline = GenerationPipeline(config)
    pipeline.run(output_path, keep_intermediate)
