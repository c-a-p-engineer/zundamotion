import re
from typing import Any, Dict, Tuple

from ...cache import CacheManager

from ...utils.ffmpeg_capabilities import has_cuda_filters, is_nvenc_available
from ...utils.ffmpeg_hw import get_hw_filter_mode
from .png import SubtitlePNGRenderer


class SubtitleGenerator:
    def __init__(self, config: Dict[str, Any], cache_manager: CacheManager):
        self.subtitle_config = config.get("subtitle", {})
        self.png_renderer = SubtitlePNGRenderer(cache_manager)

    async def build_subtitle_overlay(
        self,
        text: str,
        duration: float,
        line_config: Dict[str, Any],
        in_label: str,
        index: int,
        force_cpu: bool = False,
        allow_cuda: bool | None = None,
        existing_png_path: str | None = None,
    ) -> Tuple[Dict[str, Any], str]:
        """
        Returns:
            extra_input: {"-loop": "1", "-i": <png>}
            filter_snippet: FFmpeg filter graph snippet
        """
        style = self.subtitle_config.copy()
        style.update(line_config)
        if "subtitle" in line_config and isinstance(line_config["subtitle"], dict):
            style.update(line_config["subtitle"])

        # Reuse pre-generated subtitle PNG if provided (e.g., on fallback retry)
        if existing_png_path:
            from pathlib import Path

            p = Path(existing_png_path)
            if p.exists():
                png_path = p
            else:
                png_path, dims = await self.png_renderer.render(text, style)
        else:
            png_path, dims = await self.png_renderer.render(text, style)

        # 位置式（あなたの置換ロジックはそのまま活かす）
        # Convert drawtext-style expr to overlay(_cuda) variables
        def convert_expr(expr: str) -> str:
            # Preserve text_* first using placeholders to avoid nested replacements
            expr = expr.replace("text_w", "{OVERLAY_W}").replace("text_h", "{OVERLAY_H}")
            # drawtext: w/h => main width/height; overlay: W/H are main dims
            # Replace lone 'w'/'h' tokens with 'W'/'H'
            expr = re.sub(r"(?<![A-Za-z_])w(?![A-Za-z_])", "W", expr)
            expr = re.sub(r"(?<![A-Za-z_])h(?![A-Za-z_])", "H", expr)
            # Uppercase W/H can be kept as-is for overlay filters
            # Restore placeholders to overlay input dims (w/h)
            expr = expr.replace("{OVERLAY_W}", "w").replace("{OVERLAY_H}", "h")
            return expr

        y_expr = convert_expr(style.get("y", "H-100"))
        x_expr = convert_expr(style.get("x", "(W-w)/2"))

        # CUDA 使用可否は VideoRenderer 側の判定結果（allow_cuda）を優先
        global_mode = get_hw_filter_mode()
        if global_mode == "cpu":
            use_cuda = False
        elif allow_cuda is None:
            use_cuda = (not force_cpu) and await is_nvenc_available() and await has_cuda_filters()
        else:
            use_cuda = (not force_cpu) and bool(allow_cuda)

        extra_input = {"-loop": "1", "-i": str(png_path)}

        if use_cuda:
            # GPU: メイン側/字幕側ともに GPU フレームへ upload → overlay_cuda
            # in_label が CPU のまま来ても自衛的に GPU 化（重複しても副作用なし）
            filter_snippet = (
                f"[{in_label}]format=nv12,hwupload_cuda[bg_gpu_{index}];"
                f"[{index}:v]format=rgba,hwupload_cuda[sub_gpu_{index}];"
                f"[bg_gpu_{index}][sub_gpu_{index}]overlay_cuda="
                f"x='{x_expr}':y='{y_expr}':enable='between(t,0,{duration})'"
                f"[with_subtitle_{index}]"
            )
        else:
            # CPU fallback
            filter_snippet = (
                f"[{in_label}][{index}:v]overlay="
                f"x='{x_expr}':y='{y_expr}':enable='between(t,0,{duration})'"
                f"[with_subtitle_{index}]"
            )

        return extra_input, filter_snippet
