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
from .utils.ffmpeg_utils import add_bgm_to_video, get_audio_duration


class GenerationPipeline:
    def __init__(
        self,
        config: Dict[str, Any],
        no_cache: bool = False,
        cache_refresh: bool = False,
        jobs: str = "1",
    ):
        self.config = config
        self.no_cache = no_cache
        self.cache_refresh = cache_refresh
        self.jobs = jobs
        self.video_extensions = [
            ".mp4",
            ".mov",
            ".webm",
            ".avi",
            ".mkv",
        ]  # 動画ファイルの拡張子リスト
        self.cache_dir: Optional[Path] = None  # キャッシュディレクトリ

    def _generate_hash(self, data: Dict[str, Any]) -> str:
        """Generates a SHA256 hash from a dictionary, handling Path objects."""

        # Path オブジェクトを文字列に変換するカスタムエンコーダ
        class PathEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, Path):
                    return str(obj)
                return json.JSONEncoder.default(self, obj)

        # 辞書をソートしてJSON文字列に変換し、ハッシュを計算
        # 辞書のキーの順序が異なるとハッシュ値が変わるのを防ぐためソート
        sorted_data = json.dumps(data, sort_keys=True, cls=PathEncoder).encode("utf-8")
        return hashlib.sha256(sorted_data).hexdigest()

    def _generate_scene_hash(self, scene: Dict[str, Any]) -> str:
        """Generates a SHA256 hash for a scene based on its content and relevant config."""
        # シーンのID、ライン、背景、BGM、および関連するグローバル設定をハッシュに含める
        # BGM設定は辞書になったため、そのまま含める
        scene_data = {
            "id": scene.get("id"),
            "lines": scene.get("lines", []),
            "bg": scene.get("bg"),
            "bgm": scene.get("bgm"),  # bgm は辞書としてそのまま含める
            # "bgm_volume": scene.get("bgm_volume"), # bgm_volume は bgm 辞書の中に移動したため削除
            "voice_config": self.config.get("voice", {}),
            "video_config": self.config.get("video", {}),
            "subtitle_config": self.config.get("subtitle", {}),
            "bgm_config": self.config.get(
                "bgm", {}
            ),  # グローバルBGM設定もそのまま含める
            "background_default": self.config.get("background", {}).get("default"),
        }

        # デバッグログの追加
        print(
            f"  [DEBUG] _generate_scene_hash - scene_data before hashing: {scene_data}"
        )
        print(
            f"  [DEBUG] _generate_scene_hash - Type of scene_data: {type(scene_data)}"
        )

        return self._generate_hash(scene_data)

    def run(self, output_path: str, keep_intermediate: bool = False):
        """
        Executes the full video generation pipeline.

        Args:
            output_path (str): The final output video file path.
            keep_intermediate (bool): If True, intermediate files are not deleted.
        """
        with tempfile.TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            # キャッシュディレクトリを永続的な場所に変更
            self.cache_dir = Path(
                "cache"
            )  # プロジェクトルートに'cache'ディレクトリを作成
            self.cache_dir.mkdir(exist_ok=True)

            print(f"Using temporary directory: {temp_dir}")
            print(f"Using persistent cache directory: {self.cache_dir}")

            if self.no_cache:
                print("Cache is disabled (--no-cache). All files will be regenerated.")
                # キャッシュディレクトリの内容をクリア
                if self.cache_dir.exists():
                    shutil.rmtree(self.cache_dir)
                    self.cache_dir.mkdir(exist_ok=True)
            elif self.cache_refresh:
                print(
                    "Cache refresh requested (--cache-refresh). All files will be regenerated and cache updated."
                )
                # キャッシュディレクトリの内容をクリア
                if self.cache_dir.exists():
                    shutil.rmtree(self.cache_dir)
                    self.cache_dir.mkdir(exist_ok=True)
            else:
                print(
                    "Using existing cache. Use --no-cache to disable or --cache-refresh to force regeneration."
                )

            audio_gen = AudioGenerator(self.config, temp_dir)
            subtitle_gen = SubtitleGenerator(self.config)
            video_renderer = VideoRenderer(self.config, temp_dir, self.jobs)

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
                scene_hash = self._generate_scene_hash(scene)
                cached_scene_video_path = self.cache_dir / f"scene_{scene_hash}.mp4"

                print(
                    f"\n--- Processing Scene {scene_idx + 1}/{total_scenes}: '{scene_id}' ---"
                )

                if not self.no_cache and cached_scene_video_path.exists():
                    print(
                        f"    [Scene] Using cached scene video -> {cached_scene_video_path.name}"
                    )
                    all_clips.append(cached_scene_video_path)
                    # このシーンのライン数をスキップするために current_line_num を更新
                    current_line_num += sum(len(s.get("lines", [])) for s in [scene])
                    continue  # このシーンのレンダリングをスキップ

                # シーンがキャッシュされていない、またはキャッシュが無効な場合、通常通りレンダリング
                bg_image = scene.get("bg", bg_default)
                bgm_path = scene.get("bgm")
                bgm_volume = scene.get("bgm_volume")

                is_bg_video = Path(bg_image).suffix.lower() in self.video_extensions

                # シーン全体のdurationを計算
                scene_duration = 0.0
                scene_line_clips: List[Path] = []  # シーン内のクリップを一時的に保持
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
                        # "bgm_path": bgm_path, # BGMはrender_clipでは処理しないため、キャッシュキーから削除
                        # "bgm_volume": bgm_volume, # BGMはrender_clipでは処理しないため、キャッシュキーから削除
                        "start_time": current_scene_time,  # start_timeもキャッシュキーに含める
                        "video_config": self.config.get("video", {}),
                        "subtitle_config": self.config.get("subtitle", {}),
                        "bgm_config": self.config.get(
                            "bgm", {}
                        ),  # グローバルBGM設定もキャッシュキーに含める
                    }
                    video_cache_key = self._generate_hash(video_cache_data)
                    cached_clip_path = self.cache_dir / f"{video_cache_key}.mp4"

                    # 4. Render Video Clip (with cache)
                    if not self.no_cache and cached_clip_path.exists():
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
                            is_bg_video=is_bg_video,
                            start_time=current_scene_time,  # シーン内での開始時間を渡す
                        )
                        if not self.no_cache:
                            shutil.copy(clip_path, cached_clip_path)
                            print(
                                f"    [Video] Generated and cached clip -> {clip_path.name}"
                            )
                        else:
                            print(f"    [Video] Generated clip -> {clip_path.name}")

                    scene_line_clips.append(clip_path)
                    current_scene_time += duration  # 次のラインの開始時間を更新

                # シーン内のクリップを結合してシーン動画を生成
                if scene_line_clips:
                    scene_output_path = temp_dir / f"scene_output_{scene_id}.mp4"
                    video_renderer.concat_clips(
                        scene_line_clips, str(scene_output_path)
                    )
                    print(
                        f"    [Scene] Concatenated scene clips -> {scene_output_path.name}"
                    )
                    all_clips.append(scene_output_path)

                    # シーン動画をキャッシュに保存
                    if not self.no_cache:
                        shutil.copy(scene_output_path, cached_scene_video_path)
                        print(
                            f"    [Scene] Cached scene video -> {cached_scene_video_path.name}"
                        )

                # シーンの処理が完了したら、一時的なシーン背景動画を削除
                if scene_bg_video_path and scene_bg_video_path.exists():
                    scene_bg_video_path.unlink()
                    print(
                        f"    [Video] Cleaned up temporary scene background video -> {scene_bg_video_path.name}"
                    )

            print(
                "\n--- Phase 3: Applying BGM to scenes and preparing for final concat ---"
            )
            final_clips_for_concat: List[Path] = []
            for scene_idx, scene in enumerate(scenes):  # scenes をループ
                # all_clips から対応するシーンのクリップパスを取得
                # all_clips はフェーズ2で結合されたシーン動画のリスト
                # all_clips のインデックスと scenes のインデックスは一致するはず

                # デバッグログの追加
                print(f"  [DEBUG] Processing scene_idx: {scene_idx}")
                print(f"  [DEBUG] Type of scene: {type(scene)}, Value: {scene}")

                if scene_idx >= len(all_clips):
                    print(
                        f"  [ERROR] scene_idx {scene_idx} is out of bounds for all_clips (length {len(all_clips)})"
                    )
                    raise IndexError(
                        "Scene index out of bounds for all_clips. This indicates a mismatch between scenes and generated clips."
                    )

                scene_clip_path = all_clips[scene_idx]
                print(
                    f"  [DEBUG] Type of scene_clip_path: {type(scene_clip_path)}, Value: {scene_clip_path}"
                )

                scene_bgm_config = scene.get("bgm", {})

                bgm_path = scene_bgm_config.get("path")
                bgm_volume = scene_bgm_config.get(
                    "volume", self.config.get("bgm", {}).get("volume", 0.5)
                )
                bgm_start_time = scene_bgm_config.get(
                    "start_time", self.config.get("bgm", {}).get("start_time", 0.0)
                )
                fade_in_duration = scene_bgm_config.get(
                    "fade_in_duration",
                    self.config.get("bgm", {}).get("fade_in_duration", 0.0),
                )
                fade_out_duration = scene_bgm_config.get(
                    "fade_out_duration",
                    self.config.get("bgm", {}).get("fade_out_duration", 0.0),
                )

                if bgm_path:
                    print(
                        f"  Applying BGM to scene {scene_idx + 1} ('{scene['id']}') with '{bgm_path}'"
                    )
                    scene_output_with_bgm_path = (
                        temp_dir / f"scene_with_bgm_{scene_idx}.mp4"
                    )
                    add_bgm_to_video(
                        video_path=str(scene_clip_path),
                        bgm_path=bgm_path,
                        output_path=str(scene_output_with_bgm_path),
                        bgm_volume=bgm_volume,
                        bgm_start_time=bgm_start_time,
                        fade_in_duration=fade_in_duration,
                        fade_out_duration=fade_out_duration,
                        video_duration=get_audio_duration(
                            str(scene_clip_path)
                        ),  # シーン動画の長さを取得
                    )
                    final_clips_for_concat.append(scene_output_with_bgm_path)
                else:
                    final_clips_for_concat.append(scene_clip_path)

            print("\n--- Phase 4: Final Concatenation and Global BGM Application ---")
            final_output_path_temp = temp_dir / "final_video_no_global_bgm.mp4"
            video_renderer.concat_clips(
                final_clips_for_concat, str(final_output_path_temp)
            )

            global_bgm_config = self.config.get("bgm", {})
            global_bgm_path = global_bgm_config.get("path")
            global_bgm_volume = global_bgm_config.get("volume", 0.5)
            global_bgm_start_time = global_bgm_config.get("start_time", 0.0)
            global_fade_in_duration = global_bgm_config.get("fade_in_duration", 0.0)
            global_fade_out_duration = global_bgm_config.get("fade_out_duration", 0.0)

            if global_bgm_path:
                print(f"  Applying global BGM with '{global_bgm_path}' to final video.")
                add_bgm_to_video(
                    video_path=str(final_output_path_temp),
                    bgm_path=global_bgm_path,
                    output_path=str(Path(output_path)),  # 最終出力パスに保存
                    bgm_volume=global_bgm_volume,
                    bgm_start_time=global_bgm_start_time,
                    fade_in_duration=global_fade_in_duration,
                    fade_out_duration=global_fade_out_duration,
                    video_duration=get_audio_duration(str(final_output_path_temp)),
                )
            else:
                # グローバルBGMがない場合、一時的な最終動画を最終出力パスにコピー
                shutil.copy(final_output_path_temp, Path(output_path))

            print("--- Video Generation Pipeline Completed ---")

            if keep_intermediate:
                intermediate_dir = Path(output_path).parent / "intermediate"
                shutil.copytree(temp_dir, intermediate_dir)
                print(f"Intermediate files saved to: {intermediate_dir}")


def run_generation(
    script_path: str,
    output_path: str,
    keep_intermediate: bool = False,
    no_cache: bool = False,
    cache_refresh: bool = False,
    jobs: str = "1",
):
    """
    High-level function to run the entire generation process.
    """
    # Get the path to the default config file
    default_config_path = Path(__file__).parent / "templates" / "config.yaml"

    # Load script and config
    config = load_script_and_config(script_path, str(default_config_path))

    # Create and run the pipeline
    pipeline = GenerationPipeline(config, no_cache, cache_refresh, jobs)
    pipeline.run(output_path, keep_intermediate)
