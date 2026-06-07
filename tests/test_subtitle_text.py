import re
import sys
from pathlib import Path

import pysubs2

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


def test_timeline_resync_with_scene_durations_updates_topics_and_scene_starts():
    timeline = Timeline()
    scenes = [
        {
            "id": "intro",
            "bg": "intro.png",
            "items": [
                {"topic": "導入"},
                {"say": {"text": "最初のセリフ", "characters": [{"enter": True, "enter_duration": 0.5}]}},
            ],
        },
        {
            "id": "main",
            "bg": "main.png",
            "items": [
                {"topic": "本編"},
                {"wait": 1.0},
                {"say": {"text": "次のセリフ", "characters": [{"leave": True, "leave_duration": 0.3}]}},
            ],
        },
    ]

    timeline.add_scene_change("intro", "intro.png")
    timeline.add_topic("導入")
    timeline.add_event('copetan: "最初のセリフ"', 1.0, text="最初のセリフ")
    timeline.add_scene_change("main", "main.png")
    timeline.add_topic("本編")
    timeline.add_event("(Wait 1.0s)", 1.0, text=None)
    timeline.add_event('copetan: "次のセリフ"', 2.0, text="次のセリフ")

    line_data_map = {
        "intro_1": {"duration": 1.5, "pre_duration": 0.5, "post_duration": 0.0},
        "main_1": {"duration": 1.0},
        "main_2": {"duration": 2.3, "pre_duration": 0.0, "post_duration": 0.3},
    }

    timeline.resync_with_scene_durations(scenes, line_data_map)

    assert timeline.events[0]["start_time"] == 0.0
    assert timeline.events[1]["start_time"] == 0.0
    assert timeline.events[1]["duration"] == 1.5
    assert timeline.events[2]["start_time"] == 1.5
    assert timeline.events[3]["start_time"] == 1.5
    assert timeline.events[3]["duration"] == 1.0
    assert timeline.events[4]["start_time"] == 2.5
    assert timeline.events[4]["duration"] == 2.3
    assert timeline.topics[0]["time"] == 0.0
    assert timeline.topics[1]["time"] == 1.5
    assert timeline.current_time == 4.8
    assert timeline.events[1]["subtitle_start_time"] == 0.5
    assert timeline.events[1]["subtitle_end_time"] == 1.5
    assert timeline.events[4]["subtitle_start_time"] == 2.5
    assert timeline.events[4]["subtitle_end_time"] == 4.5


def test_timeline_save_subtitles_uses_subtitle_specific_bounds(tmp_path):
    timeline = Timeline()
    timeline.add_event("line", 2.0, text="字幕")
    timeline.events[0]["subtitle_start_time"] = 0.4
    timeline.events[0]["subtitle_end_time"] = 1.6

    output_path = tmp_path / "subtitle_bounds.srt"
    timeline.save_subtitles(output_path, format="srt")

    subs = pysubs2.load(str(output_path), format="srt")
    assert len(subs) == 1
    assert subs[0].start == 400
    assert subs[0].end == 1600


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
