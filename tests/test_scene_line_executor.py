from __future__ import annotations

import asyncio

import pytest

from zundamotion.components.pipeline_phases.video_phase.scene_line_executor import (
    SceneLineExecutorMixin,
)


class _Subject(SceneLineExecutorMixin):
    pass


def test_results_follow_input_order_even_when_completion_order_differs() -> None:
    subject = _Subject()

    async def run():
        completion = []

        async def worker(index, delay):
            await asyncio.sleep(delay)
            completion.append(index)
            return f"result-{index}"

        results = await subject._execute_scene_lines(
            [(3, 0.03), (1, 0.01), (2, 0.02)],
            worker,
            max_workers=3,
            scene_id="demo",
        )
        return results, completion

    results, completion = asyncio.run(run())

    assert completion == [1, 2, 3]
    assert results == ["result-3", "result-1", "result-2"]


def test_concurrency_never_exceeds_worker_limit() -> None:
    subject = _Subject()

    async def run():
        active = 0
        maximum = 0
        lock = asyncio.Lock()

        async def worker(index, value):
            nonlocal active, maximum
            async with lock:
                active += 1
                maximum = max(maximum, active)
            await asyncio.sleep(0.01)
            async with lock:
                active -= 1
            return value

        results = await subject._execute_scene_lines(
            [(index, index) for index in range(1, 9)],
            worker,
            max_workers=2,
            scene_id="bounded",
        )
        return results, maximum

    results, maximum = asyncio.run(run())

    assert results == list(range(1, 9))
    assert maximum == 2


def test_zero_or_invalid_worker_count_is_clamped_to_one() -> None:
    subject = _Subject()

    async def run():
        active = 0
        maximum = 0

        async def worker(index, value):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0)
            active -= 1
            return value

        results = await subject._execute_scene_lines(
            [(1, "a"), (2, "b")],
            worker,
            max_workers=0,
        )
        return results, maximum

    results, maximum = asyncio.run(run())

    assert results == ["a", "b"]
    assert maximum == 1


def test_first_failure_cancels_and_awaits_unfinished_tasks() -> None:
    subject = _Subject()

    async def run():
        cancelled = []
        completed = []

        async def worker(index, mode):
            if mode == "fail":
                await asyncio.sleep(0.01)
                raise RuntimeError("line failed")
            try:
                await asyncio.sleep(10)
                completed.append(index)
                return index
            except asyncio.CancelledError:
                cancelled.append(index)
                raise

        with pytest.raises(RuntimeError, match="line failed"):
            await subject._execute_scene_lines(
                [(1, "slow"), (2, "fail"), (3, "slow")],
                worker,
                max_workers=3,
                scene_id="failure",
            )
        await asyncio.sleep(0)
        return cancelled, completed

    cancelled, completed = asyncio.run(run())

    assert sorted(cancelled) == [1, 3]
    assert completed == []


def test_empty_input_returns_empty_without_calling_worker() -> None:
    subject = _Subject()

    async def run():
        called = False

        async def worker(index, value):
            nonlocal called
            called = True
            return value

        results = await subject._execute_scene_lines(
            [],
            worker,
            max_workers=2,
        )
        return results, called

    results, called = asyncio.run(run())

    assert results == []
    assert called is False
