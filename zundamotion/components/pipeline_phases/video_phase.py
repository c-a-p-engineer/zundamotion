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
from zundamotion.utils.ffmpeg_utils import set_hw_filter_mode  # Auto-tuneでのバックオフに使用
from zundamotion.utils.ffmpeg_utils import AudioParams, VideoParams, normalize_media
from zundamotion.utils.logger import logger, time_log


class VideoPhase:
    def __init__(
        self,
        config: Dict[str, Any],
        temp_dir: Path,
        cache_manager: CacheManager,
        jobs: str,
        hw_kind: Optional[str],
        video_params: VideoParams,
        audio_params: AudioParams,
    ):
        self.config = config
        self.temp_dir = temp_dir
        self.cache_manager = cache_manager
        self.jobs = jobs
        self.subtitle_gen = SubtitleGenerator(self.config, self.cache_manager)
        self.hw_kind = hw_kind
        self.video_params = video_params
        self.audio_params = audio_params

        self.video_extensions = self.config.get("system", {}).get(
            "video_extensions",
            [".mp4", ".mov", ".webm", ".avi", ".mkv"],
        )
        # クリップ並列実行ワーカー数を決定
        # 実効フィルタ経路がCPUの場合は、NVENC でもCPU向けヒューリスティクスを適用する
        self.clip_workers = self._determine_clip_workers(jobs, self.hw_kind)
        # Auto-tune (profile first N clips then adjust caps/clip_workers)
        vcfg = self.config.get("video", {}) if isinstance(self.config, dict) else {}
        try:
            self.profile_limit = int(vcfg.get("profile_first_clips", 4))
        except Exception:
            self.profile_limit = 4
        self.auto_tune_enabled = bool(vcfg.get("auto_tune", True))
        self._profile_samples: List[Dict[str, Any]] = []
        self._retuned = False

    @staticmethod
    def _determine_clip_workers(jobs: str, hw_kind: Optional[str]) -> int:
        """決定的な並列度を返す。"""
        try:
            import os
            from zundamotion.utils.ffmpeg_utils import get_hw_filter_mode

            # 実効フィルタがCPUかどうか（プロセス全体のバックオフ判定）
            filter_mode = get_hw_filter_mode()
            cpu_filters_effective = filter_mode == "cpu"

            if jobs is None:
                base = max(1, (os.cpu_count() or 2) // 2)
                if hw_kind == "nvenc" and not cpu_filters_effective:
                    return min(2, max(1, base))
                return base
            j = jobs.strip().lower()
            if j in ("0", "auto"):
                base = max(2, (os.cpu_count() or 2) // 2)
                if hw_kind == "nvenc" and not cpu_filters_effective:
                    return min(2, max(1, base))
                return base
            val = int(j)
            if val <= 0:
                base = max(2, (os.cpu_count() or 2) // 2)
                if hw_kind == "nvenc" and not cpu_filters_effective:
                    return min(2, max(1, base))
                return base
            # 上限はCPU数
            decided = max(1, min(val, os.cpu_count() or val))
            if hw_kind == "nvenc" and not cpu_filters_effective:
                return min(2, decided)
            return decided
        except Exception:
            return 1 if hw_kind == "nvenc" else 2

    @classmethod
    async def create(
        cls,
        config: Dict[str, Any],
        temp_dir: Path,
        cache_manager: CacheManager,
        jobs: str,
    ):
        hw_kind = await get_hw_encoder_kind_for_video_params()
        video_params = VideoParams(
            width=config.get("video", {}).get("width", 1920),
            height=config.get("video", {}).get("height", 1080),
            fps=config.get("video", {}).get("fps", 30),
            pix_fmt=config.get("video", {}).get("pix_fmt", "yuv420p"),
            profile=config.get("video", {}).get("profile", "high"),
            level=config.get("video", {}).get("level", "4.2"),
            preset=config.get("video", {}).get(
                "preset", "p5" if hw_kind == "nvenc" else "veryfast"
            ),
            cq=config.get("video", {}).get("cq", 23),
            crf=config.get("video", {}).get("crf", 23),
        )
        audio_params = AudioParams(
            sample_rate=config.get("video", {}).get("audio_sample_rate", 48000),
            channels=config.get("video", {}).get("audio_channels", 2),
            codec=config.get("video", {}).get("audio_codec", "libmp3lame"),
            bitrate_kbps=config.get("video", {}).get("audio_bitrate_kbps", 192),
        )
        # jobs/hw_kind から先に clip_workers を算出して VideoRenderer に伝搬
        pre_clip_workers = cls._determine_clip_workers(jobs, hw_kind)

        video_renderer = await VideoRenderer.create(
            config,
            temp_dir,
            cache_manager,
            jobs,
            hw_kind=hw_kind,
            video_params=video_params,
            audio_params=audio_params,
            clip_workers=pre_clip_workers,
        )
        instance = cls(
            config, temp_dir, cache_manager, jobs, hw_kind, video_params, audio_params
        )
        instance.video_renderer = video_renderer
        return instance

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
        logger.info(
            f"VideoPhase started. clip_workers={self.clip_workers}, hw_kind={self.hw_kind}"
        )

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

                # シーンベース映像（背景のみ）を事前生成（動画/静止画どちらでも）
                scene_base_path: Optional[Path] = None
                # 静的レイヤ（全行で不変な立ち絵・挿入画像）を検出（項目単位の共通部分を抽出）
                static_overlays: List[Dict[str, Any]] = []
                static_char_keys: set = set()
                static_insert_in_base = False
                scene_level_insert_video: Optional[Path] = None
                try:
                    talk_lines = [
                        l
                        for l in scene.get("lines", [])
                        if not ("wait" in l or l.get("type") == "wait")
                    ]
                    if talk_lines:
                        # 各行の可視キャラを正規化してキー化（name, expr, scale, anchor, pos）
                        def _norm_char_entries(line: Dict[str, Any]) -> Dict[tuple, Dict[str, Any]]:
                            entries: Dict[tuple, Dict[str, Any]] = {}
                            for ch in line.get("characters", []) or []:
                                if not ch.get("visible", False):
                                    continue
                                name = ch.get("name")
                                expr = ch.get("expression", "default")
                                # 量子化（微差を同一扱い）
                                try:
                                    scale = round(float(ch.get("scale", 1.0)), 2)
                                except Exception:
                                    scale = 1.0
                                anchor = str(ch.get("anchor", "bottom_center")).lower()
                                pos_raw = ch.get("position", {"x": "0", "y": "0"}) or {}
                                def _q(v):
                                    try:
                                        return f"{float(v):.2f}"
                                    except Exception:
                                        return str(v)
                                pos = {"x": _q(pos_raw.get("x", "0")), "y": _q(pos_raw.get("y", "0"))}
                                key = (
                                    name,
                                    expr,
                                    float(scale),
                                    str(anchor),
                                    str(pos.get("x", "0")),
                                    str(pos.get("y", "0")),
                                )
                                entries[key] = {
                                    "path": f"assets/characters/{name}/{expr}.png",
                                    "scale": scale,
                                    "anchor": anchor,
                                    "position": {"x": pos.get("x", "0"), "y": pos.get("y", "0")},
                                }
                            return entries

                        per_line_char_maps = [_norm_char_entries(tl) for tl in talk_lines]
                        if per_line_char_maps:
                            common_keys = set(per_line_char_maps[0].keys())
                            for m in per_line_char_maps[1:]:
                                common_keys &= set(m.keys())
                            for key in sorted(common_keys):
                                ov = per_line_char_maps[0][key]
                                p = Path(ov["path"])  # expr 固定のはず
                                if not p.exists():
                                    # default フォールバック
                                    name, _expr, _s, _a, _x, _y = key
                                    alt = Path(f"assets/characters/{name}/default.png")
                                    if not alt.exists():
                                        continue
                                    ov = {**ov, "path": str(alt)}
                                static_overlays.append(ov)
                                static_char_keys.add(key)

                        # 画像の挿入が全行共通か（画像のみ、動画は対象外）
                        first_insert = talk_lines[0].get("insert")
                        if first_insert:
                            same_insert_all = all(
                                (tl.get("insert") == first_insert) for tl in talk_lines
                            )
                            if same_insert_all:
                                insert_path = Path(first_insert.get("path", ""))
                                # 画像はベースへ取り込み、動画はシーン単位で事前正規化のみ行う
                                if insert_path.suffix.lower() in [
                                    ".png",
                                    ".jpg",
                                    ".jpeg",
                                    ".bmp",
                                    ".webp",
                                ] and insert_path.exists():
                                    static_overlays.append(
                                        {
                                            "path": str(insert_path),
                                            "scale": first_insert.get("scale", 1.0),
                                            "anchor": first_insert.get(
                                                "anchor", "middle_center"
                                            ),
                                            "position": first_insert.get(
                                                "position", {"x": "0", "y": "0"}
                                            ),
                                        }
                                    )
                                    static_insert_in_base = True
                                elif insert_path.suffix.lower() in [
                                    ".mp4",
                                    ".mov",
                                    ".webm",
                                    ".avi",
                                    ".mkv",
                                ] and insert_path.exists():
                                    try:
                                        # シーン内で共通の挿入動画を一度だけ正規化
                                        normalized_insert = await normalize_media(
                                            input_path=insert_path,
                                            video_params=self.video_params,
                                            audio_params=self.audio_params,
                                            cache_manager=self.cache_manager,
                                        )
                                        scene_level_insert_video = normalized_insert
                                        logger.info(
                                            f"Scene {scene_id}: pre-normalized common insert video -> {normalized_insert.name}"
                                        )
                                    except Exception as e:
                                        logger.warning(
                                            f"Scene {scene_id}: failed to pre-normalize common insert video {insert_path.name}: {e}"
                                        )
                except Exception as e:
                    logger.debug(
                        f"Static overlay detection failed on scene {scene_id}: {e}"
                    )
                # ベース映像生成の可否を判断
                normalized_bg_path: Optional[Path] = None
                total_lines_in_scene = len(scene.get("lines", []))
                min_lines_for_base = int(
                    self.config.get("video", {}).get("scene_base_min_lines", 6)
                )
                should_generate_base = False
                if static_overlays:
                    should_generate_base = True
                elif is_bg_video and total_lines_in_scene >= min_lines_for_base:
                    # 静的オーバーレイは無いが、行数が多い場合はベース生成の方が有利
                    should_generate_base = True

                if should_generate_base:
                    try:
                        bg_config_for_base = {
                            "type": "video" if is_bg_video else "image",
                            "path": str(bg_image),
                        }
                        scene_base_filename = f"scene_base_{scene_id}"
                        if static_overlays:
                            scene_base_path = await self.video_renderer.render_scene_base_composited(
                                bg_config_for_base,
                                scene_duration,
                                scene_base_filename,
                                static_overlays,
                            )
                            # ベースに取り込んだ静的オーバーレイの種類は per-line で個別に除外処理
                        else:
                            scene_base_path = await self.video_renderer.render_scene_base(
                                bg_config_for_base, scene_duration, scene_base_filename
                            )
                        if scene_base_path:
                            logger.info(
                                f"Scene {scene_id}: generated base with {len(static_overlays)} static overlay(s) -> {scene_base_path.name}"
                            )
                    except Exception as e:
                        logger.warning(
                            f"Failed to generate scene base for scene {scene_id}: {e}"
                        )
                        # フォールバック: 動画背景なら従来のループ生成を試みる
                        if is_bg_video:
                            try:
                                normalized_bg_path = await normalize_media(
                                    input_path=Path(bg_image),
                                    video_params=self.video_params,
                                    audio_params=self.audio_params,
                                    cache_manager=self.cache_manager,
                                )
                                scene_base_path = await self.video_renderer.render_looped_background_video(
                                    str(normalized_bg_path),
                                    scene_duration,
                                    f"scene_bg_{scene_id}",
                                )
                                if scene_base_path:
                                    logger.debug(
                                        f"Fallback generated looped background -> {scene_base_path.name}"
                                    )
                            except Exception as e2:
                                logger.warning(
                                    f"Fallback looped BG generation also failed for scene {scene_id}: {e2}"
                                )
                else:
                    # ベース生成をスキップ。動画背景はシーン単位で一度だけ正規化して各行へ伝搬
                    if is_bg_video:
                        try:
                            normalized_bg_path = await normalize_media(
                                input_path=Path(bg_image),
                                video_params=self.video_params,
                                audio_params=self.audio_params,
                                cache_manager=self.cache_manager,
                            )
                            logger.info(
                                "Scene %s: skipping base generation (static_overlays=%d, lines=%d < threshold=%d). Using pre-normalized background.",
                                scene_id,
                                len(static_overlays),
                                total_lines_in_scene,
                                min_lines_for_base,
                            )
                        except Exception as e:
                            logger.warning(
                                "Scene %s: background pre-normalization failed (%s). Proceeding as-is without base.",
                                scene_id,
                                e,
                            )

                # 先に各行の開始時刻を決定
                lines = list(enumerate(scene.get("lines", []), start=1))
                start_time_by_idx: Dict[int, float] = {}
                t_acc = 0.0
                for idx, _line in lines:
                    line_id2 = f"{scene_id}_{idx}"
                    d = line_data_map[line_id2]["duration"]
                    start_time_by_idx[idx] = t_acc
                    t_acc += d

                # 並列レンダリング用のタスクを構築
                import asyncio

                # If auto-tune has retuned clip_workers, new sem will reflect it
                sem = asyncio.Semaphore(self.clip_workers)
                results: List[Optional[Path]] = [None] * len(lines)

                async def process_one(idx: int, line: Dict[str, Any]):
                    async with sem:
                        import time as _time
                        line_id = f"{scene_id}_{idx}"
                        line_data = line_data_map[line_id]
                        duration = line_data["duration"]
                        line_config = line_data["line_config"]

                        # シーンベース映像が生成できたらそれを使い、再スケール/正規化をスキップ
                        if scene_base_path is not None and scene_base_path.exists():
                            background_config = {
                                "type": "video",
                                "path": str(scene_base_path),
                                "start_time": start_time_by_idx[idx],
                                "normalized": True,  # 正規化済み（ベース作成時）
                                "pre_scaled": True,  # width/height/fps 済み
                            }
                        else:
                            # フォールバック（従来動作）: ベースなしで個別処理
                            if is_bg_video:
                                # シーン単位で正規化済みなら二重スケールを回避
                                if normalized_bg_path is not None and Path(
                                    normalized_bg_path
                                ).exists():
                                    background_config = {
                                        "type": "video",
                                        "path": str(normalized_bg_path),
                                        "start_time": start_time_by_idx[idx],
                                        "normalized": True,
                                        "pre_scaled": True,
                                    }
                                else:
                                    background_config = {
                                        "type": "video",
                                        "path": str(bg_image),
                                        "start_time": start_time_by_idx[idx],
                                    }
                            else:
                                background_config = {
                                    "type": "image",
                                    "path": str(bg_image),
                                    "start_time": start_time_by_idx[idx],
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
                                "start_time": start_time_by_idx[idx],
                                "video_config": self.config.get("video", {}),
                                "line_config": line_config,
                                "hw_kind": self.hw_kind,
                                "video_params": self.video_params.__dict__,
                                "audio_params": self.audio_params.__dict__,
                            }

                            async def wait_creator_func(output_path: Path) -> Path:
                                clip_path = await self.video_renderer.render_wait_clip(
                                    duration,
                                    background_config,
                                    output_path.stem,
                                    line_config,
                                )
                                if clip_path is None:
                                    raise PipelineError(
                                        f"Wait clip rendering failed for line: {line_id}"
                                    )
                                return clip_path

                            clip_path = await self.cache_manager.get_or_create(
                                key_data=wait_cache_data,
                                file_name=line_id,
                                extension="mp4",
                                creator_func=wait_creator_func,
                            )
                            results[idx - 1] = clip_path
                            return

                        # Talk step
                        text = line_data["text"]
                        audio_path = line_data["audio_path"]
                        logger.debug(
                            f"Rendering clip for line '{text[:30]}...' (Scene '{scene_id}', Line {idx})"
                        )

                        audio_cache_key_data = {
                            "text": text,
                            "line_config": line_config,
                            "voice_config": self.config.get("voice", {}),
                        }
                        # 静的レイヤをベースに取り込んでいる場合、行側から該当項目のみ除去
                        original_characters = line.get("characters", []) or []
                        if static_char_keys:
                            eff_chars: List[Dict[str, Any]] = []
                            for ch in original_characters:
                                if not ch.get("visible", False):
                                    eff_chars.append(ch)
                                    continue
                                key = (
                                    ch.get("name"),
                                    ch.get("expression", "default"),
                                    float(ch.get("scale", 1.0)),
                                    str(ch.get("anchor", "bottom_center")),
                                    str((ch.get("position", {}) or {}).get("x", "0")),
                                    str((ch.get("position", {}) or {}).get("y", "0")),
                                )
                                if key in static_char_keys:
                                    continue
                                eff_chars.append(ch)
                            effective_characters = eff_chars
                        else:
                            effective_characters = original_characters

                        # ベースに取り込まれていない共通挿入“動画”があれば、事前正規化済みのパスを各行へ伝搬
                        if static_insert_in_base:
                            effective_insert = None
                        else:
                            raw_insert = line_config.get("insert")
                            if (
                                scene_level_insert_video is not None
                                and raw_insert
                                and Path(raw_insert.get("path", "")).exists()
                            ):
                                effective_insert = {
                                    **raw_insert,
                                    "path": str(scene_level_insert_video),
                                    "normalized": True,
                                    "pre_scaled": True,
                                }
                            else:
                                effective_insert = raw_insert

                        # Face animation config versioning for cache stability
                        face_anim = line_data.get("face_anim")
                        anim_meta = (face_anim or {}).get("meta") or {}
                        video_cache_data = {
                            "type": "talk",
                            "audio_cache_key": self.cache_manager._generate_hash(
                                audio_cache_key_data
                            ),
                            "duration": duration,
                            "subtitle_text": text,
                            "subtitle_style_override": line_config.get("subtitle"),
                            "bg_image_path": bg_image,
                            "is_bg_video": is_bg_video,
                            "start_time": start_time_by_idx[idx],
                            "video_config": self.config.get("video", {}),
                            "subtitle_config": self.config.get("subtitle", {}),
                            "bgm_config": self.config.get("bgm", {}),
                            "insert_config": effective_insert,
                            "static_chars_in_base": bool(static_char_keys),
                            "static_insert_in_base": static_insert_in_base,
                            "hw_kind": self.hw_kind,
                            "video_params": self.video_params.__dict__,
                            "audio_params": self.audio_params.__dict__,
                            # Minimal cache key for face animation
                            "lip_eye_version": "v1",
                            "face_anim_enabled": bool(face_anim),
                            "mouth_fps": anim_meta.get("mouth_fps"),
                            "thr_half": anim_meta.get("thr_half"),
                            "thr_open": anim_meta.get("thr_open"),
                            "blink_min_interval": anim_meta.get("blink_min_interval"),
                            "blink_max_interval": anim_meta.get("blink_max_interval"),
                            "blink_close_frames": anim_meta.get("blink_close_frames"),
                        }

                        async def clip_creator_func(output_path: Path) -> Path:
                            clip_path = await self.video_renderer.render_clip(
                                audio_path=audio_path,
                                duration=duration,
                                background_config=background_config,
                                characters_config=effective_characters,
                                output_filename=output_path.stem,
                                subtitle_text=text,
                                subtitle_line_config=line_config,
                                insert_config=effective_insert,
                                face_anim=face_anim,
                            )
                            if clip_path is None:
                                raise PipelineError(
                                    f"Clip rendering failed for line: {line_id}"
                                )
                            return clip_path

                        _t0 = _time.time()
                        clip_path = await self.cache_manager.get_or_create(
                            key_data=video_cache_data,
                            file_name=line_id,
                            extension="mp4",
                            creator_func=clip_creator_func,
                        )
                        # Collect lightweight samples for auto-tune
                        try:
                            if (
                                self.auto_tune_enabled
                                and len(self._profile_samples) < self.profile_limit
                            ):
                                # Heuristic: subtitle or visible characters or image insert implies CPU overlay
                                has_subtitle = bool((line_data.get("text") or "").strip())
                                any_chars = any(
                                    (c or {}).get("visible", False)
                                    for c in (line.get("characters", []) or [])
                                )
                                ins = line_config.get("insert") or {}
                                ins_path = str(ins.get("path", ""))
                                ins_is_image = ins_path.lower().endswith(
                                    (".png", ".jpg", ".jpeg", ".bmp", ".webp")
                                )
                                cpu_overlay = has_subtitle or any_chars or ins_is_image
                                elapsed = _time.time() - _t0
                                self._profile_samples.append(
                                    {
                                        "cpu_overlay": cpu_overlay,
                                        "elapsed": elapsed,
                                    }
                                )
                        except Exception:
                            pass
                        results[idx - 1] = clip_path

                tasks = [process_one(idx, line) for idx, line in lines]
                # 並列実行
                await asyncio.gather(*tasks)

                # After first scene (or once enough samples), auto-tune for subsequent scenes
                if (
                    self.auto_tune_enabled
                    and not self._retuned
                    and len(self._profile_samples) >= self.profile_limit
                ):
                    try:
                        cpu_ratio = (
                            sum(1 for s in self._profile_samples if s.get("cpu_overlay"))
                            / float(len(self._profile_samples) or 1)
                        )
                        import os as _os
                        # Be conservative on CPU overlays
                        if cpu_ratio >= 0.5:
                            # Tighten filter caps and lower concurrency
                            _os.environ.setdefault("FFMPEG_FILTER_THREADS_CAP", "2")
                            _os.environ.setdefault(
                                "FFMPEG_FILTER_COMPLEX_THREADS_CAP", "2"
                            )
                            # CPU overlay 優勢時はGPUフィルタを全体でオフにしてスレッド最適化を適用
                            try:
                                set_hw_filter_mode("cpu")
                                logger.info(
                                    "[AutoTune] Set HW filter mode to 'cpu' due to CPU overlay dominance."
                                )
                            except Exception:
                                pass
                            # Prefer at most 2 workers when NVENC + CPU overlays dominate
                            prev_workers = self.clip_workers
                            self.clip_workers = max(1, min(prev_workers, 2))
                            logger.info(
                                "[AutoTune] cpu_ratio=%.2f -> caps(ft,fct)=2, clip_workers %s -> %s",
                                cpu_ratio,
                                prev_workers,
                                self.clip_workers,
                            )
                        else:
                            logger.info(
                                "[AutoTune] cpu_ratio=%.2f -> keeping current concurrency",
                                cpu_ratio,
                            )
                        # Disable profiling overhead after retune
                        _os.environ["FFMPEG_PROFILE_MODE"] = "0"
                        self._retuned = True
                    except Exception:
                        pass

                # 順序維持で集約
                scene_line_clips: List[Path] = [p for p in results if p is not None]

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

                if scene_base_path and scene_base_path.exists():
                    try:
                        scene_base_path.unlink()
                        logger.debug(
                            f"Cleaned up temporary scene base video -> {scene_base_path.name}"
                        )
                    except Exception:
                        pass
                pbar_scenes.update(1)

        end_time = time.time()  # End timing
        duration = end_time - start_time
        logger.info(f"VideoPhase completed in {duration:.2f} seconds.")
        return all_clips
