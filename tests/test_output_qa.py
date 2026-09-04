from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from zundamotion.output_qa import (
    OUTPUT_INSPECTION_FORMAT,
    expected_from_config,
    expected_from_preset,
    inspect_output,
    representative_timestamps,
)


def test_expected_from_config_tracks_observable_media_contract() -> None:
    expected = expected_from_config(
        {
            "export_preset": "shorts_1080x1920",
            "video": {
                "width": 1080,
                "height": 1920,
                "fps": 30,
                "audio_codec": "aac",
                "audio_sample_rate": 48000,
                "audio_channels": 2,
                "crf": 20,
            },
        }
    )

    assert expected == {
        "export_preset": "shorts_1080x1920",
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "audio_codec": "aac",
        "audio_sample_rate": 48000,
        "audio_channels": 2,
    }


def test_expected_from_preset_uses_existing_export_preset_contract() -> None:
    expected = expected_from_preset("shorts_1080x1920")

    assert expected["width"] == 1080
    assert expected["height"] == 1920
    assert expected["fps"] == 30
    assert expected["audio_sample_rate"] == 48000
    assert expected["audio_channels"] == 2


def test_representative_timestamps_avoid_exact_boundaries() -> None:
    timestamps = representative_timestamps(100.0, 5)

    assert timestamps == pytest.approx([5.0, 27.5, 50.0, 72.5, 95.0])


def test_representative_timestamps_reject_invalid_sample_count() -> None:
    with pytest.raises(ValueError, match="between 1 and 12"):
        representative_timestamps(10.0, 13)


def test_inspect_output_reports_preset_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"not-empty")

    async def fake_probe(*args, **kwargs):
        return {
            "duration": 12.5,
            "video": {
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "pix_fmt": "yuv420p",
                "r_frame_rate": "30/1",
                "fps": 30.0,
            },
            "audio": {
                "codec_name": "aac",
                "sample_rate": 48000,
                "channels": 2,
                "channel_layout": "stereo",
            },
        }

    monkeypatch.setattr("zundamotion.output_qa.get_media_info", fake_probe)
    document = asyncio.run(
        inspect_output(
            media_path,
            expected=expected_from_preset("shorts_1080x1920"),
        )
    )

    assert document["format"] == OUTPUT_INSPECTION_FORMAT
    assert document["valid"] is False
    failures = {item["id"] for item in document["checks"] if item["status"] == "fail"}
    assert failures == {"width", "height"}
    assert document["visual_review"]["status"] == "not_generated"
