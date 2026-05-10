"""動画オーバーレイ処理を担当するMixinモジュール。

VideoRendererに継承させることで、前景動画や字幕PNGを
ベース映像に重ねるユーティリティを提供する。
"""
from pathlib import Path
from dataclasses import replace
from typing import Any, Dict, List, Optional

from importlib import import_module

from ...utils.ffmpeg_probe import get_media_duration
from ...utils.ffmpeg_ops import concat_videos_copy
from ...utils.filter_presets import get_video_filter_chain
from ...utils.logger import logger
from .overlay_effects import resolve_overlay_effects
from .threading import build_ffmpeg_thread_flags


async def _run_ffmpeg(cmd: List[str]) -> None:
    """videoモジュール経由でffmpegを実行するラッパー。"""
    video_module = import_module("zundamotion.components.video")
    await video_module._run_ffmpeg_async(cmd)


class OverlayMixin:
    """FFmpegを用いたオーバーレイ合成機能のMixinクラス。"""

    def _max_cuda_subtitle_overlays(self) -> int:
        video_cfg = getattr(self, "video_config", {}) or {}
        try:
            value = int(video_cfg.get("max_cuda_subtitle_overlays", 8))
        except Exception:
            value = 8
        return max(0, value)

    def _should_use_cuda_for_subtitles(self, subtitles: List[Dict[str, Any]]) -> bool:
        if self.gpu_overlay_backend != "cuda":
            return False

        limit = self._max_cuda_subtitle_overlays()
        count = len(subtitles or [])
        if limit and count > limit:
            logger.info(
                "[SubtitleOverlay] Falling back to CPU filters because subtitle count=%s exceeds CUDA limit=%s",
                count,
                limit,
            )
            return False
        return True

    def _is_image(self, path: Path) -> bool:
        ext = path.suffix.lower()
        return ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

    def _subtitle_render_mode(self, subtitles: List[Dict[str, Any]]) -> str:
        if not subtitles:
            return "none"
        resolver = getattr(self.subtitle_gen, "resolve_render_mode_for_subtitles", None)
        if callable(resolver):
            mode = resolver(subtitles)
        else:
            mode = self.subtitle_gen.subtitle_render_mode()
        return "png" if mode == "png" else "ass"

    @staticmethod
    def _escape_filter_path(path: Path) -> str:
        return str(path.resolve()).replace("\\", "\\\\").replace(":", "\\:")

    def _build_ass_filter(self, ass_path: Path) -> str:
        font_dir = ""
        try:
            font_path = self.subtitle_gen.subtitle_config.get("font_path")
            if font_path:
                font_dir = str(Path(str(font_path)).resolve().parent)
        except Exception:
            font_dir = ""
        ass_arg = self._escape_filter_path(ass_path)
        if font_dir:
            return f"ass={ass_arg}:fontsdir={self._escape_filter_path(Path(font_dir))}"
        return f"ass={ass_arg}"

    def _build_ass_subtitle_file(
        self,
        output_stem: str,
        subtitles: List[Dict[str, Any]],
    ) -> Path:
        ass_path = self.temp_dir / f"{output_stem}.ass"
        return self.subtitle_gen.build_ass_subtitle_file(subtitles, ass_path)

    def _single_job_thread_flags(self) -> List[str]:
        """単発の最終合成ジョブでは clip_workers に依存しない。"""
        return build_ffmpeg_thread_flags(
            getattr(self, "jobs", "0"),
            1,
            getattr(self, "hw_kind", None),
        )

    def _subtitle_png_chunk_size(self) -> int:
        subtitle_cfg = self.subtitle_gen.subtitle_config or {}
        try:
            value = int(subtitle_cfg.get("png_chunk_size", 12))
        except Exception:
            value = 12
        return max(1, value)

    def _subtitle_burn_video_opts(self, subtitle_mode: str) -> List[str]:
        params = self.video_params
        if self.hw_kind is None and subtitle_mode == "ass":
            burn_preset = (
                (self.subtitle_gen.subtitle_config or {}).get("ass_burn_preset")
                or "ultrafast"
            )
            try:
                crf_delta = int(
                    (self.subtitle_gen.subtitle_config or {}).get("ass_burn_crf_delta", 0)
                    or 0
                )
            except Exception:
                crf_delta = 0
            burn_params = replace(
                params,
                preset=str(burn_preset),
                crf=None if params.crf is None else max(0, int(params.crf) + crf_delta),
            )
            return burn_params.to_ffmpeg_opts(self.hw_kind)
        return params.to_ffmpeg_opts(self.hw_kind)

    @staticmethod
    def _merge_subtitle_ranges(
        subtitles: List[Dict[str, Any]],
        *,
        base_duration: Optional[float],
        gap_threshold: float = 0.20,
    ) -> List[Dict[str, Any]]:
        ranges: List[Dict[str, Any]] = []
        for sub in subtitles:
            try:
                start = max(0.0, float(sub.get("start", 0.0)))
                duration = max(0.0, float(sub.get("duration", 0.0)))
            except Exception:
                continue
            end = start + duration
            if base_duration is not None:
                end = min(float(base_duration), end)
            if end <= start:
                continue
            if ranges and start <= ranges[-1]["end"] + gap_threshold:
                ranges[-1]["end"] = max(ranges[-1]["end"], end)
                ranges[-1]["subtitles"].append(sub)
            else:
                ranges.append({"start": start, "end": end, "subtitles": [sub]})
        return ranges

    @classmethod
    def _split_subtitle_ranges_for_png(
        cls,
        subtitles: List[Dict[str, Any]],
        *,
        base_duration: Optional[float],
        gap_threshold: float = 0.20,
        max_subtitles: int = 12,
    ) -> List[Dict[str, Any]]:
        ranges = cls._merge_subtitle_ranges(
            subtitles,
            base_duration=base_duration,
            gap_threshold=gap_threshold,
        )
        if max_subtitles <= 0:
            max_subtitles = 12

        chunks: List[Dict[str, Any]] = []
        for item in ranges:
            current_subs: List[Dict[str, Any]] = []
            current_start: Optional[float] = None
            current_end = 0.0
            for sub in item["subtitles"]:
                try:
                    start = max(0.0, float(sub.get("start", 0.0)))
                    duration = max(0.0, float(sub.get("duration", 0.0)))
                except Exception:
                    continue
                end = start + duration
                if base_duration is not None:
                    end = min(float(base_duration), end)
                if end <= start:
                    continue

                can_split = (
                    current_subs
                    and len(current_subs) >= max_subtitles
                    and start >= current_end - 0.001
                )
                if can_split:
                    chunks.append(
                        {
                            "start": float(current_start or 0.0),
                            "end": current_end,
                            "subtitles": current_subs,
                        }
                    )
                    current_subs = []
                    current_start = None
                    current_end = 0.0

                if not current_subs:
                    current_start = start
                    current_end = end
                else:
                    current_end = max(current_end, end)
                current_subs.append(sub)

            if current_subs:
                chunks.append(
                    {
                        "start": float(current_start or 0.0),
                        "end": current_end,
                        "subtitles": current_subs,
                    }
                )
        return chunks

    async def _copy_video_segment(
        self,
        base_video: Path,
        output_path: Path,
        start: float,
        duration: float,
    ) -> Optional[Path]:
        if duration <= 0.02:
            return None
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-nostdin",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(base_video),
            "-t",
            f"{duration:.3f}",
            "-map",
            "0",
            "-c",
            "copy",
            "-avoid_negative_ts",
            "make_zero",
            str(output_path),
        ]
        await _run_ffmpeg(cmd)
        return output_path

    def _build_effect_filters(self, effects: Optional[List[Any]]) -> List[str]:
        """fg_overlays[*].effects を FFmpeg フィルタ列に変換する。"""

        return resolve_overlay_effects(effects)

    def _build_overlay_filter_parts(
        self, in_stream: str, idx: int, ov: Dict[str, Any]
    ) -> tuple[list[str], str]:
        """Build filter_complex snippets for a single overlay entry.

        The chain preserves the original alpha by splitting color/alpha planes,
        applying effects only to the color stream, scaling alpha separately for
        opacity, and merging them back with `alphamerge`.
        """

        filter_parts: list[str] = []
        steps: list[str] = []

        mode = ov.get("mode", "overlay")
        if mode == "alpha":
            mode = "overlay"

        fps = ov.get("fps")
        if fps:
            steps.append(f"fps={int(fps)}")

        scale_cfg = ov.get("scale", {})
        if isinstance(scale_cfg, (int, float)):
            scale_factor = float(scale_cfg)
            if scale_factor > 0:
                steps.append(
                    f"scale=iw*{scale_factor}:ih*{scale_factor}:flags={self.scale_flags}"
                )
        elif isinstance(scale_cfg, dict):
            w = scale_cfg.get("w")
            h = scale_cfg.get("h")
            keep = scale_cfg.get("keep_aspect")
            if w and h:
                if keep:
                    steps.append(
                        f"scale={w}:{h}:flags={self.scale_flags}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x00000000"
                    )
                else:
                    steps.append(f"scale={w}:{h}:flags={self.scale_flags}")

        if mode == "chroma":
            chroma = ov.get("chroma", {})
            key_color = chroma.get("key_color", "#000000").replace("#", "0x")
            similarity = chroma.get("similarity", 0.1)
            blend = chroma.get("blend", 0.0)
            steps.append(f"colorkey={key_color}:{similarity}:{blend}")

        fade_in = ov.get("fade_in")
        if isinstance(fade_in, dict):
            try:
                st = float(fade_in.get("start", 0.0))
                dur = float(fade_in.get("duration", 0.0))
            except Exception:
                st = 0.0
                dur = 0.0
            if dur > 0:
                steps.append(f"fade=t=in:st={st:.3f}:d={dur:.3f}:alpha=1")

        fade_out = ov.get("fade_out")
        if isinstance(fade_out, dict):
            try:
                st = float(fade_out.get("start", 0.0))
                dur = float(fade_out.get("duration", 0.0))
            except Exception:
                st = 0.0
                dur = 0.0
            if dur > 0:
                steps.append(f"fade=t=out:st={st:.3f}:d={dur:.3f}:alpha=1")

        effects = self._build_effect_filters(ov.get("effects"))
        video_filter = ov.get("filter")
        opacity = ov.get("opacity")
        force_opaque = bool(ov.get("opaque", False))

        color_in = f"[ov{idx}_c_in]"
        alpha_in = f"[ov{idx}_a_in]"
        color_out = f"[ov{idx}_c]"
        alpha_out = f"[ov{idx}_a]"
        processed = f"[ov{idx}]"

        # Base decode and optional fps/scale/chroma transforms
        steps.insert(0, "format=rgba")
        if force_opaque:
            steps.insert(1, "colorchannelmixer=aa=1")
        filter_parts.append(f"{in_stream}{','.join(steps)},split{color_in}{alpha_in}")

        color_steps: list[str] = []
        if effects:
            color_steps.extend(effects)
        if video_filter:
            color_steps.extend(get_video_filter_chain(str(video_filter)))
        filter_parts.append(f"{color_in}{','.join(color_steps or ['null'])}{color_out}")

        alpha_steps = ["format=ya8"]
        if opacity is not None:
            alpha_steps.append(f"lut=a='val*{float(opacity):.6f}'")
        filter_parts.append(f"{alpha_in}{','.join(alpha_steps)}{alpha_out}")

        filter_parts.append(f"{color_out}{alpha_out}alphamerge{processed}")

        return filter_parts, processed if mode != "blend" else processed

    async def apply_foreground_overlays(
        self, base_video: Path, overlays: List[Dict[str, Any]]
    ) -> Path:
        """前景動画をベース映像に重ね合わせる。

        Parameters
        ----------
        base_video: Path
            合成元となる動画パス。
        overlays: List[Dict[str, Any]]
            重ね合わせる動画の設定リスト。
        """
        if not overlays:
            return base_video

        output_path = self.temp_dir / f"{base_video.stem}_fg.mp4"
        try:
            base_dur = await get_media_duration(str(base_video))
        except Exception:
            base_dur = None

        cmd: List[str] = [self.ffmpeg_path, "-y", "-nostdin", "-i", str(base_video)]
        for ov in overlays:
            timing = ov.get("timing", {})
            if timing.get("loop"):
                cmd.extend(["-stream_loop", "-1"])
            src_path = Path(ov["src"]).resolve()
            # 画像は -loop 1 と -framerate を付与し、長さはベースに合わせる
            if self._is_image(src_path):
                fps = int(ov.get("fps") or getattr(self.video_params, "fps", 30) or 30)
                cmd.extend(["-loop", "1", "-framerate", str(fps), "-t", f"{(base_dur or 0):.3f}"])
            cmd.extend(["-i", str(src_path)])

        cmd.extend(self._single_job_thread_flags())

        filter_parts: List[str] = []
        prev_stream = "[0:v]"
        for idx, ov in enumerate(overlays):
            in_stream = f"[{idx + 1}:v]"
            overlay_filters, processed = self._build_overlay_filter_parts(in_stream, idx, ov)
            filter_parts.extend(overlay_filters)

            pos = ov.get("position", {})
            x = pos.get("x", 0)
            y = pos.get("y", 0)
            timing = ov.get("timing", {})
            start = float(timing.get("start", 0.0))
            duration = timing.get("duration")
            if duration is not None:
                end = start + float(duration)
                enable = f"between(t,{start},{end})"
            else:
                enable = f"gte(t,{start})"

            preserve_color = bool(ov.get("preserve_color", False))
            if ov.get("mode") == "blend" and not preserve_color:
                blend_mode = ov.get("blend_mode", "screen")
                filter_parts.append(
                    f"{prev_stream}{processed}blend=all_mode={blend_mode}:enable='{enable}'[tmp{idx}]"
                )
            else:
                filter_parts.append(
                    f"{prev_stream}{processed}overlay=x={x}:y={y}:enable='{enable}'[tmp{idx}]"
                )
            prev_stream = f"[tmp{idx}]"

        filter_complex = ";".join(filter_parts)
        cmd.extend(["-filter_complex", filter_complex, "-map", prev_stream, "-map", "0:a?"])
        cmd.extend(self.video_params.to_ffmpeg_opts(self.hw_kind))
        cmd.extend(["-c:a", "copy"])
        if base_dur and base_dur > 0:
            cmd.extend(["-t", f"{base_dur:.3f}"])
        cmd.append(str(output_path))

        await _run_ffmpeg(cmd)
        return output_path

    async def apply_overlays(
        self,
        base_video: Path,
        overlays: List[Dict[str, Any]],
        subtitles: List[Dict[str, Any]],
    ) -> Path:
        """前景動画と字幕PNGを同時に焼き込む。"""
        if not overlays and not subtitles:
            return base_video

        output_path = self.temp_dir / f"{base_video.stem}_fg_sub.mp4"
        try:
            base_dur = await get_media_duration(str(base_video))
        except Exception:
            base_dur = None

        cmd: List[str] = [self.ffmpeg_path, "-y", "-nostdin", "-i", str(base_video)]

        for ov in overlays or []:
            timing = ov.get("timing", {})
            if timing.get("loop"):
                cmd.extend(["-stream_loop", "-1"])
            src_path = Path(ov["src"]).resolve()
            if self._is_image(src_path):
                fps = int(ov.get("fps") or getattr(self.video_params, "fps", 30) or 30)
                cmd.extend(["-loop", "1", "-framerate", str(fps), "-t", f"{(base_dur or 0):.3f}"])
            cmd.extend(["-i", str(src_path)])

        cmd.extend(self._single_job_thread_flags())

        filter_parts: List[str] = []
        prev_stream = "[0:v]"
        use_cuda_for_subtitles = self._should_use_cuda_for_subtitles(subtitles or [])
        subtitle_mode = self._subtitle_render_mode(subtitles or [])

        for idx, ov in enumerate(overlays or []):
            in_stream = f"[{idx + 1}:v]"
            overlay_filters, processed = self._build_overlay_filter_parts(in_stream, idx, ov)
            filter_parts.extend(overlay_filters)

            pos = ov.get("position", {})
            x = pos.get("x", 0)
            y = pos.get("y", 0)
            timing = ov.get("timing", {})
            start = float(timing.get("start", 0.0))
            duration = timing.get("duration")
            if duration is not None:
                end = start + float(duration)
                enable = f"between(t,{start},{end})"
            else:
                enable = f"gte(t,{start})"

            preserve_color = bool(ov.get("preserve_color", False))
            if ov.get("mode") == "blend" and not preserve_color:
                blend_mode = ov.get("blend_mode", "screen")
                filter_parts.append(
                    f"{prev_stream}{processed}blend=all_mode={blend_mode}:enable='{enable}'[tmp{idx}]"
                )
            else:
                filter_parts.append(
                    f"{prev_stream}{processed}overlay=x={x}:y={y}:enable='{enable}'[tmp{idx}]"
                )
            prev_stream = f"[tmp{idx}]"

        overlay_input_count = len(overlays or [])
        if subtitle_mode == "ass" and subtitles:
            ass_path = self._build_ass_subtitle_file(
                f"{base_video.stem}_subtitle_overlay",
                subtitles,
            )
            logger.info("[SubtitleOverlay] Using ASS/libass mode for %s subtitle(s)", len(subtitles))
            filter_parts.append(
                f"{prev_stream}{self._build_ass_filter(ass_path)}[with_subtitle_ass]"
            )
            prev_stream = "[with_subtitle_ass]"
        else:
            png_added = 0
            for sub in subtitles or []:
                png_input_index = overlay_input_count + png_added + 1
                extra_input, snippet = await self.subtitle_gen.build_subtitle_overlay(
                    sub.get("text", ""),
                    float(sub.get("duration", 0.0)),
                    sub.get("line_config", {}),
                    in_label=prev_stream.strip("[]"),
                    index=png_input_index,
                    allow_cuda=use_cuda_for_subtitles,
                )
                for k, v in extra_input.items():
                    cmd.extend([k, v])
                png_added += 1
                start = float(sub.get("start", 0.0))
                end = start + float(sub.get("duration", 0.0))
                snippet = snippet.replace(
                    f"between(t,0,{sub.get('duration')})", f"between(t,{start},{end})"
                )
                filter_parts.append(snippet)
                prev_stream = f"[with_subtitle_{png_input_index}]"

        filter_complex = ";".join(filter_parts)
        cmd.extend(["-filter_complex", filter_complex, "-map", prev_stream, "-map", "0:a?"])
        cmd.extend(self._subtitle_burn_video_opts(subtitle_mode))
        cmd.extend(["-c:a", "copy"])
        if base_dur and base_dur > 0:
            cmd.extend(["-t", f"{base_dur:.3f}"])
        cmd.append(str(output_path))

        await _run_ffmpeg(cmd)
        return output_path

    async def apply_subtitle_overlays(
        self, base_video: Path, subtitles: List[Dict[str, Any]]
    ) -> Path:
        """字幕PNGのみを順次焼き込む。"""
        if not subtitles:
            return base_video

        output_path = self.temp_dir / f"{base_video.stem}_sub.mp4"
        subtitle_mode = self._subtitle_render_mode(subtitles)
        try:
            base_dur = await get_media_duration(str(base_video))
        except Exception:
            base_dur = None

        video_cfg = getattr(self, "video_config", {}) or {}
        if (
            subtitle_mode == "png"
            and base_dur
            and bool(video_cfg.get("subtitle_layer_video", False))
        ):
            logger.info(
                "[SubtitleOverlay] Layer-video mode: generating transparent subtitle layer (%d subtitles, base=%.2fs)",
                len(subtitles),
                float(base_dur),
            )
            try:
                layer_path = await self._render_subtitle_layer_video(
                    subtitles,
                    duration=float(base_dur),
                    output_path=self.temp_dir / f"{base_video.stem}_subtitle_layer.mov",
                )
                return await self._overlay_subtitle_layer_video(
                    base_video,
                    layer_path,
                    output_path,
                    duration=float(base_dur),
                )
            except Exception as err:
                logger.warning(
                    "[SubtitleOverlay] Layer-video mode failed (%s). Falling back to default burn.",
                    err,
                )

        if subtitle_mode == "png" and base_dur and len(subtitles) >= 2:
            gap_threshold = float(
                (self.subtitle_gen.subtitle_config or {}).get(
                    "copy_gap_threshold", 0.20
                )
            )
            png_chunk_size = self._subtitle_png_chunk_size()
            ranges = self._split_subtitle_ranges_for_png(
                subtitles,
                base_duration=float(base_dur),
                gap_threshold=gap_threshold,
                max_subtitles=png_chunk_size,
            )
            if ranges and (
                ranges[0]["start"] > 0.05
                or ranges[-1]["end"] < float(base_dur) - 0.05
                or len(ranges) > 1
            ):
                logger.info(
                    "[SubtitleOverlay] Segment mode: re-encoding %d subtitle chunk(s), copying gaps (base=%.2fs, subtitles=%d, png_chunk_size=%d)",
                    len(ranges),
                    float(base_dur),
                    len(subtitles),
                    png_chunk_size,
                )
                segment_paths: List[Path] = []
                cursor = 0.0
                for seg_idx, item in enumerate(ranges):
                    start = float(item["start"])
                    end = float(item["end"])
                    if start > cursor + 0.02:
                        copied = await self._copy_video_segment(
                            base_video,
                            self.temp_dir / f"{base_video.stem}_sub_gap_{seg_idx:03d}.mp4",
                            cursor,
                            start - cursor,
                        )
                        if copied:
                            segment_paths.append(copied)

                    adjusted: List[Dict[str, Any]] = []
                    for sub in item["subtitles"]:
                        copied_sub = dict(sub)
                        copied_sub["start"] = max(0.0, float(sub["start"]) - start)
                        adjusted.append(copied_sub)
                    seg_base = self.temp_dir / f"{base_video.stem}_sub_base_{seg_idx:03d}.mp4"
                    await self._copy_video_segment(base_video, seg_base, start, end - start)
                    burned = await self._apply_subtitle_overlays_full(
                        seg_base,
                        adjusted,
                        self.temp_dir / f"{base_video.stem}_sub_burn_{seg_idx:03d}.mp4",
                    )
                    segment_paths.append(burned)
                    cursor = end

                if float(base_dur) > cursor + 0.02:
                    copied = await self._copy_video_segment(
                        base_video,
                        self.temp_dir / f"{base_video.stem}_sub_gap_tail.mp4",
                        cursor,
                        float(base_dur) - cursor,
                    )
                    if copied:
                        segment_paths.append(copied)

                try:
                    await concat_videos_copy(
                        [str(path.resolve()) for path in segment_paths],
                        str(output_path),
                        self.ffmpeg_path,
                    )
                    return output_path
                except Exception as err:
                    logger.warning(
                        "[SubtitleOverlay] Segment concat failed (%s). Falling back to full subtitle burn.",
                        err,
                    )

        return await self._apply_subtitle_overlays_full(base_video, subtitles, output_path)

    async def _render_subtitle_layer_video(
        self,
        subtitles: List[Dict[str, Any]],
        *,
        duration: float,
        output_path: Path,
    ) -> Path:
        """Render subtitle PNGs into one transparent intermediate video."""
        params = self.video_params
        cmd: List[str] = [
            self.ffmpeg_path,
            "-y",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            (
                f"color=c=black@0.0:s={int(params.width)}x{int(params.height)}:"
                f"r={int(params.fps)}:d={duration:.3f},format=rgba"
            ),
        ]

        filter_parts: List[str] = []
        prev_stream = "[0:v]"
        for idx, sub in enumerate(subtitles, start=1):
            input_index = idx
            extra_input, snippet = await self.subtitle_gen.build_subtitle_overlay(
                sub["text"],
                sub["duration"],
                sub.get("line_config", {}),
                in_label=prev_stream.strip("[]"),
                index=input_index,
                force_cpu=True,
                allow_cuda=False,
            )
            for k, v in extra_input.items():
                cmd.extend([k, v])

            start = float(sub["start"])
            end = start + float(sub["duration"])
            snippet = snippet.replace(
                f"between(t,0,{sub['duration']})", f"between(t,{start},{end})"
            )
            filter_parts.append(snippet)
            prev_stream = f"[with_subtitle_{input_index}]"

        cmd.extend(self._single_job_thread_flags())
        cmd.extend(["-filter_complex", ";".join(filter_parts), "-map", prev_stream])
        cmd.extend(["-an", "-c:v", "qtrle", "-pix_fmt", "argb", "-t", f"{duration:.3f}"])
        cmd.append(str(output_path))

        await _run_ffmpeg(cmd)
        return output_path

    async def _overlay_subtitle_layer_video(
        self,
        base_video: Path,
        layer_video: Path,
        output_path: Path,
        *,
        duration: float,
    ) -> Path:
        """Overlay a pre-rendered transparent subtitle layer onto the base video."""
        cmd: List[str] = [
            self.ffmpeg_path,
            "-y",
            "-nostdin",
            "-i",
            str(base_video),
            "-i",
            str(layer_video),
        ]
        cmd.extend(self._single_job_thread_flags())
        cmd.extend(
            [
                "-filter_complex",
                "[0:v][1:v]overlay=0:0:format=auto[final_v]",
                "-map",
                "[final_v]",
                "-map",
                "0:a?",
            ]
        )
        cmd.extend(self._subtitle_burn_video_opts("png"))
        cmd.extend(["-c:a", "copy", "-t", f"{duration:.3f}", str(output_path)])
        await _run_ffmpeg(cmd)
        return output_path

    async def _apply_subtitle_overlays_full(
        self,
        base_video: Path,
        subtitles: List[Dict[str, Any]],
        output_path: Path,
    ) -> Path:
        subtitle_mode = self._subtitle_render_mode(subtitles)
        try:
            base_dur = await get_media_duration(str(base_video))
        except Exception:
            base_dur = None
        cmd: List[str] = [self.ffmpeg_path, "-y", "-nostdin", "-i", str(base_video)]

        filter_parts: List[str] = []
        prev_stream = "[0:v]"
        if subtitle_mode == "ass":
            ass_path = self._build_ass_subtitle_file(
                f"{base_video.stem}_subtitle_only",
                subtitles,
            )
            logger.info("[SubtitleOverlay] Using ASS/libass mode for %s subtitle(s)", len(subtitles))
            filter_parts.append(
                f"{prev_stream}{self._build_ass_filter(ass_path)}[with_subtitle_ass]"
            )
            prev_stream = "[with_subtitle_ass]"
        else:
            use_cuda_for_subtitles = self._should_use_cuda_for_subtitles(subtitles)
            for idx, sub in enumerate(subtitles):
                extra_input, snippet = await self.subtitle_gen.build_subtitle_overlay(
                    sub["text"],
                    sub["duration"],
                    sub.get("line_config", {}),
                    in_label=prev_stream.strip("[]"),
                    index=idx + 1,
                    allow_cuda=use_cuda_for_subtitles,
                )
                for k, v in extra_input.items():
                    cmd.extend([k, v])

                start = float(sub["start"])
                end = start + float(sub["duration"])
                snippet = snippet.replace(
                    f"between(t,0,{sub['duration']})", f"between(t,{start},{end})"
                )
                filter_parts.append(snippet)
                prev_stream = f"[with_subtitle_{idx + 1}]"

        cmd.extend(self._single_job_thread_flags())
        filter_complex = ";".join(filter_parts)
        cmd.extend(["-filter_complex", filter_complex, "-map", prev_stream, "-map", "0:a?"])
        cmd.extend(self._subtitle_burn_video_opts(subtitle_mode))
        cmd.extend(["-c:a", "copy"])
        if base_dur and base_dur > 0:
            cmd.extend(["-t", f"{base_dur:.3f}"])
        cmd.append(str(output_path))

        await _run_ffmpeg(cmd)
        return output_path
