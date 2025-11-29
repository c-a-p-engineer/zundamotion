from pathlib import Path

import yaml

from zundamotion.components.subtitles.effects import (
    reset_subtitle_effect_registry,
    resolve_subtitle_effects,
)
from zundamotion.components.video.overlay_effects import (
    reset_overlay_effect_registry,
    resolve_overlay_effects,
)
from zundamotion.plugins.loader import PluginLoadResult
from zundamotion.plugins.manager import initialize_plugins
from zundamotion.plugins.schema import PluginMeta, PluginSpec


def _write_plugin(tmpdir: Path, meta: dict, body: str) -> Path:
    tmpdir.mkdir(parents=True, exist_ok=True)
    (tmpdir / "plugin.yaml").write_text(yaml.safe_dump(meta), encoding="utf-8")
    (tmpdir / "plugin.py").write_text(body, encoding="utf-8")
    return tmpdir


def _write_inline_plugin(tmpdir: Path, meta: dict, body: str) -> Path:
    tmpdir.mkdir(parents=True, exist_ok=True)
    inlined_body = f"PLUGIN_META = {meta!r}\n\n{body}"
    (tmpdir / "plugin.py").write_text(inlined_body, encoding="utf-8")
    return tmpdir


def test_overlay_plugin_overrides_builtin(tmp_path: Path):
    reset_overlay_effect_registry()
    reset_subtitle_effect_registry()

    meta = {
        "id": "overlay.override_blur",
        "version": "1.0.0",
        "kind": "overlay",
        "provides": ["blur"],
    }
    body = """
from typing import Dict, Any, List


def builder(params: Dict[str, Any]) -> List[str]:
    return ["custom_blur"]


BUILDERS = {"blur": builder}
"""
    plugin_dir = _write_plugin(tmp_path / "overlay_override", meta, body)

    initialize_plugins(config={"plugins": {"paths": [str(plugin_dir)]}})

    assert resolve_overlay_effects([{"type": "blur"}]) == ["custom_blur"]


def test_overlay_plugin_deny_falls_back_to_builtin(tmp_path: Path):
    reset_overlay_effect_registry()

    meta = {
        "id": "overlay.deny_blur",
        "version": "1.0.0",
        "kind": "overlay",
        "provides": ["blur"],
    }
    body = """
from typing import Dict, Any, List


def builder(params: Dict[str, Any]) -> List[str]:
    return ["should_not_apply"]


BUILDERS = {"blur": builder}
"""
    plugin_dir = _write_plugin(tmp_path / "overlay_deny", meta, body)

    initialize_plugins(
        config={"plugins": {"paths": [str(plugin_dir)]}},
        deny_ids=["overlay.deny_blur"],
    )

    # Falls back to built-in blur builder
    blur_filters = resolve_overlay_effects([{"type": "blur", "sigma": 2}])
    assert blur_filters and blur_filters[0].startswith("gblur=sigma=")


def test_inline_plugin_without_manifest_loads(tmp_path: Path):
    reset_overlay_effect_registry()

    meta = {
        "id": "overlay.inline_blur",
        "version": "1.0.0",
        "kind": "overlay",
        "provides": ["blur"],
    }
    body = """
from typing import Dict, Any, List


def builder(params: Dict[str, Any]) -> List[str]:
    return ["inline_custom_blur"]


BUILDERS = {"blur": builder}
"""
    plugin_dir = _write_inline_plugin(tmp_path / "overlay_inline", meta, body)

    initialize_plugins(
        config={"plugins": {"paths": [str(plugin_dir)], "allow": ["overlay.inline_blur"]}}
    )

    blur_filters = resolve_overlay_effects([{"type": "blur", "sigma": 2}])
    assert blur_filters == ["inline_custom_blur"]


def test_subtitle_plugin_registers_alias(tmp_path: Path):
    reset_subtitle_effect_registry()

    meta = {
        "id": "subtitle.custom_bounce",
        "version": "1.0.0",
        "kind": "subtitle",
        "provides": ["text:bounce_text"],
    }
    body = """
from typing import Any, Dict, Optional
from zundamotion.components.subtitles.effects import SubtitleEffectContext, SubtitleEffectSnippet


def builder(ctx: SubtitleEffectContext, params: Dict[str, Any]) -> Optional[SubtitleEffectSnippet]:
    return SubtitleEffectSnippet(filter_chain=["test"], output_label=ctx.input_label, overlay_kwargs={}, dynamic=False)


BUILDERS = {"text:bounce_text": builder}
ALIASES = {"text:bounce_text": ["bounce_text"]}
"""
    plugin_dir = _write_plugin(tmp_path / "subtitle_bounce", meta, body)

    initialize_plugins(config={"plugins": {"paths": [str(plugin_dir)]}})

    snippet = resolve_subtitle_effects(
        effects=["bounce_text"],
        input_label="in0",
        base_x_expr="x0",
        base_y_expr="y0",
        duration=1.0,
        width=1920,
        height=1080,
        index=0,
    )
    assert snippet is not None
    assert snippet.filter_chain == ["test"]
    reset_subtitle_effect_registry()


