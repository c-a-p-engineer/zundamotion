from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zundamotion.components.script.resolver import resolve_script
from zundamotion.exceptions import ValidationError


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_scenes_include_inline_expansion(tmp_path):
    parts = tmp_path / "parts"
    parts.mkdir()
    _write_yaml(
        parts / "intro.yaml",
        {"scenes": [{"id": "intro", "lines": [{"text": "start"}]}]},
    )
    _write_yaml(
        parts / "body.yaml",
        {"scenes": [{"id": "body", "lines": [{"text": "body"}]}]},
    )
    entry = tmp_path / "entry.yaml"
    _write_yaml(
        entry,
        {"scenes": [{"include": "parts/intro.yaml"}, {"include": "parts/body.yaml"}]},
    )

    resolved = resolve_script(entry)
    scenes = resolved.data["scenes"]
    assert len(scenes) == 2
    assert scenes[0]["id"] == "intro"
    assert scenes[1]["id"] == "body"


def test_non_scene_defaults_include_deep_merge(tmp_path):
    presets = tmp_path / "presets"
    presets.mkdir()
    _write_yaml(
        presets / "base.yaml",
        {"subtitle": {"max_lines": 3, "font_color": "white"}, "characters": {"a": {"speaker_id": 1}}},
    )
    _write_yaml(
        presets / "shorts.yaml",
        {"subtitle": {"max_lines": 2}},
    )
    entry = tmp_path / "entry.yaml"
    _write_yaml(
        entry,
        {
            "defaults": {
                "include": ["presets/base.yaml", "presets/shorts.yaml"],
                "subtitle": {"max_lines": 1},
            }
        },
    )

    resolved = resolve_script(entry)
    defaults = resolved.data["defaults"]
    assert defaults["subtitle"]["max_lines"] == 1
    assert defaults["subtitle"]["font_color"] == "white"
    assert defaults["characters"]["a"]["speaker_id"] == 1


def test_list_replacement_behavior(tmp_path):
    presets = tmp_path / "presets"
    presets.mkdir()
    _write_yaml(presets / "base.yaml", {"voices": ["a", "b"]})
    entry = tmp_path / "entry.yaml"
    _write_yaml(
        entry,
        {"defaults": {"include": "presets/base.yaml", "voices": ["c"]}},
    )

    resolved = resolve_script(entry)
    assert resolved.data["defaults"]["voices"] == ["c"]


def test_vars_substitution_success(tmp_path):
    parts = tmp_path / "parts"
    parts.mkdir()
    _write_yaml(
        parts / "intro.yaml",
        {"scenes": [{"id": "intro", "lines": [{"text": "EP${EP}"}]}]},
    )
    entry = tmp_path / "entry.yaml"
    _write_yaml(
        entry,
        {
            "vars": {"EP": 12, "TITLE": "S3 consistency"},
            "meta": {"title": "${TITLE}"},
            "scenes": [{"include": "parts/intro.yaml"}],
        },
    )

    resolved = resolve_script(entry)
    assert resolved.data["meta"]["title"] == "S3 consistency"
    assert resolved.data["scenes"][0]["lines"][0]["text"] == "EP12"


def test_vars_undefined_raises(tmp_path):
    entry = tmp_path / "entry.yaml"
    _write_yaml(entry, {"meta": {"title": "${MISSING}"}, "scenes": []})

    with pytest.raises(ValidationError, match="Undefined variable"):
        resolve_script(entry)


def test_include_cycle_detection(tmp_path):
    a = tmp_path / "a.yaml"
    b = tmp_path / "b.yaml"
    _write_yaml(a, {"scenes": [{"include": "b.yaml"}]})
    _write_yaml(b, {"scenes": [{"include": "a.yaml"}]})

    with pytest.raises(ValidationError, match="Include cycle detected"):
        resolve_script(a)


def test_transition_annotation_at_include_boundary(tmp_path):
    parts = tmp_path / "parts"
    parts.mkdir()
    _write_yaml(
        parts / "body.yaml",
        {"scenes": [{"id": "body", "lines": [{"text": "next"}]}]},
    )
    entry = tmp_path / "entry.yaml"
    _write_yaml(
        entry,
        {
            "scenes": [
                {"id": "intro", "lines": [{"text": "start"}]},
                {
                    "include": "parts/body.yaml",
                    "transition": {"video": "fade", "duration": 0.25},
                },
            ]
        },
    )

    resolved = resolve_script(entry)
    transition = resolved.data["scenes"][0]["transition"]
    assert transition["type"] == "fade"
    assert transition["duration"] == 0.25


def test_markdown_frontmatter_to_scenes(tmp_path):
    script = tmp_path / "script.md"
    script.write_text(
        """---
meta:
  title: Markdown Demo
video:
  width: 720
  height: 1280
bg: assets/bg/room.png
defaults:
  characters:
    copetan:
      speaker_id: 3
      style: smile
---
# Markdown台本
ずんだモーション向けの
制限Markdown仕様です

copetan: 今日は台本形式を定義します。
ナレーション: 次のセリフです。
""",
        encoding="utf-8",
    )

    resolved = resolve_script(script)
    scenes = resolved.data["scenes"]
    assert len(scenes) == 1
    scene = scenes[0]
    assert scene["id"] == "markdown-main"
    assert scene["bg"] == "assets/bg/room.png"
    assert Path(scene["lines"][0]["image_layers"][0]["show"]["path"]).exists()
    assert scene["lines"][1]["speaker_name"] == "copetan"
    assert scene["lines"][1]["characters"][0]["name"] == "copetan"
    assert scene["lines"][2]["speaker_name"] == "ナレーション"
    assert resolved.data["meta"]["title"] == "Markdown Demo"
    assert resolved.data["video"]["width"] == 720


def test_markdown_frontmatter_missing_closing_boundary(tmp_path):
    script = tmp_path / "broken.md"
    script.write_text("""---
meta:
  title: Broken
""", encoding="utf-8")

    with pytest.raises(ValidationError, match="closing boundary"):
        resolve_script(script)


def test_markdown_frontmatter_with_scenes_is_rejected(tmp_path):
    script = tmp_path / "entry.md"
    script.write_text(
        """---
bg: assets/bg/room.png
scenes:
  - id: legacy
---
copetan: 本文
""",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="does not support 'scenes'"):
        resolve_script(script)


def test_markdown_dialogue_requires_speaker_prefix(tmp_path):
    script = tmp_path / "entry.md"
    script.write_text(
        """---
meta:
  title: broken
bg: assets/bg/room.png
---
# 台本
話者プレフィックスなし
""",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="at least one dialogue"):
        resolve_script(script)


def test_markdown_consecutive_dialogues_do_not_switch_panel(tmp_path):
    script = tmp_path / "entry.md"
    script.write_text(
        """---
bg: assets/bg/room.png
---
# 見出し
説明文

copetan: 1行目
engy: 2行目
""",
        encoding="utf-8",
    )

    resolved = resolve_script(script)
    lines = resolved.data["scenes"][0]["lines"]
    image_layer_lines = [line for line in lines if "image_layers" in line]
    text_lines = [line for line in lines if "text" in line]
    assert len(image_layer_lines) == 1
    assert len(text_lines) == 2
