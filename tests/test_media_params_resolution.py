import pytest

from zundamotion.pipeline import GenerationPipeline
from zundamotion.utils.export_presets import apply_export_preset
from zundamotion.utils.ffmpeg_params import resolve_media_params


@pytest.mark.parametrize(
    ("preset", "size"),
    [
        ("youtube_1080p", (1920, 1080)),
        ("youtube_1440p", (2560, 1440)),
        ("shorts_1080x1920", (1080, 1920)),
        ("draft_720p", (1280, 720)),
    ],
)
def test_export_preset_resolves_expected_final_size(preset, size):
    video, audio = resolve_media_params(apply_export_preset({"export_preset": preset}))
    assert (video.width, video.height) == size
    assert (audio.sample_rate, audio.channels) == (48000, 2)


def test_explicit_fps_wins_and_pipeline_resolves_one_shared_pair(tmp_path):
    config = {
        "export_preset": "draft_720p",
        "video": {"fps": 24, "audio_sample_rate": 44100, "audio_channels": 1},
        "system": {"cache_dir": str(tmp_path / "cache")},
    }
    pipeline = GenerationPipeline(config)
    assert (pipeline.video_params.width, pipeline.video_params.height, pipeline.video_params.fps) == (
        1280,
        720,
        24,
    )
    assert (pipeline.audio_params.sample_rate, pipeline.audio_params.channels) == (44100, 1)