def test_overlay_plugin_with_forbidden_import_is_blocked(tmp_path: Path):
    reset_overlay_effect_registry()

    meta = {
        "id": "overlay.unsafe_blur",
        "version": "1.0.0",
        "kind": "overlay",
        "provides": ["blur"],
    }
    body = """
import subprocess
from typing import Dict, Any, List


def builder(params: Dict[str, Any]) -> List[str]:
    return ["unsafe_blur"]


BUILDERS = {"blur": builder}
"""
    plugin_dir = _write_plugin(tmp_path / "overlay_unsafe", meta, body)

    initialize_plugins(config={"plugins": {"paths": [str(plugin_dir)]}})

    blur_filters = resolve_overlay_effects([{"type": "blur", "sigma": 2}])
    assert blur_filters and blur_filters[0].startswith("gblur=")


def test_builtin_blur_preserves_alpha_by_default():
    reset_overlay_effect_registry()

    blur_filters = resolve_overlay_effects([{"type": "blur", "sigma": 5.5}])

    assert blur_filters == ["gblur=sigma=5.5000:planes=7"]


def test_invalid_manifest_is_skipped(tmp_path: Path):
    reset_overlay_effect_registry()
    reset_subtitle_effect_registry()

    meta = {
        "id": "overlay.invalid",
        "version": "1.0.0",
        "kind": "overlay",
        "provides": ["blur"],
        "unknown": True,
    }
    body = """
from typing import Dict, Any, List


def builder(params: Dict[str, Any]) -> List[str]:
    return ["invalid_override"]


BUILDERS = {"blur": builder}
"""

    plugin_dir = _write_plugin(tmp_path / "overlay_invalid", meta, body)
    initialize_plugins(config={"plugins": {"paths": [str(plugin_dir)]}})

    blur_filters = resolve_overlay_effects([{"type": "blur", "sigma": 2}])
    assert blur_filters and blur_filters[0].startswith("gblur=")


def test_builtin_plugins_cached_between_calls(monkeypatch, tmp_path: Path):
    from zundamotion import plugins
    from zundamotion.plugins import loader

    loader._PLUGIN_CACHE.clear()

    meta = PluginMeta(
        plugin_id="overlay.cached_blur",
        version="1.0.0",
        kind="overlay",
        provides=["blur"],
        source="builtin",
        enabled=True,
    )
    spec = PluginSpec(meta=meta, base_path=str(tmp_path), module_path=str(tmp_path / "plugin.py"))

    def fake_discover(roots, allow=None, deny=None):  # type: ignore[override]
        return [spec]

    call_counter = {"loader": 0}

    def fake_load(spec_arg: PluginSpec):  # type: ignore[override]
        call_counter["loader"] += 1
        return PluginLoadResult(
            meta=spec_arg.meta,
            builders={"blur": lambda params: [f"cached_blur:{params.get('sigma', 1)}"]},
            aliases={},
            duration_s=0.0,
            source_path=spec_arg.module_path,
        )

    monkeypatch.setattr(plugins.loader, "discover_plugins", fake_discover)
    monkeypatch.setattr(plugins.loader, "load_plugin_builders", fake_load)

    roots = [tmp_path]
    first = loader.load_plugins_cached(roots, use_cache=True)
    second = loader.load_plugins_cached(roots, use_cache=True)
    uncached = loader.load_plugins_cached(roots, use_cache=False)

    assert call_counter["loader"] == 2  # cache hit prevents re-import once
    assert first == second
    assert uncached[0].builders["blur"]({}) == ["cached_blur:1"]


def test_example_user_simple_shake_presets_load():
    reset_overlay_effect_registry()
    reset_subtitle_effect_registry()

    examples = Path(__file__).resolve().parents[1] / "plugins" / "examples"
    initialize_plugins(config={"plugins": {"paths": [str(examples)]}})

    basic = resolve_overlay_effects([{"type": "shake", "amplitude_deg": 2.0, "frequency_hz": 3.2}])
    assert basic and "rotate=(" in basic[0]

    soft = resolve_overlay_effects([{"type": "soft_shake"}])
    assert soft and any("rotate=" in f for f in soft)

    with_sfx = resolve_overlay_effects([{"type": "shake_fanfare"}])
    assert with_sfx is not None and any("eq=contrast" in f for f in with_sfx)
