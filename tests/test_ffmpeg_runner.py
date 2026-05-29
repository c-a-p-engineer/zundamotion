from __future__ import annotations

from zundamotion.utils.ffmpeg_runner import _extract_av_warning_items


def test_extract_av_warning_items_classifies_known_timestamp_warnings() -> None:
    stderr_text = """
    [mp4 @ 0x123] Non-monotonic DTS in output stream
    [aac @ 0x456] Queue input is backward in time
    Past duration 0.123 too large
    invalid dropping
    """

    items = _extract_av_warning_items(stderr_text)

    assert [item["type"] for item in items] == [
        "non_monotonic_dts",
        "queue_input_backward",
        "past_duration",
        "invalid_dropping",
    ]
