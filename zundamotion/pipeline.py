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

            audio_gen = AudioGenerator(self.config, temp_dir)
            subtitle_gen = SubtitleGenerator(self.config)
            video_renderer = VideoRenderer(self.config, temp_dir)

            script = self.config.get("script", {})
            scenes = script.get("scenes", [])
            total_lines = sum(len(s.get("lines", [])) for s in scenes)
            current_line_num = 0

            # --- フェーズ1: 全ての音声生成とdurationの計算 ---
            # line_id -> {audio_path, duration, text, line_config}
            line_data_map: Dict[str, Dict[str, Any]] = {}

            print("\n--- Phase 1: Generating all audio and calculating durations ---")
            for scene_idx, scene in enumerate(scenes):
                scene_id = scene["id"]
                for idx, line in enumerate(scene.get("lines", []), start=1):
                    current_line_num += 1
                    line_id = f"{scene_id}_{idx}"
                    text = line["text"]

                    print(
                        f"  [{current_line_num}/{total_lines}] Processing audio for line '{text[:30]}...' (Scene '{scene_id}', Line {idx})"
                    )

                    audio_cache_data = {
                        "text": text,
                        "line_config": line,
                        "voice_config": self.config.get("voice", {}),
                    }
                    audio_cache_key = self._generate_hash(audio_cache_data)
                    cached_audio_path = self.cache_dir / f"{audio_cache_key}.wav"

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

                    duration = get_audio_duration(str(audio_path))
                    line_data_map[line_id] = {
                        "audio_path": audio_path,
                        "duration": duration,
                        "text": text,
                        "line_config": line,
                    }
            print("--- Phase 1 Completed ---")

            # --- フェーズ2: シーンごとの背景動画の準備とクリップのレンダリング ---
            all_clips: List[Path] = []
            bg_default = self.config.get("background", {}).get("default")
            total_scenes = len(scenes)
            current_line_num = 0  # リセットしてフェーズ2で再利用

            print("\n--- Phase 2: Preparing scene backgrounds and rendering clips ---")
            for scene_idx, scene in enumerate(scenes):
                scene_id = scene["id"]
                bg_image = scene.get("bg", bg_default)
                bgm_path = scene.get("bgm")
                bgm_volume = scene.get("bgm_volume")

                is_bg_video = Path(bg_image).suffix.lower() in self.video_extensions

                print(
                    f"\n--- Processing Scene {scene_idx + 1}/{total_scenes}: '{scene_id}' ---"
                )

                # シーン全体のdurationを計算
                scene_duration = 0.0
                for idx, line in enumerate(scene.get("lines", []), start=1):
                    line_id = f"{scene_id}_{idx}"
                    scene_duration += line_data_map[line_id]["duration"]

                # シーンの背景が動画の場合、シーン全体の長さでループする背景動画を生成
                scene_bg_video_path: Optional[Path] = None
                if is_bg_video:
                    scene_bg_video_filename = f"scene_bg_{scene_id}"
                    scene_bg_video_path = video_renderer.render_looped_background_video(
                        bg_image, scene_duration, scene_bg_video_filename
                    )
                    print(
                        f"    [Video] Generated looped scene background video -> {scene_bg_video_path.name}"
                    )

                current_scene_time = 0.0  # シーン内での現在の時間
                for idx, line in enumerate(scene.get("lines", []), start=1):
                    current_line_num += 1
                    line_id = f"{scene_id}_{idx}"
                    text = line_data_map[line_id]["text"]
                    audio_path = line_data_map[line_id]["audio_path"]
                    duration = line_data_map[line_id]["duration"]
                    line_config = line_data_map[line_id]["line_config"]

                    print(
                        f"  [{current_line_num}/{total_lines}] Rendering clip for line '{text[:30]}...' (Scene '{scene_id}', Line {idx})"
                    )

                    # 3. Generate Subtitle Filter (always needed)
                    drawtext_filter = subtitle_gen.get_drawtext_filter(
                        text, duration, line_config
                    )

                    # ビデオクリップのキャッシュキー生成
                    video_cache_data = {
                        "audio_cache_key": self._generate_hash(
                            {
                                "text": text,
                                "line_config": line_config,
                                "voice_config": self.config.get("voice", {}),
                            }
                        ),
                        "duration": duration,
                        "drawtext_filter": drawtext_filter,
                        "bg_image_path": bg_image,  # オリジナルのbg_image_pathをキャッシュキーに含める
                        "is_bg_video": is_bg_video,
                        "bgm_path": bgm_path,
                        "bgm_volume": bgm_volume,
                        "start_time": current_scene_time,  # start_timeもキャッシュキーに含める
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
                            (
                                str(scene_bg_video_path) if is_bg_video else bg_image
                            ),  # シーン背景動画を使用
                            line_id,
                            bgm_path=bgm_path,
                            bgm_volume=bgm_volume,
                            is_bg_video=is_bg_video,
                            start_time=current_scene_time,  # シーン内での開始時間を渡す
                        )
                        shutil.copy(clip_path, cached_clip_path)
                        print(
                            f"    [Video] Generated and cached clip -> {clip_path.name}"
                        )

                    all_clips.append(clip_path)
                    current_scene_time += duration  # 次のラインの開始時間を更新

                # シーンの処理が完了したら、一時的なシーン背景動画を削除
                if scene_bg_video_path and scene_bg_video_path.exists():
                    scene_bg_video_path.unlink()
                    print(
                        f"    [Video] Cleaned up temporary scene background video -> {scene_bg_video_path.name}"
                    )

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
