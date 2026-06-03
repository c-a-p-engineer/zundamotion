import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zundamotion.timeline import Timeline
from zundamotion.utils.subtitle_text import (
    is_effective_subtitle_text,
    normalize_subtitle_text,
    subtitle_char_display_width,
    subtitle_display_width,
    wrap_subtitle_text_by_display_width,
)


def test_normalize_subtitle_text_handles_common_break_markers():
    text = "Line1\\nLine2<BR/>Line3\r\nLine4"
    normalized = normalize_subtitle_text(text)
    assert normalized == "Line1\nLine2\nLine3\nLine4"


def test_is_effective_subtitle_text_uses_normalized_content():
    assert is_effective_subtitle_text("あ<br>い")
    assert not is_effective_subtitle_text("   <br>   ")


def test_timeline_save_subtitles_converts_breaks_for_ass(tmp_path):
    timeline = Timeline()
    timeline.add_event("line", 1.0, text="一行\\n二行")
    ass_path = tmp_path / "sample.ass"
    timeline.save_subtitles(ass_path, format="ass")
    content = ass_path.read_text(encoding="utf-8")
    assert "一行\\N二行" in content


def test_timeline_save_subtitles_preserves_newlines_for_srt(tmp_path):
    timeline = Timeline()
    timeline.add_event("line", 1.0, text="一行\\n二行")
    srt_path = tmp_path / "sample.srt"
    timeline.save_subtitles(srt_path, format="srt")
    content = srt_path.read_text(encoding="utf-8")
    # Normalize Windows-style newline variations before assertion
    normalized = re.sub(r"\r\n?", "\n", content)
    assert "一行\n二行" in normalized


def test_subtitle_char_display_width_counts_fullwidth_and_halfwidth():
    assert subtitle_char_display_width("あ") == 1.0
    assert subtitle_char_display_width("A") == 0.5
    assert subtitle_char_display_width(" ") == 0.5
    assert subtitle_char_display_width("　") == 1.0
    assert subtitle_char_display_width("\n") == 0.0


def test_subtitle_display_width_counts_ascii_as_halfwidth():
    assert subtitle_display_width("これは字幕テストです") == 10.0
    assert subtitle_display_width("GitHubActions") == 6.5
    assert subtitle_display_width("GitHubでCIを確認") == 8.0
    assert subtitle_display_width("npm install zundamotion") == 11.5


def test_wrap_subtitle_text_by_display_width_preserves_explicit_newlines():
    wrapped = wrap_subtitle_text_by_display_width("GitHub Actions\n失敗しました", 6)

    assert wrapped == "GitHub Actio\nns\n失敗しました"


def test_wrap_subtitle_text_by_display_width_handles_mixed_ascii_naturally():
    wrapped = wrap_subtitle_text_by_display_width("GitHubActionsでCIを確認します", 10)

    assert wrapped == "GitHubActionsでCIを\n確認します"
