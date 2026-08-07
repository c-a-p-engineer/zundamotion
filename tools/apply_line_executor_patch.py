"""Apply the bounded line executor extraction once."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIDEO_PHASE = ROOT / "zundamotion/components/pipeline_phases/video_phase"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_standard_renderer() -> None:
    path = VIDEO_PHASE / "scene_standard_renderer.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        """        # 並列レンダリング用のタスクを構築
        import asyncio

        # If auto-tune has retuned clip_workers, new sem will reflect it
        sem = asyncio.Semaphore(self.phase.clip_workers)
        results: List[Optional[Path]] = [None] * len(lines)

""",
        """        # 行処理本体。並列度・順序・cancelはSceneLineExecutorが管理する。
""",
        label="legacy semaphore prelude",
    )

    function_start = text.index(
        "        async def process_one(idx: int, line: Dict[str, Any]):"
    )
    body_start = text.index("\n", function_start) + 1
    task_start = text.index(
        "        tasks = [process_one(idx, line) for idx, line in lines]",
        body_start,
    )
    body = text[body_start:task_start]
    with_line = "            async with sem:\n"
    if not body.startswith(with_line):
        raise RuntimeError("process_one no longer starts with the legacy semaphore")
    body = body[len(with_line):]
    dedented_lines = []
    for line in body.splitlines(keepends=True):
        if line.strip():
            if not line.startswith("    "):
                raise RuntimeError(f"cannot dedent process_one line: {line!r}")
            line = line[4:]
        dedented_lines.append(line)
    body = "".join(dedented_lines)
    body = replace_once(
        body,
        """                results[idx - 1] = None
                return
""",
        """                return None
""",
        label="image-layer result",
    )
    body = replace_once(
        body,
        """                results[idx - 1] = await self._render_wait_line(context)
                return
""",
        """                return await self._render_wait_line(context)
""",
        label="wait result",
    )
    body = replace_once(
        body,
        "            results[idx - 1] = clip_path\n\n",
        "            return clip_path\n\n",
        label="talk result",
    )
    replacement_header = (
        "        async def process_one(\n"
        "            idx: int, line: Dict[str, Any]\n"
        "        ) -> Optional[Path]:\n"
    )
    header_end = body_start
    text = text[:function_start] + replacement_header + body + text[task_start:]

    text = replace_once(
        text,
        """        tasks = [process_one(idx, line) for idx, line in lines]
        # 並列実行
        await asyncio.gather(*tasks)

""",
        """        results = await self._execute_scene_lines(
            lines,
            process_one,
            max_workers=self.phase.clip_workers,
            scene_id=scene_id,
        )

""",
        label="legacy gather",
    )
    if "async with sem" in text or "asyncio.gather(*tasks)" in text:
        raise RuntimeError("legacy line executor remains")
    if len(text.splitlines()) >= 630:
        raise RuntimeError("scene_standard_renderer.py did not shrink below 630 lines")
    path.write_text(text, encoding="utf-8")


def patch_scene_renderer() -> None:
    path = VIDEO_PHASE / "scene_renderer.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from .scene_line_context import SceneLineContextMixin\n",
        "from .scene_line_context import SceneLineContextMixin\n"
        "from .scene_line_executor import SceneLineExecutorMixin\n",
        label="line executor import",
    )
    text = replace_once(
        text,
        """    SceneBaseRendererMixin,
    SceneLineContextMixin,
    SceneRunBasePlanMixin,
""",
        """    SceneBaseRendererMixin,
    SceneLineContextMixin,
    SceneLineExecutorMixin,
    SceneRunBasePlanMixin,
""",
        label="line executor MRO",
    )
    path.write_text(text, encoding="utf-8")


def patch_module_split_test() -> None:
    path = ROOT / "tests/test_scene_renderer_module_split.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '        "_build_scene_line_context": "scene_line_context",\n',
        '        "_build_scene_line_context": "scene_line_context",\n'
        '        "_execute_scene_lines": "scene_line_executor",\n',
        label="module split line executor",
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_standard_renderer()
    patch_scene_renderer()
    patch_module_split_test()


if __name__ == "__main__":
    main()
