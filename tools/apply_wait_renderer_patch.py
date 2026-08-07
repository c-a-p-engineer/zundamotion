"""Apply the wait renderer extraction to large orchestration files once."""

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
    process_start = text.index(
        "        async def process_one(idx: int, line: Dict[str, Any]):"
    )
    start = text.index('                if context.line_type == "wait":', process_start)
    end = text.index("                # Talk step", start)
    replacement = """                if context.line_type == "wait":
                    results[idx - 1] = await self._render_wait_line(context)
                    return

"""
    text = text[:start] + replacement + text[end:]
    if len(text.splitlines()) >= 800:
        raise RuntimeError("scene_standard_renderer.py did not shrink below 800 lines")
    if "wait_cache_data =" in text or "wait_creator_func" in text:
        raise RuntimeError("legacy inline wait renderer remains")
    path.write_text(text, encoding="utf-8")


def patch_scene_renderer() -> None:
    path = VIDEO_PHASE / "scene_renderer.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from .scene_timing import SceneTimingMixin\n",
        "from .scene_timing import SceneTimingMixin\n"
        "from .scene_wait_renderer import SceneWaitRendererMixin\n",
        label="wait renderer import",
    )
    text = replace_once(
        text,
        """    SceneRunBaseRendererMixin,
    SceneTimingMixin,
    SceneStandardRendererMixin,
""",
        """    SceneRunBaseRendererMixin,
    SceneTimingMixin,
    SceneWaitRendererMixin,
    SceneStandardRendererMixin,
""",
        label="wait renderer MRO",
    )
    path.write_text(text, encoding="utf-8")


def patch_module_split_test() -> None:
    path = ROOT / "tests/test_scene_renderer_module_split.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '        "_build_scene_line_context": "scene_line_context",\n',
        '        "_build_scene_line_context": "scene_line_context",\n'
        '        "_render_wait_line": "scene_wait_renderer",\n',
        label="module split wait renderer",
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_standard_renderer()
    patch_scene_renderer()
    patch_module_split_test()


if __name__ == "__main__":
    main()
