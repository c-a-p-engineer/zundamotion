import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from .components.audio import AudioGenerator
from .components.script_loader import load_script_and_config
from .components.subtitle import SubtitleGenerator
from .components.video import VideoRenderer
from .utils.ffmpeg_utils import get_audio_duration


class GenerationPipeline:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.video_extensions = [
            ".mp4",
            ".mov",
            ".webm",
            ".avi",
            ".mkv",
        ]  # 動画ファイルの拡張子リスト
        self.cache_dir: Optional[Path] = None  # キャッシュディレクトリ

    def _generate_hash(self, data: Dict[str, Any]) -> str:
        """Generates a SHA256 hash from a dictionary."""
        # 辞書をソートしてJSON文字列に変換し、ハッシュを計算
        # 辞書のキーの順序が異なるとハッシュ値が変わるのを防ぐためソート
        sorted_data = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(sorted_data).hexdigest()

    def run(self, output_path: str, keep_intermediate: bool = False):
        """
        Executes the full video generation pipeline.

        Args:
            output_path (str): The final output video file path.
            keep_intermediate (bool): If True, intermediate files are not deleted.
        """
        with tempfile.TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            self.cache_dir = temp_dir / "cache"  # キャッシュディレクトリを設定
            self.cache_dir.mkdir(exist_ok=True)
            print(f"Using temporary directory: {temp_dir}")
            print(f"Using cache directory: {self.cache_dir}")

            # Initialize components
            audio_gen = AudioGenerator(self.config, temp_dir)
            subtitle_gen = SubtitleGenerator(self.config)
            video_renderer = VideoRenderer(self.config, temp_dir)

            all_clips: List[Path] = []
            script = self.config.get("script", {})
            bg_default = self.config.get("background", {}).get("default")

            scenes = script.get("scenes", [])
            total_scenes = len(scenes)
            total_lines = sum(len(s.get("lines", [])) for s in scenes)
            current_line_num = 0

            print("\n--- Starting Video Generation Pipeline ---")

            # Process each scene and line
            for scene_idx, scene in enumerate(scenes):
                scene_id = scene["id"]
                bg_image = scene.get("bg", bg_default)
                bgm_path = scene.get("bgm")
                bgm_volume = scene.get("bgm_volume")

                # 背景が動画かどうかを判断
                is_bg_video = Path(bg_image).suffix.lower() in self.video_extensions

                print(
                    f"\n--- Processing Scene {scene_idx + 1}/{total_scenes}: '{scene_id}' ---"
                )

                for idx, line in enumerate(scene.get("lines", []), start=1):
                    current_line_num += 1
                    line_id = f"{scene_id}_{idx}"
                    text = line["text"]

                    print(
                        f"  [{current_line_num}/{total_lines}] Processing line '{text[:30]}...' (Scene '{scene_id}', Line {idx})"
                    )

                    # キャッシュキーの生成
                    audio_cache_data = {
                        "text": text,
                        "line_config": line,
                        "voice_config": self.config.get("voice", {}),
                    }
                    audio_cache_key = self._generate_hash(audio_cache_data)
                    cached_audio_path = self.cache_dir / f"{audio_cache_key}.wav"

                    # 1. Generate Audio (with cache)
                    if cached_audio_path.exists():
                        audio_path = cached_audio_path
                        print(f"    [Audio] Using cached audio -> {audio_path.name}")
                    else:
                        print(f"    [Audio] Generating audio...")
                        audio_path = audio_gen.generate_audio(text, line, line_id)
                        shutil.copy(audio_path, cached_audio_path)
                        print(
                            f"    [Audio] Generated and cached audio -> {audio_path.name}"
                        )

                    # 2. Get Audio Duration (always needed)
                    duration = get_audio_duration(str(audio_path))

                    # 3. Generate Subtitle Filter (always needed)
                    drawtext_filter = subtitle_gen.get_drawtext_filter(
                        text, duration, line
                    )

                    # ビデオクリップのキャッシュキー生成
                    video_cache_data = {
                        "audio_cache_key": audio_cache_key,
                        "duration": duration,
                        "drawtext_filter": drawtext_filter,
                        "bg_image_path": bg_image,
                        "is_bg_video": is_bg_video,
                        "bgm_path": bgm_path,
                        "bgm_volume": bgm_volume,
                        "video_config": self.config.get("video", {}),
                        "subtitle_config": self.config.get("subtitle", {}),
                        "bgm_config": self.config.get("bgm", {}),
                    }
                    video_cache_key = self._generate_hash(video_cache_data)
                    cached_clip_path = self.cache_dir / f"{video_cache_key}.mp4"

                    # 4. Render Video Clip (with cache)
                    if cached_clip_path.exists():
                        clip_path = cached_clip_path
                        print(f"    [Video] Using cached clip -> {clip_path.name}")
                    else:
                        print(f"    [Video] Rendering clip...")
                        clip_path = video_renderer.render_clip(
                            audio_path,
                            duration,
                            drawtext_filter,
                            bg_image,
                            line_id,
                            bgm_path=bgm_path,
                            bgm_volume=bgm_volume,
                            is_bg_video=is_bg_video,
                        )
                        shutil.copy(clip_path, cached_clip_path)
                        print(
                            f"    [Video] Generated and cached clip -> {clip_path.name}"
                        )

                    all_clips.append(clip_path)

            print("\n--- Concatenating all clips ---")
            # 5. Concatenate all clips
            video_renderer.concat_clips(all_clips, output_path)
            print("--- Video Generation Pipeline Completed ---")

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
