import asyncio
from pathlib import Path

from zundamotion.components.pipeline_phases.bgm_phase import BGMPhase
from zundamotion.timeline import Timeline
from zundamotion.utils.ffmpeg_params import AudioParams


def test_bgm_phase_closes_looped_segments_with_wrapped_source_position(monkeypatch, tmp_path: Path):
    captured = {}

    async def fake_get_media_duration(_path: str) -> float:
        return 10.0

    async def fake_get_audio_duration(_path: str) -> float:
        return 3.0

    async def fake_add_bgm_segments_to_video(video_path, output_path, *, bgm_layers, segments, audio_params, ffmpeg_path="ffmpeg"):
        captured["segments"] = segments
        Path(output_path).write_bytes(b"mp4")
        return "filter"

    monkeypatch.setattr(
        "zundamotion.components.pipeline_phases.bgm_phase.get_media_duration",
        fake_get_media_duration,
    )
    monkeypatch.setattr(
        "zundamotion.components.pipeline_phases.bgm_phase.get_audio_duration",
        fake_get_audio_duration,
    )
    monkeypatch.setattr(
        "zundamotion.components.pipeline_phases.bgm_phase.add_bgm_segments_to_video",
        fake_add_bgm_segments_to_video,
    )

    video = tmp_path / "input.mp4"
    video.write_bytes(b"mp4")
    timeline = Timeline()
    timeline.add_bgm_event("main", "start")
    timeline.add_bgm_event("main", "stop")
    timeline.bgm_events[1]["time"] = 8.0

    phase = BGMPhase(
        config={"script": {"bgm_layers": [{"id": "main", "file": "bgm.wav", "loop": True}]}},
        temp_dir=tmp_path,
        audio_params=AudioParams(),
    )
    output = asyncio.run(phase.run(video, timeline))

    assert output == tmp_path / "final_with_bgm.mp4"
    assert captured["segments"] == [
        {
            "id": "main",
            "timeline_start": 0.0,
            "timeline_end": 8.0,
            "source_start_pos": 0.0,
            "duration": 8.0,
            "fade_in": 0.0,
            "fade_out": 0.0,
            "gain": 0.0,
        }
    ]


def test_bgm_phase_applies_mastering_without_bgm(monkeypatch, tmp_path: Path):
    captured = {}

    async def fake_apply_master_audio_filter(input_path, output_path, *, audio_params, loudnorm=None, ffmpeg_path="ffmpeg"):
        captured["input_path"] = input_path
        captured["loudnorm"] = loudnorm
        Path(output_path).write_bytes(b"mp4")

    monkeypatch.setattr(
        "zundamotion.components.pipeline_phases.bgm_phase.apply_master_audio_filter",
        fake_apply_master_audio_filter,
    )

    video = tmp_path / "input.mp4"
    video.write_bytes(b"mp4")
    phase = BGMPhase(
        config={"audio": {"master_loudnorm": {"i": -14, "tp": -1.0, "lra": 10}}},
        temp_dir=tmp_path,
        audio_params=AudioParams(),
    )

    output = asyncio.run(phase.run(video, Timeline()))

    assert output == tmp_path / "final_mastered.mp4"
    assert captured["input_path"] == str(video)
    assert captured["loudnorm"] == {"i": -14, "tp": -1.0, "lra": 10}
