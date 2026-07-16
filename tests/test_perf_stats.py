from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

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


def _line_item(index: int, cache_status: str = "miss") -> dict:
    return {
        "scene_id": f"scene_{index % 4}",
        "line_index": index + 1,
        "clip_id": f"clip_{index}",
        "duration_ms": float(index + 1) * 10.0,
        "cache_status": cache_status,
        "worker_id": f"worker-{index % 3}",
        "render_path": f"clip_{index}.mp4",
        "has_subtitle": True,
        "has_face_overlay": index % 2 == 0,
        "has_move": False,
        "has_effect": False,
        "cache_lookup_ms": 1.0,
        "render_ms": 0.0 if cache_status == "hit" else float(index + 1) * 8.0,
        "prepare_ms": 1.0,
        "cache_store_ms": 1.0 if cache_status == "miss" else 0.0,
    }


def test_line_clip_summary_records_single_worker_nonzero_values() -> None:
    perf = PerfStats()
    perf.record_line_clip(_line_item(0))

    data = perf.to_dict()

    assert data["video_line_clip_ms"] == 10.0
    assert data["line_clip_count"] == 1
    assert data["line_clip_render_ms"] == 8.0
    assert data["line_clip"]["items"][0]["clip_id"] == "clip_0"


def test_line_clip_summary_is_thread_safe_for_44_parallel_records() -> None:
    perf = PerfStats()
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(
            executor.map(
                perf.record_line_clip,
                [_line_item(index, "hit" if index % 3 == 0 else "miss") for index in range(44)],
            )
        )

    summary = perf.to_dict()["line_clip"]

    assert summary["line_clip_count"] == 44
    assert summary["line_clip_cache_hit_count"] == 15
    assert summary["line_clip_cache_miss_count"] == 29
    assert summary["line_clip_total_ms"] > 0
    assert len(summary["slowest"]) == 10
    assert summary["slowest"][0]["clip_id"] == "clip_43"
