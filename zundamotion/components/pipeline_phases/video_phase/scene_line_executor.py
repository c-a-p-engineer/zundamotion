"""Bounded, ordered, fail-fast execution for standard scene lines."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Iterable, Optional, Sequence, TypeVar

from ....utils.logger import logger


LineT = TypeVar("LineT")
ResultT = TypeVar("ResultT")
LineWorker = Callable[[int, LineT], Awaitable[ResultT]]


class SceneLineExecutorMixin:
    """Execute line workers with a bounded semaphore and deterministic order."""

    async def _execute_scene_lines(
        self,
        lines: Sequence[tuple[int, LineT]] | Iterable[tuple[int, LineT]],
        worker: LineWorker[LineT, ResultT],
        *,
        max_workers: int,
        scene_id: Optional[str] = None,
    ) -> list[ResultT]:
        ordered_lines = list(lines)
        if not ordered_lines:
            return []

        concurrency = max(1, int(max_workers or 1))
        semaphore = asyncio.Semaphore(concurrency)
        results: list[Any] = [None] * len(ordered_lines)

        async def run_one(position: int, line_index: int, line: LineT) -> None:
            async with semaphore:
                results[position] = await worker(line_index, line)

        tasks = [
            asyncio.create_task(
                run_one(position, line_index, line),
                name=f"scene-line-{scene_id or 'unknown'}-{line_index}",
            )
            for position, (line_index, line) in enumerate(ordered_lines)
        ]
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            pending = [task for task in tasks if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            logger.warning(
                "[LineExecutor] scene=%s status=failed workers=%d total=%d cancelled=%d",
                scene_id or "unknown",
                concurrency,
                len(tasks),
                len(pending),
            )
            raise

        logger.info(
            "[LineExecutor] scene=%s status=success workers=%d total=%d",
            scene_id or "unknown",
            concurrency,
            len(tasks),
        )
        return list(results)
