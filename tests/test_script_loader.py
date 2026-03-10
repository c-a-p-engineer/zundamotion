from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zundamotion.components.script.loader import load_script_and_config


def test_voice_layers_inherit_character_defaults(tmp_path):
    default_config_path = tmp_path / "default.yaml"
    default_config_path.write_text(
        yaml.safe_dump(
            {
                "script": {"scenes": []},
                "defaults": {},
            }
        ),
        encoding="utf-8",
    )

    script_path = tmp_path / "script.yaml"
    script_path.write_text(
        yaml.safe_dump(
            {
                "meta": {"title": "test", "version": 3},
                "defaults": {
                    "characters": {
                        "alice": {"speaker_id": 1, "speed": 1.2},
                        "bob": {"speaker_id": 2},
                    }
                },
                "scenes": [
                    {
                        "id": "scene",
                        "bg": str((Path.cwd() / "assets/bg/room.png").resolve()),
                        "lines": [
                            {
                                "text": "合わせて挨拶",
                                "voice_layers": [
                                    {"speaker_name": "alice"},
                                    {"speaker_name": "bob", "speed": 0.9},
                                ],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    config = load_script_and_config(str(script_path), str(default_config_path))
    line = config["script"]["scenes"][0]["lines"][0]

    assert "voice_layers" in line
    voice_layers = line["voice_layers"]
    assert voice_layers[0]["speaker_id"] == 1
    assert voice_layers[0]["speed"] == 1.2
    assert voice_layers[1]["speaker_id"] == 2
    # Explicit overrides on the layer should be preserved
    assert voice_layers[1]["speed"] == 0.9


def test_character_subtitle_defaults_are_merged_into_speaker_lines(tmp_path):
    default_config_path = tmp_path / "default.yaml"
    default_config_path.write_text(
        yaml.safe_dump({"script": {"scenes": []}, "defaults": {}}),
        encoding="utf-8",
    )

    script_path = tmp_path / "script.yaml"
    script_path.write_text(
        yaml.safe_dump(
            {
                "meta": {"title": "test", "version": 3},
                "defaults": {
                    "characters": {
                        "alice": {
                            "speaker_id": 1,
                            "subtitle": {
                                "font_color": "#90EE90",
                                "stroke_color": "#102A43",
                            },
                        }
                    }
                },
                "scenes": [
                    {
                        "id": "scene",
                        "bg": str((Path.cwd() / "assets/bg/room.png").resolve()),
                        "lines": [{"speaker_name": "alice", "text": "字幕色を継承します"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    config = load_script_and_config(str(script_path), str(default_config_path))
    line = config["script"]["scenes"][0]["lines"][0]

    assert line["subtitle"]["font_color"] == "#90EE90"
    assert line["subtitle"]["stroke_color"] == "#102A43"


def test_auto_sound_effect_injected_from_overlay_preset(tmp_path):
    root = Path.cwd()
    default_config_path = tmp_path / "default.yaml"
    default_config_path.write_text(
        yaml.safe_dump(
            {
                "script": {"scenes": []},
                "plugins": {
                    "paths": [str(root / "plugins" / "examples")],
                    "allow": ["example.overlay.user-simple"],
                },
            }
        ),
        encoding="utf-8",
    )

    script_path = tmp_path / "script.yaml"
    script_path.write_text(
        yaml.safe_dump(
            {
                "meta": {"title": "test", "version": 3},
                "scenes": [
                    {
                        "id": "s1",
                        "bg": str((root / "assets" / "bg" / "room.png").resolve()),
                        "fg_overlays": [
                            {
                                "id": "shake_fanfare",
                                "src": str((root / "assets" / "overlay" / "speedlines.png").resolve()),
                                "mode": "overlay",
                                "effects": ["shake_fanfare"],
                            }
                        ],
                        "lines": [
                            {
                                "text": "fanfare付き揺れのテスト",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    config = load_script_and_config(str(script_path), str(default_config_path))
    line = config["script"]["scenes"][0]["lines"][0]

    assert line.get("sound_effects"), "shake_fanfare はデフォルトSEを自動付与する"
    se = line["sound_effects"][0]
    assert se["path"].endswith("rap_fanfare.mp3")


def test_image_layers_show_hide_supported(tmp_path):
    root = Path.cwd()
    default_config_path = tmp_path / "default.yaml"
    default_config_path.write_text(
        yaml.safe_dump(
            {
                "script": {"scenes": []},
                "defaults": {},
            }
        ),
        encoding="utf-8",
    )

    script_path = tmp_path / "script.yaml"
    script_path.write_text(
        yaml.safe_dump(
            {
                "meta": {"title": "image_layers", "version": 3},
                "scenes": [
                    {
                        "id": "s1",
                        "bg": str((root / "assets" / "bg" / "room.png").resolve()),
                        "lines": [
                            {
                                "text": "表示テスト",
                                "image_layers": [
                                    {
                                        "show": {
                                            "id": "room_thumb",
                                            "path": str(
                                                (root / "assets" / "bg" / "room.png").resolve()
                                            ),
                                            "scale": 0.3,
                                            "anchor": "bottom_right",
                                            "position": {"x": -20, "y": -20},
                                            "transition": {
                                                "in": {"type": "fade", "duration": 0.5},
                                                "out": {"type": "fade", "duration": 0.4},
                                            },
                                        }
                                    }
                                ],
                            },
                            {
                                "image_layers": [
                                    {
                                        "hide": {
                                            "id": "room_thumb",
                                            "transition": {
                                                "out": {"type": "fade", "duration": 0.4}
                                            },
                                        }
                                    }
                                ]
                            },
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    config = load_script_and_config(str(script_path), str(default_config_path))
    line0 = config["script"]["scenes"][0]["lines"][0]
    line1 = config["script"]["scenes"][0]["lines"][1]

    assert "image_layers" in line0
    assert "image_layers" in line1


def test_load_script_and_config_supports_markdown_input(tmp_path):
    root = Path.cwd()
    default_config_path = tmp_path / "default.yaml"
    default_config_path.write_text(
        yaml.safe_dump(
            {
                "script": {"scenes": []},
                "background": {"default": str((root / "assets" / "bg" / "room.png").resolve())},
                "defaults": {},
            }
        ),
        encoding="utf-8",
    )

    script_path = tmp_path / "script.md"
    script_path.write_text(
        """---
meta:
  title: markdown
bg: assets/bg/room.png
defaults:
  characters:
    copetan:
      speaker_id: 3
      style: smile
---
# タイトル
本文を画像化するブロック

copetan: 最初の行
ナレーション: 二行目
""",
        encoding="utf-8",
    )

    config = load_script_and_config(str(script_path), str(default_config_path))
    lines = config["script"]["scenes"][0]["lines"]
    assert len(lines) == 3
    assert "image_layers" in lines[0]
    assert lines[1]["text"] == "最初の行"
    assert lines[1]["speaker_name"] == "copetan"
    assert lines[1]["characters"][0]["name"] == "copetan"
    assert lines[2]["speaker_name"] == "ナレーション"
