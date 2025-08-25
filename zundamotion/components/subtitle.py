from typing import Any, Dict, Tuple

from zundamotion.cache import CacheManager

from ..utils.ffmpeg_utils import has_cuda_filters, is_nvenc_available
from .subtitle_png import SubtitlePNGRenderer


class SubtitleGenerator:
    def __init__(self, config: Dict[str, Any], cache_manager: CacheManager):
        self.subtitle_config = config.get("subtitle", {})
        self.png_renderer = SubtitlePNGRenderer(cache_manager)

    def build_subtitle_overlay(
        self,
        text: str,
        duration: float,
        line_config: Dict[str, Any],
        in_label: str,
        index: int,
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

        png_path, dims = self.png_renderer.render(text, style)

        # 位置式（あなたの置換ロジックはそのまま活かす）
        y_expr = style.get("y", "H-100").replace("H", "main_h").replace("W", "main_w")
        y_expr = y_expr.replace("h", "overlay_h").replace("w", "overlay_w")
        x_expr = style.get("x", "(W-w)/2").replace("H", "main_h").replace("W", "main_w")
        x_expr = x_expr.replace("h", "overlay_h").replace("w", "overlay_w")

        use_cuda = is_nvenc_available() and has_cuda_filters()

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
