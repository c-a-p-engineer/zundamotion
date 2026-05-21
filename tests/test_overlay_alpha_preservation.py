"""Ensure overlay filters preserve transparency when effects are applied."""

import asyncio
from pathlib import Path

import zundamotion.components.video.overlays as overlays_module
from zundamotion.components.video.overlays import OverlayMixin
from zundamotion.utils.ffmpeg_params import AudioParams, VideoParams


class _DummyOverlay(OverlayMixin):
    def __init__(self) -> None:
        self.scale_flags = "bicubic"
        self.ffmpeg_path = "ffmpeg"
        self.video_params = VideoParams(width=1080, height=1920, fps=30)
        self.audio_params = AudioParams(sample_rate=48000, channels=2)
        self.hw_kind = None
        self.subtitle_gen = type(
            "SubtitleGen",
            (),
            {"subtitle_config": {}},
        )()

    def _single_job_thread_flags(self):  # type: ignore[override]
        return ["-threads", "1"]

    def _build_effect_filters(self, effects):  # type: ignore[override]
        # Reuse base implementation
        return super()._build_effect_filters(effects)


def test_overlay_chain_keeps_alpha_mask_when_effects_present():
    dummy = _DummyOverlay()

    filters, processed = dummy._build_overlay_filter_parts(  # type: ignore[attr-defined]
        "[1:v]",
        0,
        {
            "opacity": 0.85,
            "effects": [{"type": "blur", "sigma": 2.0}],
            "scale": {"w": 640, "h": 480, "keep_aspect": True},
        },
    )

    assert processed == "[ov0]"
    # First leg ensures split into color/alpha with format before effects
    assert any("split[ov0_c_in][ov0_a_in]" in part for part in filters)
    # Alpha leg must extract and scale the alpha mask only.
    assert any("alphaextract,lut=y='val*0.850000'" in part for part in filters)
    # Final merge should recombine color and preserved alpha
    assert any("alphamerge[ov0]" in part for part in filters)


def test_overlay_blink_is_applied_to_alpha_chain_only():
    dummy = _DummyOverlay()

    filters, _ = dummy._build_overlay_filter_parts(  # type: ignore[attr-defined]
        "[1:v]",
        0,
        {
            "opacity": 0.5,
            "blink": {
                "interval": 0.2,
                "duty": 0.5,
                "min_opacity": 0.0,
                "max_opacity": 1.0,
            },
            "effects": [{"type": "blur", "sigma": 2.0}],
        },
    )

    alpha_filters = [part for part in filters if "[ov0_a_in]" in part]
    color_filters = [part for part in filters if part.startswith("[ov0_c_in]")]

    assert any("lut=y='val*0.500000'" in part for part in alpha_filters)
    assert any("geq=lum=lum(X\\,Y)*if(lt(mod(N\\,6)\\,3)\\,1.000000\\,0.000000)" in part for part in alpha_filters)
    assert not any("mod(N\\," in part for part in color_filters)


def test_overlay_blink_clamps_duty_and_opacity_values():
    dummy = _DummyOverlay()

    filters, _ = dummy._build_overlay_filter_parts(  # type: ignore[attr-defined]
        "[1:v]",
        0,
        {
            "blink": {
                "interval": 0.25,
                "duty": 2.0,
                "min_opacity": -1.0,
                "max_opacity": 3.0,
            },
        },
    )

    alpha_filter = next(part for part in filters if part.startswith("[ov0_a_in]"))
    assert "if(lt(mod(N\\,8)\\,8)\\,1.000000\\,0.000000)" in alpha_filter


def test_overlay_blink_ignores_invalid_interval():
    dummy = _DummyOverlay()

    filters, _ = dummy._build_overlay_filter_parts(  # type: ignore[attr-defined]
        "[1:v]",
        0,
        {"blink": {"interval": 0, "duty": 0.5}},
    )

    alpha_filter = next(part for part in filters if part.startswith("[ov0_a_in]"))
    assert "mod(N\\," not in alpha_filter


