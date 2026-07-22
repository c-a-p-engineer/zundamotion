from __future__ import annotations

from zundamotion.components.subtitles import png as subtitle_png
from zundamotion.components.subtitles.lifecycle import shutdown_subtitle_executor


class TerminableExecutor:
    def __init__(self) -> None:
        self.terminate_calls = 0

    def terminate_workers(self) -> None:
        self.terminate_calls += 1

    def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
        raise AssertionError("shutdown fallback must not be used when terminate_workers exists")


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, bool]] = []

    def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
        self.calls.append({"wait": wait, "cancel_futures": cancel_futures})


def test_shutdown_subtitle_executor_terminates_python314_workers(monkeypatch) -> None:
    executor = TerminableExecutor()
    monkeypatch.setattr(subtitle_png, "_SUBTITLE_EXECUTOR", executor)
    monkeypatch.setattr(subtitle_png, "_SUBTITLE_EXECUTOR_WORKERS", 2)

    shutdown_subtitle_executor()

    assert executor.terminate_calls == 1
    assert subtitle_png._SUBTITLE_EXECUTOR is None
    assert subtitle_png._SUBTITLE_EXECUTOR_WORKERS is None


def test_shutdown_subtitle_executor_waits_on_older_runtime(monkeypatch) -> None:
    executor = RecordingExecutor()
    monkeypatch.setattr(subtitle_png, "_SUBTITLE_EXECUTOR", executor)
    monkeypatch.setattr(subtitle_png, "_SUBTITLE_EXECUTOR_WORKERS", 2)

    shutdown_subtitle_executor()

    assert executor.calls == [{"wait": True, "cancel_futures": True}]
    assert subtitle_png._SUBTITLE_EXECUTOR is None
    assert subtitle_png._SUBTITLE_EXECUTOR_WORKERS is None


def test_shutdown_subtitle_executor_is_idempotent(monkeypatch) -> None:
    monkeypatch.setattr(subtitle_png, "_SUBTITLE_EXECUTOR", None)
    monkeypatch.setattr(subtitle_png, "_SUBTITLE_EXECUTOR_WORKERS", None)

    shutdown_subtitle_executor()

    assert subtitle_png._SUBTITLE_EXECUTOR is None
    assert subtitle_png._SUBTITLE_EXECUTOR_WORKERS is None
