"""Apply the line metrics and auto-tune extraction once."""

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
    text = replace_once(text, "import asyncio\n", "", label="asyncio import")

    process_start = text.index("        async def process_one(\n")
    metrics_start = text.index(
        "            total_ms = (\n",
        process_start,
    )
    return_line = text.index(
        "            return clip_path\n",
        metrics_start,
    )
    replacement = """            self._record_talk_line_metrics(
                scene_id=scene_id,
                context=context,
                plan=talk_plan,
                outcome=render_outcome,
                line_total_started=line_total_started,
            )
"""
    text = text[:metrics_start] + replacement + text[return_line:]

    autotune_start = text.index(
        "        # After first scene (or once enough samples), auto-tune for subsequent scenes\n"
    )
    aggregation_start = text.index(
        "        # 順序維持で集約\n",
        autotune_start,
    )
    text = (
        text[:autotune_start]
        + "        await self._maybe_retune_line_workers()\n\n"
        + text[aggregation_start:]
    )

    if "perf_stats.record_line_clip(\n" in text or "[AutoTune]" in text:
        raise RuntimeError("legacy inline line metrics or auto-tune remains")
    if "perf_stats.record_line_clips_skipped_by_scene_cache" not in text:
        raise RuntimeError("unrelated scene cache metric was removed")
    if len(text.splitlines()) >= 500:
        raise RuntimeError("scene_standard_renderer.py did not shrink below 500 lines")
    path.write_text(text, encoding="utf-8")


def patch_scene_renderer() -> None:
    path = VIDEO_PHASE / "scene_renderer.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from .scene_line_executor import SceneLineExecutorMixin\n",
        "from .scene_line_executor import SceneLineExecutorMixin\n"
        "from .scene_line_metrics import SceneLineMetricsMixin\n",
        label="line metrics import",
    )
    text = replace_once(
        text,
        """    SceneLineContextMixin,
    SceneLineExecutorMixin,
    SceneRunBasePlanMixin,
""",
        """    SceneLineContextMixin,
    SceneLineExecutorMixin,
    SceneLineMetricsMixin,
    SceneRunBasePlanMixin,
""",
        label="line metrics MRO",
    )
    path.write_text(text, encoding="utf-8")


def patch_module_split_test() -> None:
    path = ROOT / "tests/test_scene_renderer_module_split.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '        "_execute_scene_lines": "scene_line_executor",\n',
        '        "_execute_scene_lines": "scene_line_executor",\n'
        '        "_record_talk_line_metrics": "scene_line_metrics",\n'
        '        "_maybe_retune_line_workers": "scene_line_metrics",\n',
        label="module split line metrics",
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_standard_renderer()
    patch_scene_renderer()
    patch_module_split_test()


if __name__ == "__main__":
    main()
