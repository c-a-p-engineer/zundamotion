"""Apply the Issue #33 Run Base runtime refactor once.

This temporary script exists only because the connected GitHub contents API
cannot patch a section of a large file. It validates every expected source
fragment before replacing it and is deleted after the generated commit lands.
"""

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

    start_marker = "        # 連続行で静的レイヤが不変な“ラン”のベース"
    end_marker = "        # 先に各行の開始時刻を決定"
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    replacement = """        run_bases = await self._prepare_run_bases(
            scene_id=scene_id,
            background=str(bg_image),
            is_background_video=is_bg_video,
            scene_base_path=scene_base_path,
            scene_copy=scene_cp,
            has_line_background_override=has_line_bg_override,
        )

"""
    text = text[:start] + replacement + text[end:]

    text = replace_once(
        text,
        """                run_base = None
                for rb in run_bases or []:
                    if rb[\"start\"] <= idx <= rb[\"end\"]:
                        run_base = rb
                        break
""",
        """                run_base = self._find_run_base(run_bases, idx)
""",
        label="run-base lookup",
    )
    text = replace_once(
        text,
        'Path(run_base["path"]).exists()',
        "run_base.path.exists()",
        label="run-base path existence",
    )
    text = replace_once(
        text,
        """                    # ラン内でのオフセットを算出（キャッシュ）
                    if run_base.get(\"offsets\") is None:
                        offs = {}
                        acc = 0.0
                        for li in range(run_base[\"start\"], run_base[\"end\"] + 1):
                            offs[li] = acc
                            lid2 = f\"{scene_id}_{li}\"
                            acc += float(line_data_map[lid2][\"duration\"])  # type: ignore
                        run_base[\"offsets\"] = offs
""",
        "",
        label="legacy offset calculation",
    )
    text = replace_once(
        text,
        'str(run_base["path"])',
        "str(run_base.path)",
        label="run-base path",
    )
    text = replace_once(
        text,
        'float(run_base["offsets"][idx])',
        "float(run_base.offsets[idx])",
        label="run-base offset",
    )
    text = replace_once(
        text,
        '(run_base and run_base.get("char_keys"))',
        "(run_base and run_base.character_keys)",
        label="run-base character condition",
    )
    text = replace_once(
        text,
        'entry_keys & run_base.get("char_keys", set())',
        "entry_keys & run_base.character_keys",
        label="run-base character keys",
    )
    text = replace_once(
        text,
        '(run_base and run_base.get("has_insert_image"))',
        "(run_base and run_base.has_insert_image)",
        label="run-base insert condition",
    )

    if "talk_lines2" in text or "Run-base detection skipped" in text:
        raise RuntimeError("legacy inline Run Base implementation remains")
    if len(text.splitlines()) >= 950:
        raise RuntimeError("scene_standard_renderer.py did not shrink as expected")
    path.write_text(text, encoding="utf-8")


def patch_scene_renderer() -> None:
    path = VIDEO_PHASE / "scene_renderer.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from .scene_run_base_safety import SceneRunBaseSafetyMixin\n",
        "from .scene_run_base_renderer import SceneRunBaseRendererMixin\n",
        label="Run Base renderer import",
    )
    text = replace_once(
        text,
        """    SceneRunBasePlanMixin,
    SceneTimingMixin,
    SceneRunBaseSafetyMixin,
    SceneStandardRendererMixin,
""",
        """    SceneRunBasePlanMixin,
    SceneRunBaseRendererMixin,
    SceneTimingMixin,
    SceneStandardRendererMixin,
""",
        label="Run Base renderer MRO",
    )
    text = replace_once(
        text,
        """        effective_scene_cp = self._effective_scene_copy_for_run_base_safety(
            scene,
            scene_cp,
        )
        return await self._render_scene_internal(
            scene,
            effective_scene_cp,
            bg_default,
            scene_hash_data,
        )
""",
        """        return await self._render_scene_internal(
            scene,
            scene_cp,
            bg_default,
            scene_hash_data,
        )
""",
        label="Run Base safety facade",
    )
    path.write_text(text, encoding="utf-8")


def patch_module_split_test() -> None:
    path = ROOT / "tests/test_scene_renderer_module_split.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '        "_prepare_scene_base": "scene_base_renderer",\n'
        '        "_build_scene_timing_plan": "scene_timing",\n',
        '        "_prepare_scene_base": "scene_base_renderer",\n'
        '        "_prepare_run_bases": "scene_run_base_renderer",\n'
        '        "_build_scene_timing_plan": "scene_timing",\n',
        label="module split expectation",
    )
    path.write_text(text, encoding="utf-8")


def remove_temporary_safety_guard() -> None:
    for path in (
        VIDEO_PHASE / "scene_run_base_safety.py",
        ROOT / "tests/test_scene_run_base_safety.py",
    ):
        if not path.exists():
            raise RuntimeError(f"expected safety file is missing: {path}")
        path.unlink()


def main() -> None:
    patch_standard_renderer()
    patch_scene_renderer()
    patch_module_split_test()
    remove_temporary_safety_guard()


if __name__ == "__main__":
    main()
