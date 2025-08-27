import hashlib
import json
import time  # Import time module
from pathlib import Path
from typing import Any, Dict, List, Optional

from tqdm import tqdm

from zundamotion.cache import CacheManager
from zundamotion.components.subtitle import SubtitleGenerator
from zundamotion.components.video import VideoRenderer
from zundamotion.exceptions import PipelineError
from zundamotion.timeline import Timeline
from zundamotion.utils.ffmpeg_utils import get_hw_encoder_kind_for_video_params  # 追加
from zundamotion.utils.ffmpeg_utils import AudioParams, VideoParams, normalize_media
from zundamotion.utils.logger import logger, time_log


class VideoPhase:
    def __init__(
        self,
        config: Dict[str, Any],
        temp_dir: Path,
        cache_manager: CacheManager,
        jobs: str,
    ):
        self.config = config
        self.temp_dir = temp_dir
        self.cache_manager = cache_manager
        self.jobs = jobs
        self.subtitle_gen = SubtitleGenerator(self.config, self.cache_manager)

        # 要件に基づいた VideoParams と AudioParams を作成
        self.hw_kind = get_hw_encoder_kind_for_video_params()
        self.video_params = VideoParams(
            width=self.config.get("video", {}).get("width", 1920),
            height=self.config.get("video", {}).get("height", 1080),
            fps=self.config.get("video", {}).get("fps", 30),
            pix_fmt=self.config.get("video", {}).get("pix_fmt", "yuv420p"),
            profile=self.config.get("video", {}).get("profile", "high"),
            level=self.config.get("video", {}).get("level", "4.2"),
            preset=self.config.get("video", {}).get(
                "preset", "p4" if self.hw_kind == "nvenc" else "veryfast"
            ),
            cq=self.config.get("video", {}).get("cq", 23),
            crf=self.config.get("video", {}).get("crf", 23),
        )
        self.audio_params = AudioParams(
            sample_rate=self.config.get("video", {}).get("audio_sample_rate", 48000),
            channels=self.config.get("video", {}).get("audio_channels", 2),
            codec=self.config.get("video", {}).get("audio_codec", "aac"),
            bitrate_kbps=self.config.get("video", {}).get("audio_bitrate_kbps", 192),
        )

        self.video_renderer = VideoRenderer(
            self.config,
            self.temp_dir,
            self.cache_manager,
            self.jobs,
            hw_kind=self.hw_kind,  # 追加
            video_params=self.video_params,  # 追加
            audio_params=self.audio_params,  # 追加
        )
        self.video_extensions = self.config.get("system", {}).get(
            "video_extensions",
            [".mp4", ".mov", ".webm", ".avi", ".mkv"],
        )

    def _generate_scene_hash(self, scene: Dict[str, Any]) -> Dict[str, Any]:
        """Generates a dictionary for scene hash based on its content and relevant config."""
        return {
            "id": scene.get("id"),
            "lines": scene.get("lines", []),
            "bg": scene.get("bg"),
            "bgm": scene.get("bgm"),
            "voice_config": self.config.get("voice", {}),
            "video_config": self.config.get("video", {}),
            "subtitle_config": self.config.get("subtitle", {}),
            "bgm_config": self.config.get("bgm", {}),
            "background_default": self.config.get("background", {}).get("default"),
            "transition_config": scene.get(
                "transition"
            ),  # Add transition config to hash
            "hw_kind": self.hw_kind,  # 追加
            "video_params": self.video_params.__dict__,  # 追加
            "audio_params": self.audio_params.__dict__,  # 追加
        }

    @time_log(logger)
    async def run(
        self,
        scenes: List[Dict[str, Any]],
        line_data_map: Dict[str, Dict[str, Any]],
        timeline: Timeline,
    ) -> List[Path]:
        """Phase 2: Render video clips for each scene."""
        start_time = time.time()  # Start timing
        logger.info("VideoPhase started.")

        all_clips: List[Path] = []
        bg_default = self.config.get("background", {}).get("default")
        total_scenes = len(scenes)

        with tqdm(
            total=total_scenes, desc="Scene Rendering", unit="scene"
        ) as pbar_scenes:
            for scene_idx, scene in enumerate(scenes):
                scene_id = scene["id"]
                scene_hash_data = self._generate_scene_hash(scene)

                cached_scene_video_path = self.cache_manager.get_cached_path(
                    key_data=scene_hash_data,
                    file_name=f"scene_{scene_id}",
                    extension="mp4",
                )
                if cached_scene_video_path:
                    all_clips.append(cached_scene_video_path)
                    pbar_scenes.update(1)
                    continue

                pbar_scenes.set_description(
                    f"Scene Rendering (Scene {scene_idx + 1}/{total_scenes}: '{scene_id}')"
                )

                bg_image = scene.get("bg", bg_default)
                is_bg_video = Path(bg_image).suffix.lower() in self.video_extensions

                scene_duration = sum(
                    line_data_map[f"{scene_id}_{idx + 1}"]["duration"]
                    for idx, line in enumerate(scene.get("lines", []))
                )

                scene_bg_video_path: Optional[Path] = None
                if is_bg_video:
                    # 正規化用のパラメータを取得 (self.video_params と self.audio_params を使用)
                    # 背景動画を正規化
                    normalized_bg_path = await normalize_media(
                        input_path=Path(bg_image),
                        video_params=self.video_params,  # 変更
                        audio_params=self.audio_params,  # 変更
                        cache_manager=self.cache_manager,
                    )

                    scene_bg_video_filename = f"scene_bg_{scene_id}"
                    scene_bg_video_path: Optional[Path] = (
                        await self.video_renderer.render_looped_background_video(
                            str(normalized_bg_path),  # Pathオブジェクトを文字列に変換
                            scene_duration,
                            scene_bg_video_filename,
                        )
                    )
                    if scene_bg_video_path:
                        logger.debug(
                            f"Generated looped scene background video -> {scene_bg_video_path.name}"
                        )
                    else:
                        logger.warning(
                            f"Failed to generate looped background video for scene {scene_id}"
                        )

                scene_line_clips: List[Path] = []
                current_scene_time = 0.0
                for idx, line in enumerate(scene.get("lines", []), start=1):
                    line_id = f"{scene_id}_{idx}"
                    line_data = line_data_map[line_id]
                    duration = line_data["duration"]
                    line_config = line_data["line_config"]

                    background_config = {
                        "type": "video" if is_bg_video else "image",
                        "path": (
                            str(scene_bg_video_path) if is_bg_video else bg_image
                        ),  # Pathオブジェクトを文字列に変換
                        "start_time": current_scene_time,
                    }

                    if line_data["type"] == "wait":
                        logger.debug(
                            f"Rendering wait clip for {duration}s (Scene '{scene_id}', Line {idx})"
                        )
                        wait_cache_data = {
                            "type": "wait",
                            "duration": duration,
                            "bg_image_path": bg_image,
                            "is_bg_video": is_bg_video,
                            "start_time": current_scene_time,
                            "video_config": self.config.get("video", {}),
                            "line_config": line_config,
                            "hw_kind": self.hw_kind,  # 追加
                            "video_params": self.video_params.__dict__,  # 追加
                            "audio_params": self.audio_params.__dict__,  # 追加
                        }

                        async def wait_creator_func(output_path: Path) -> Path:
                            return await self.video_renderer.render_wait_clip(
                                duration,
                                background_config,
                                output_path.stem,
                                line_config,
                            )

                        clip_path = await self.cache_manager.get_or_create(
                            key_data=wait_cache_data,
                            file_name=line_id,
                            extension="mp4",
                            creator_func=wait_creator_func,
                        )
                        if clip_path:
                            scene_line_clips.append(clip_path)
                    else:  # Talk Step
                        text = line_data["text"]
                        audio_path = line_data["audio_path"]
                        logger.debug(
                            f"Rendering clip for line '{text[:30]}...' (Scene '{scene_id}', Line {idx})"
                        )

                        # 字幕PNGを生成し、FFmpegの入力とフィルタースニペットを取得
                        # 現在の入力ストリーム数を考慮してインデックスを決定
                        # VideoRenderer.render_clip内で動的に入力インデックスを管理するため、ここでは仮のインデックスを渡す
                        # 実際にはVideoRendererが管理する
                        (
                            extra_subtitle_inputs,
                            subtitle_filter_snippet,
                        ) = await self.subtitle_gen.build_subtitle_overlay(
                            text,
                            duration,
                            line_config,
                            "with_char",
                            0,  # 0は仮の値、VideoRendererが調整
                        )

                        audio_cache_key_data = {
                            "text": text,
                            "line_config": line_config,
                            "voice_config": self.config.get("voice", {}),
                        }
                        video_cache_data = {
                            "type": "talk",
                            "audio_cache_key": self.cache_manager._generate_hash(
                                audio_cache_key_data
                            ),
                            "duration": duration,
                            "subtitle_png_path": extra_subtitle_inputs[
                                "-i"
                            ],  # キャッシュキーにPNGパスを含める
                            "subtitle_filter_snippet": subtitle_filter_snippet,  # キャッシュキーにフィルタースニペットを含める
                            "bg_image_path": bg_image,
                            "is_bg_video": is_bg_video,
                            "start_time": current_scene_time,
                            "video_config": self.config.get("video", {}),
                            "subtitle_config": self.config.get("subtitle", {}),
                            "bgm_config": self.config.get("bgm", {}),
                            "insert_config": line_config.get("insert"),
                            "hw_kind": self.hw_kind,  # 追加
                            "video_params": self.video_params.__dict__,  # 追加
                            "audio_params": self.audio_params.__dict__,  # 追加
                        }

                        async def clip_creator_func(
                            output_path: Path,
                        ) -> Path:  # 戻り値の型を Path に変更
                            clip_path = await self.video_renderer.render_clip(
                                audio_path=audio_path,  # Pathオブジェクトのまま渡す
                                duration=duration,
                                background_config=background_config,
                                characters_config=line.get("characters", []),
                                output_filename=output_path.stem,
                                extra_subtitle_inputs=extra_subtitle_inputs,
                                insert_config=line_config.get("insert"),
                            )
                            if clip_path is None:
                                raise PipelineError(
                                    f"Clip rendering failed for line: {line_id}"
                                )
                            return clip_path

                        clip_path = await self.cache_manager.get_or_create(
                            key_data=video_cache_data,
                            file_name=line_id,
                            extension="mp4",
                            creator_func=clip_creator_func,
                        )
                        if clip_path:
                            scene_line_clips.append(clip_path)
                        else:
                            raise PipelineError(
                                f"Clip rendering failed for line: {line_id}"
                            )

                    current_scene_time += duration

                if scene_line_clips:
                    scene_output_path = self.temp_dir / f"scene_output_{scene_id}.mp4"
                    await self.video_renderer.concat_clips(
                        scene_line_clips, str(scene_output_path)
                    )
                    logger.info(f"Concatenated scene clips -> {scene_output_path.name}")
                    all_clips.append(scene_output_path)
                    self.cache_manager.cache_file(
                        source_path=scene_output_path,
                        key_data=scene_hash_data,
                        file_name=f"scene_{scene_id}",
                        extension="mp4",
                    )

                if scene_bg_video_path and scene_bg_video_path.exists():
                    scene_bg_video_path.unlink()
                    logger.debug(
                        f"Cleaned up temporary scene background video -> {scene_bg_video_path.name}"
                    )
                pbar_scenes.update(1)

        end_time = time.time()  # End timing
        duration = end_time - start_time
        logger.info(f"VideoPhase completed in {duration:.2f} seconds.")
        return all_clips
