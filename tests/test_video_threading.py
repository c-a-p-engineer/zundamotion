from __future__ import annotations

from zundamotion.components.video import threading as video_threading


def _flag_value(flags: list[str], name: str) -> str:
    index = flags.index(name)
    return flags[index + 1]


def test_cpu_auto_keeps_clip_parallelism_but_serializes_filter_complex(monkeypatch) -> None:
    monkeypatch.setattr(video_threading.multiprocessing, "cpu_count", lambda: 4)
    monkeypatch.setattr(video_threading, "get_hw_filter_mode", lambda: "cpu")
    monkeypatch.delenv("FFMPEG_FILTER_THREADS", raising=False)
    monkeypatch.delenv("FFMPEG_FILTER_COMPLEX_THREADS", raising=False)
    monkeypatch.delenv("FFMPEG_FILTER_THREADS_CAP", raising=False)
    monkeypatch.delenv("FFMPEG_FILTER_COMPLEX_THREADS_CAP", raising=False)

    flags = video_threading.build_ffmpeg_thread_flags(
        jobs="auto",
        clip_workers=2,
        hw_kind=None,
    )

    assert _flag_value(flags, "-threads") == "2"
    assert _flag_value(flags, "-filter_threads") == "2"
    assert _flag_value(flags, "-filter_complex_threads") == "1"


def test_cpu_filter_complex_thread_override_is_preserved(monkeypatch) -> None:
    monkeypatch.setattr(video_threading.multiprocessing, "cpu_count", lambda: 8)
    monkeypatch.setattr(video_threading, "get_hw_filter_mode", lambda: "cpu")
    monkeypatch.setenv("FFMPEG_FILTER_COMPLEX_THREADS", "3")

    flags = video_threading.build_ffmpeg_thread_flags(
        jobs="auto",
        clip_workers=2,
        hw_kind=None,
    )

    assert _flag_value(flags, "-filter_complex_threads") == "3"


def test_gpu_filter_path_keeps_existing_thread_policy(monkeypatch) -> None:
    monkeypatch.setattr(video_threading.multiprocessing, "cpu_count", lambda: 8)
    monkeypatch.setattr(video_threading, "get_hw_filter_mode", lambda: "cuda")
    monkeypatch.delenv("FFMPEG_FILTER_COMPLEX_THREADS", raising=False)

    flags = video_threading.build_ffmpeg_thread_flags(
        jobs="auto",
        clip_workers=2,
        hw_kind="nvenc",
    )

    assert _flag_value(flags, "-filter_complex_threads") == "1"
