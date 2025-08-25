from typing import Any, Dict, Tuple

from zundamotion.cache import CacheManager

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
        Generates a subtitle PNG and returns FFmpeg filter snippet and extra input.

        Args:
            text (str): The text to display.
            duration (float): The duration the text should be visible.
            line_config (Dict[str, Any]): The specific config for this line.
            in_label (str): The input video stream label to overlay on.
            index (int): The index of the subtitle input stream (e.g., 3 for [3:v]).

        Returns:
            Tuple[Dict[str, Any], str]:
                - Dict: extra_input for FFmpeg (e.g., {"-loop": "1", "-i": "path/to/sub.png"})
                - str: FFmpeg filter snippet for overlay.
        """
        style = self.subtitle_config.copy()
        style.update(line_config)
        if "subtitle" in line_config and isinstance(line_config["subtitle"], dict):
            style.update(line_config["subtitle"])

        png_path, dims = self.png_renderer.render(text, style)
        subtitle_w = dims["w"]
        subtitle_h = dims["h"]

        # y座標の基本式を取得
        y_base_expression = style.get("y", "H-100")  # Default to H-100 if not specified
        # 行数に応じた追加のオフセットを計算 (PNGレンダラで折り返し済みなので、ここでは不要)
        # ただし、y_base_expressionがH-hのような相対位置の場合、overlay_hを使う必要がある
        # ここでは、y_base_expressionをそのまま使い、overlay_hを考慮した式に変換する

        # 位置式の互換: W/H -> main_w/main_h, w/h -> overlay_w/overlay_h に置換
        # FFmpegのoverlayフィルタは、入力ストリームのラベルを自動的にmain_w/main_h, overlay_w/overlay_hにマッピングする
        # そのため、ここでは元のy式をそのまま使用し、FFmpegが解釈できるようにする
        # ただし、overlay_h/overlay_w を明示的に使う場合は、y_base_expressionを調整する必要がある

        # 例: y='H-100-h/2' の場合、Hはmain_h、hはoverlay_hになる
        # y='main_h-100-overlay_h/2'

        # ユーザー指定のy式をそのまま使うが、overlay_hを考慮した調整が必要な場合はここで変換する
        # 現状のタスク指示では「W/H → main_w/main_h、w/h → overlay_w/overlay_h に置換」とあるので、
        # y_base_expression が 'H-h' のような形式の場合、'main_h-overlay_h' に変換する

        # 簡単な置換ロジック
        final_y_expression = y_base_expression.replace("H", "main_h").replace(
            "W", "main_w"
        )
        final_y_expression = final_y_expression.replace("h", "overlay_h").replace(
            "w", "overlay_w"
        )

        # x座標も同様に変換
        x_base_expression = style.get("x", "(W-w)/2")  # Default to center
        final_x_expression = x_base_expression.replace("H", "main_h").replace(
            "W", "main_w"
        )
        final_x_expression = final_x_expression.replace("h", "overlay_h").replace(
            "w", "overlay_w"
        )

        extra_input = {"-loop": "1", "-i": str(png_path)}
        filter_snippet = (
            f"[{in_label}][{index}:v]overlay="
            f"x='{final_x_expression}':"
            f"y='{final_y_expression}':"
            f"enable='between(t,0,{duration})'[with_subtitle_{index}]"
        )

        return extra_input, filter_snippet
