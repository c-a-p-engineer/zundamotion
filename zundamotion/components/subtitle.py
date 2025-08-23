import textwrap
from typing import Any, Dict


class SubtitleGenerator:
    def __init__(self, config: Dict[str, Any]):
        self.subtitle_config = config.get("subtitle", {})

    def get_drawtext_filter(
        self, text: str, duration: float, line_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Creates a dictionary of options for ffmpeg's drawtext filter.

        Args:
            text (str): The text to display.
            duration (float): The duration the text should be visible.
            line_config (Dict[str, Any]): The specific config for this line.

        Returns:
            Dict[str, Any]: A dictionary of drawtext options.
        """
        # Get style from config, allowing line-specific overrides
        # Start with global subtitle config
        style = self.subtitle_config.copy()

        # Merge line-specific subtitle settings, which should already include character defaults
        # The script_loader should have merged character defaults and line-specific overrides into line_config
        # So, we just need to merge line_config itself, as it contains the final merged settings
        style.update(line_config)

        # If there's a nested 'subtitle' key in line_config (from character defaults or line override),
        # merge that as well. This handles cases where subtitle settings are explicitly nested.
        if "subtitle" in line_config and isinstance(line_config["subtitle"], dict):
            style.update(line_config["subtitle"])

        # 自動改行を適用
        max_chars = style.get("max_chars_per_line")
        if max_chars:
            wrapped_text = self._wrap_text(text, max_chars)
        else:
            wrapped_text = text

        # Escape text for ffmpeg
        escaped_text = self._escape_text(wrapped_text)

        # y座標の基本式を取得
        y_base_expression = style.get("y")
        # 自動改行後の行数を取得
        num_lines = wrapped_text.count("\n") + 1
        # 行数に応じた追加のオフセットを計算
        line_offset_per_line = style.get("line_spacing_offset_per_line", 0)
        additional_y_offset = (num_lines - 1) * line_offset_per_line
        # y式にオフセットを組み込む
        if additional_y_offset > 0:
            final_y_expression = f"{y_base_expression} - {additional_y_offset}"
        else:
            final_y_expression = y_base_expression

        return {
            "text": escaped_text,
            "fontfile": style.get("font_path"),
            "fontcolor": style.get("font_color"),
            "fontsize": style.get("font_size"),
            "x": style.get("x"),
            "y": final_y_expression,
            "box": 1,
            "boxcolor": "black@0.5",
            "boxborderw": 5,
            "enable": f"between(t,0,{duration})",
        }

    def _wrap_text(self, text: str, max_chars_per_line: int) -> str:
        """
        Wraps text to a specified maximum number of characters per line.
        """
        return textwrap.fill(text, width=max_chars_per_line)

    def _normalize_newlines(self, s: str) -> str:
        # 既存の実改行統一 + リテラル "\n" → 実改行
        return s.replace("\r\n", "\n").replace("\r", "\n").replace("\\n", "\n")

    def _escape_text(self, text: str) -> str:
        """
        FFmpeg drawtext向けエスケープ。
        - まずリテラル \n を実改行に戻す（ダブルエスケープ対策）
        - バックスラッシュは1回だけエスケープ
        - 実改行は '\n' に変換
        - コロンとシングルクォートも1回だけエスケープ
        """
        text = self._normalize_newlines(text)
        text = text.replace("\\", r"\\")
        # text = text.replace("\n", r"\n")
        text = text.replace(":", r"\:")
        text = text.replace("'", r"\'")
        return text