def test_subtitle_png_chunks_split_continuous_ranges_by_count():
    subtitles = [
        {"text": str(idx), "start": float(idx), "duration": 0.9, "line_config": {}}
        for idx in range(7)
    ]

    chunks = OverlayMixin._split_subtitle_ranges_for_png(
        subtitles,
        base_duration=10.0,
        gap_threshold=0.20,
        max_subtitles=3,
    )

    assert [len(chunk["subtitles"]) for chunk in chunks] == [3, 3, 1]
    assert chunks[0]["start"] == 0.0
    assert chunks[0]["end"] == 2.9
    assert chunks[1]["start"] == 3.0


def test_subtitle_png_chunks_do_not_split_overlapping_subtitles():
    subtitles = [
        {"text": "a", "start": 0.0, "duration": 2.0, "line_config": {}},
        {"text": "b", "start": 1.0, "duration": 2.0, "line_config": {}},
        {"text": "c", "start": 2.0, "duration": 1.0, "line_config": {}},
    ]

    chunks = OverlayMixin._split_subtitle_ranges_for_png(
        subtitles,
        base_duration=3.0,
        gap_threshold=0.20,
        max_subtitles=1,
    )

    assert len(chunks) == 1
    assert len(chunks[0]["subtitles"]) == 3


def test_auto_subtitle_png_chunk_size_scales_for_long_many_subtitle_scene():
    value = OverlayMixin._auto_subtitle_png_chunk_size(
        90,
        base_duration=534.25,
        cpu_count=12,
    )

    assert value == 15


def test_auto_subtitle_png_chunk_size_accounts_for_dense_continuous_subtitles():
    value = OverlayMixin._auto_subtitle_png_chunk_size(
        149,
        base_duration=975.77,
        cpu_count=12,
        subtitle_density=149 / 975.77,
        gap_duration=120.0,
        longest_zone=420.0,
    )

    assert value == 22


def test_auto_subtitle_png_chunk_size_allows_fewer_chunks_for_sparse_gap_heavy_scene():
    value = OverlayMixin._auto_subtitle_png_chunk_size(
        90,
        base_duration=534.25,
        cpu_count=12,
        subtitle_density=90 / 534.25,
        gap_duration=300.0,
        longest_zone=70.0,
    )

    assert value == 18


def test_explicit_subtitle_png_chunk_size_overrides_auto():
    dummy = _DummyOverlay()
    dummy.subtitle_gen.subtitle_config = {"png_chunk_size": 24}

    assert dummy._subtitle_png_chunk_size([{}] * 90, base_duration=534.25) == 24


def test_subtitle_segment_cut_uses_exact_trim_not_stream_copy(monkeypatch, tmp_path):
    dummy = _DummyOverlay()
    captured = {}

    async def fake_run_ffmpeg(cmd):
        captured["cmd"] = cmd

    monkeypatch.setattr(overlays_module, "_run_ffmpeg", fake_run_ffmpeg)

    asyncio.run(
        dummy._cut_video_segment_exact(
            tmp_path / "base.mp4",
            tmp_path / "segment.mp4",
            start=1.92,
            duration=0.25,
        )
    )

    cmd = captured["cmd"]
    filter_complex = cmd[cmd.index("-filter_complex") + 1]
    assert "trim=start=1.920:duration=0.250" in filter_complex
    assert "atrim=start=1.920:duration=0.250" in filter_complex
    assert "-c" not in cmd
    assert "copy" not in cmd
    assert str(tmp_path / "segment.mp4") == cmd[-1]


def test_subtitle_segment_cut_skips_tiny_segments(monkeypatch, tmp_path):
    dummy = _DummyOverlay()
    called = False

    async def fake_run_ffmpeg(cmd):
        nonlocal called
        called = True

    monkeypatch.setattr(overlays_module, "_run_ffmpeg", fake_run_ffmpeg)

    result = asyncio.run(
        dummy._cut_video_segment_exact(
            tmp_path / "base.mp4",
            tmp_path / "segment.mp4",
            start=40.04,
            duration=0.03,
        )
    )

    assert result is None
    assert called is False
