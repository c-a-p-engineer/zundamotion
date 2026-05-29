from __future__ import annotations

from zundamotion.utils.perf_stats import PerfStats


def test_perf_stats_to_dict_keeps_existing_metrics_and_adds_p0_fields() -> None:
    perf = PerfStats()
    perf.incr("ffmpeg_calls", 3)
    perf.incr("ffprobe_calls", 4)
    perf.incr("ffprobe_duration_calls", 3)
    perf.incr("ffprobe_other_calls", 1)
    perf.incr("subtitle_chunks", 2)
    perf.incr("subtitle_png", 7)
    perf.add_ms("subtitle_burn_ms", 3456.7)
    perf.record_av_warning(
        {
            "run_id": perf.run_id,
            "phase": "FinalizePhase",
            "operation": "transition_boundary",
            "scene_id": "demo",
            "transition_index": 2,
            "type": "non_monotonic_dts",
            "input_paths": ["a.mp4", "b.mp4"],
            "output_path": "out.mp4",
            "message": "Non-monotonic DTS in output stream",
        }
    )
    perf.record_subtitle_burn_chunk(
        scene_id="scene_a",
        chunk_index=0,
        chunk_count=2,
        subtitle_count=4,
        input_video_duration=12.3,
        burn_duration_ms=2100.0,
        output_path="scene_a_chunk0.mp4",
        start_time=0.0,
        end_time=12.3,
    )
    perf.record_subtitle_burn_chunk(
        scene_id="scene_b",
        chunk_index=1,
        chunk_count=2,
        subtitle_count=3,
        input_video_duration=8.0,
        burn_duration_ms=3200.0,
        output_path="scene_b_chunk1.mp4",
        start_time=12.3,
        end_time=20.3,
    )
    perf.record_ffprobe_call(
        kind="duration",
        caller="transition_input_probe",
        path="a.mp4",
        elapsed_ms=12.4,
    )
    perf.record_ffprobe_call(
        kind="duration",
        caller="transition_input_probe",
        path="a.mp4",
        elapsed_ms=11.6,
    )
    perf.record_ffprobe_call(
        kind="other",
        caller="line_clip_duration",
        path="b.mp4",
        elapsed_ms=7.0,
    )
    perf.record_ffprobe_call(
        kind="duration",
        caller="transition_input_probe",
        path="a.mp4",
        elapsed_ms=0.0,
        cache_hit=True,
    )

    data = perf.to_dict()

    assert data["ffmpeg_calls"] == 3
    assert data["ffprobe_calls"] == 4
    assert data["run_id"] == perf.run_id
    assert data["av_warnings"]["total"] == 1
    assert data["av_warnings"]["by_type"]["non_monotonic_dts"] == 1
    assert data["subtitle_burn"]["chunk_count"] == 2
    assert data["subtitle_burn"]["subtitle_png"] == 7
    assert data["subtitle_burn"]["top_chunks"][0]["scene_id"] == "scene_b"
    assert data["ffprobe"]["by_kind"]["duration"] == 3
    assert data["ffprobe"]["by_caller"]["transition_input_probe"] == 2
    assert data["ffprobe"]["top_paths"][0]["path"] == "a.mp4"
    assert data["ffprobe"]["top_callers"][0]["caller"] == "transition_input_probe"
    assert data["ffprobe"]["cache_hits_by_caller"]["transition_input_probe"] == 1
