import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace

import zundamotion.components.pipeline_phases.video_phase.scene_fast_path_executor as executor_module
from zundamotion.components.pipeline_phases.video_phase.scene_fast_path_executor import (
    SceneFastPathExecutorMixin,
)
from zundamotion.components.pipeline_phases.video_phase.scene_fast_path_graph import (
    SceneFastPathGraphMixin,
)


class _GraphHarness(SceneFastPathGraphMixin):
    def __init__(self, temp_dir: Path) -> None:
        self.temp_dir = temp_dir
        self.hw_kind = "nvenc"
        self.video_params = SimpleNamespace(
            width=1280,
            height=720,
            fps=30,
            to_ffmpeg_opts=lambda _hw: ["-c:v", "h264_nvenc"],
        )
        self.audio_params = SimpleNamespace(
            sample_rate=48000,
            to_ffmpeg_opts=lambda: ["-c:a", "aac"],
        )
        self.video_renderer = SimpleNamespace(
            ffmpeg_path="ffmpeg",
            ffmpeg_thread_flags=lambda: ["-threads", "0"],
            scale_flags="lanczos",
            apply_fps_filter=True,
            subtitle_gen=SimpleNamespace(),
        )

    def _compute_global_char_position(self, _state, *, start_time, end_time):
        assert start_time == 0.0
        assert end_time == 1.0
        return {
            "x_expr": "10",
            "y_expr": "20",
            "fade_filters": [],
            "scale_dynamic": False,
            "scale_expr": "1.0",
        }


def test_fast_path_graph_keeps_timing_audio_and_mapping_contract(tmp_path: Path) -> None:
    bg = tmp_path / "bg.png"
    char = tmp_path / "char.png"
    bg.write_bytes(b"bg")
    char.write_bytes(b"char")
    harness = _GraphHarness(tmp_path)
    plan = {
        "first_bg_path": bg,
        "base_layout": {
            "fit": "stretch",
            "fill_color": "black",
            "anchor": "middle_center",
            "position": {"x": "0", "y": "0"},
        },
        "background_changes": [],
        "character_intervals": [
            {
                "state": {
                    "image_path": char,
                    "scale": 1.0,
                    "source_width": 100,
                    "source_height": 200,
                    "anchor": "bottom_center",
                    "move": None,
                },
                "start": 0.0,
                "end": 1.0,
            }
        ],
        "face_overlays": [],
        "subtitle_entries": [],
        "audio_specs": [],
    }

    cmd = harness._build_simple_scene_fast_command(
        scene_id="demo",
        scene_duration=1.0,
        output_path=tmp_path / "out.mp4",
        plan=plan,
    )

    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "trim=duration=1.000[bg_base]" in graph
    assert "enable='between(t,0.000,1.000)'" in graph
    assert "anullsrc=channel_layout=stereo:sample_rate=48000" in cmd
    assert "aresample=async=1:first_pts=0" in graph
    assert cmd.count("-map") == 2
    assert "[scene_fast_video_out]" in cmd
    assert "[scene_fast_audio_out]" in cmd
    assert cmd[-3:] == ["-t", "1.000", str(tmp_path / "out.mp4")]


def test_fast_path_executor_preserves_ffmpeg_failure_fallback(tmp_path: Path, monkeypatch) -> None:
    class _ExecutorHarness(SceneFastPathExecutorMixin):
        scene = {"lines": [{}]}
        temp_dir = tmp_path
        cache_manager = SimpleNamespace(
            cache_file=lambda **_kwargs: (_ for _ in ()).throw(
                AssertionError("failed fast path must not be cached")
            )
        )

        def _build_simple_scene_fast_plan(self, **_kwargs):
            return {"plan": True}

        def _build_simple_scene_fast_command(self, **_kwargs):
            return ["ffmpeg", "-version"]

    async def _fail(_cmd):
        raise subprocess.CalledProcessError(1, ["ffmpeg"], stderr="boom")

    monkeypatch.setattr(executor_module, "_run_ffmpeg_async", _fail)
    result = asyncio.run(
        _ExecutorHarness()._render_simple_scene_fast(
            scene_id="demo",
            bg_default="bg.png",
            scene_duration=1.0,
            start_time_by_idx={1: 0.0},
            scene_hash_data={"scene": "demo"},
        )
    )
    assert result is None
