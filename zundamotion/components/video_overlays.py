"""動画オーバーレイ処理を担当するMixinモジュール。

VideoRendererに継承させることで、前景動画や字幕PNGを
ベース映像に重ねるユーティリティを提供する。
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

from importlib import import_module

from ..utils.ffmpeg_probe import get_media_duration


async def _run_ffmpeg(cmd: List[str]) -> None:
    """videoモジュール経由でffmpegを実行するラッパー。"""
    video_module = import_module("zundamotion.components.video")
    await video_module._run_ffmpeg_async(cmd)


class OverlayMixin:
    """FFmpegを用いたオーバーレイ合成機能のMixinクラス。"""

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
            cmd.extend(["-i", str(Path(ov["src"]).resolve())])

        cmd.extend(self._thread_flags())

        filter_parts: List[str] = []
        prev_stream = "[0:v]"
        for idx, ov in enumerate(overlays):
            in_stream = f"[{idx + 1}:v]"
            steps: List[str] = []
            mode = ov.get("mode", "overlay")
            fps = ov.get("fps")
            if fps:
                steps.append(f"fps={int(fps)}")
            scale_cfg = ov.get("scale", {})
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
            steps.append("format=rgba")
            opacity = ov.get("opacity")
            if opacity is not None:
                steps.append(f"colorchannelmixer=aa={float(opacity)}")
            processed = f"[ov{idx}]"
            filter_parts.append(f"{in_stream}{','.join(steps)}{processed}")

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

            if mode == "blend":
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
            cmd.extend(["-i", str(Path(ov["src"]).resolve())])

        cmd.extend(self._thread_flags())

        filter_parts: List[str] = []
        prev_stream = "[0:v]"

        for idx, ov in enumerate(overlays or []):
            in_stream = f"[{idx + 1}:v]"
            steps: List[str] = []
            mode = ov.get("mode", "overlay")
            fps = ov.get("fps")
            if fps:
                steps.append(f"fps={int(fps)}")
            scale_cfg = ov.get("scale", {})
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
            steps.append("format=rgba")
            opacity = ov.get("opacity")
            if opacity is not None:
                steps.append(f"colorchannelmixer=aa={float(opacity)}")
            processed = f"[ov{idx}]"
            filter_parts.append(f"{in_stream}{','.join(steps)}{processed}")

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

            if mode == "blend":
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
        png_added = 0
        for sub in subtitles or []:
            png_input_index = overlay_input_count + png_added + 1
            extra_input, snippet = await self.subtitle_gen.build_subtitle_overlay(
                sub.get("text", ""),
                float(sub.get("duration", 0.0)),
                sub.get("line_config", {}),
                in_label=prev_stream.strip("[]"),
                index=png_input_index,
                allow_cuda=self.gpu_overlay_backend == "cuda",
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
        cmd.extend(self.video_params.to_ffmpeg_opts(self.hw_kind))
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
        try:
            base_dur = await get_media_duration(str(base_video))
        except Exception:
            base_dur = None
        cmd: List[str] = [self.ffmpeg_path, "-y", "-nostdin", "-i", str(base_video)]

        filter_parts: List[str] = []
        prev_stream = "[0:v]"
        for idx, sub in enumerate(subtitles):
            extra_input, snippet = await self.subtitle_gen.build_subtitle_overlay(
                sub["text"],
                sub["duration"],
                sub.get("line_config", {}),
                in_label=prev_stream.strip("[]"),
                index=idx + 1,
                allow_cuda=self.gpu_overlay_backend == "cuda",
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

        cmd.extend(self._thread_flags())
        filter_complex = ";".join(filter_parts)
        cmd.extend(["-filter_complex", filter_complex, "-map", prev_stream, "-map", "0:a?"])
        cmd.extend(self.video_params.to_ffmpeg_opts(self.hw_kind))
        cmd.extend(["-c:a", "copy"])
        if base_dur and base_dur > 0:
            cmd.extend(["-t", f"{base_dur:.3f}"])
        cmd.append(str(output_path))

        await _run_ffmpeg(cmd)
        return output_path
