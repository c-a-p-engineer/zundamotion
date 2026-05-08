import asyncio

from zundamotion.utils import ffmpeg_ops
from zundamotion.utils.ffmpeg_params import AudioParams, VideoParams


def test_apply_transition_local_copies_consumed_next_suffix(monkeypatch, tmp_path):
    calls = {"copy": [], "encode": [], "concat": []}

    async def fake_get_media_duration(path: str) -> float:
        return 10.0 if path == "first.mp4" else 20.0

    async def fake_copy_segment(input_path: str, output_path: str, *, start: float, duration: float, ffmpeg_path: str):
        calls["copy"].append((input_path, output_path, start, duration))
        return output_path

    async def fake_encode_segment(
        input_path: str,
        output_path: str,
        *,
        start: float,
        duration: float,
        video_params: VideoParams,
        audio_params: AudioParams,
        ffmpeg_path: str,
        hw_encoder: str,
    ):
        calls["encode"].append((input_path, output_path, start, duration))
        return output_path

    async def fake_create_freeze_tail(*args, **kwargs):
        return kwargs.get("output_path") or args[1]

    async def fake_apply_transition(*args, **kwargs):
        return None

    async def fake_concat_videos_copy(input_paths, output_path, ffmpeg_path="ffmpeg", movflags_faststart=True):
        calls["concat"].append(list(input_paths))

    monkeypatch.setattr(ffmpeg_ops, "get_media_duration", fake_get_media_duration)
    monkeypatch.setattr(ffmpeg_ops, "_copy_segment", fake_copy_segment)
    monkeypatch.setattr(ffmpeg_ops, "_encode_segment", fake_encode_segment)
    monkeypatch.setattr(ffmpeg_ops, "_create_freeze_tail", fake_create_freeze_tail)
    monkeypatch.setattr(ffmpeg_ops, "apply_transition", fake_apply_transition)
    monkeypatch.setattr(ffmpeg_ops, "concat_videos_copy", fake_concat_videos_copy)

    asyncio.run(
        ffmpeg_ops.apply_transition_local(
            "first.mp4",
            "second.mp4",
            str(tmp_path / "out.mp4"),
            "dissolve",
            0.5,
            9.5,
            VideoParams(),
            AudioParams(),
            wait_padding=1.0,
            hw_encoder="cpu",
            consume_next_head=True,
        )
    )

    assert any(call[0] == "second.mp4" and call[2] == 0.5 for call in calls["copy"])
    assert calls["encode"] == [("second.mp4", str(tmp_path / "out_head2.mp4"), 0.0, 0.5)]
    assert calls["concat"]
