from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zundamotion.components.script.loader import load_script_and_config
from zundamotion.exceptions import ValidationError


def test_export_preset_overrides_template_defaults_but_not_explicit_video(tmp_path):
    default_config_path = tmp_path / "default.yaml"
    default_config_path.write_text(
        yaml.safe_dump({"script": {"scenes": []}, "defaults": {}, "video": {"width": 1920, "height": 1080, "fps": 30}}),
        encoding="utf-8",
    )
    script_path = tmp_path / "script.yaml"
    script_path.write_text(
        yaml.safe_dump(
            {
                "export_preset": "youtube_1440p",
                "video": {"fps": 24},
                "scenes": [{"id": "scene", "lines": [{"wait": 0.1}]}],
            }
        ),
        encoding="utf-8",
    )

    config = load_script_and_config(str(script_path), str(default_config_path))
    assert (config["video"]["width"], config["video"]["height"], config["video"]["fps"]) == (
        2560,
        1440,
        24,
    )


def test_persistent_character_display_defaults_are_left_for_tracker(tmp_path):
    default_config_path = tmp_path / "default.yaml"
    default_config_path.write_text(
        yaml.safe_dump({"script": {"scenes": []}, "defaults": {}}), encoding="utf-8"
    )
    script_path = tmp_path / "script.yaml"
    script_path.write_text(
        yaml.safe_dump(
            {
                "defaults": {
                    "characters_persist": True,
                    "characters": {"alice": {"scale": 0.7, "position": {"x": 10, "y": 0}}},
                },
                "scenes": [
                    {
                        "id": "scene",
                        "lines": [
                            {"text": "first", "characters": [{"name": "alice", "expression": "smile"}]}
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    config = load_script_and_config(str(script_path), str(default_config_path))
    character = config["script"]["scenes"][0]["lines"][0]["characters"][0]
    assert character == {"name": "alice", "expression": "smile"}


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


def test_top_level_transitions_override_default_config(tmp_path):
    root = Path.cwd()
    default_config_path = tmp_path / "default.yaml"
    default_config_path.write_text(
        yaml.safe_dump(
            {
                "script": {"scenes": []},
                "transitions": {"wait_padding_seconds": 2.0},
                "defaults": {},
            }
        ),
        encoding="utf-8",
    )

    script_path = tmp_path / "script.yaml"
    script_path.write_text(
        yaml.safe_dump(
            {
                "meta": {"title": "transition override", "version": 3},
                "transitions": {"wait_padding_seconds": 0.0},
                "scenes": [
                    {
                        "id": "scene",
                        "bg": str((root / "assets" / "bg" / "room.png").resolve()),
                        "lines": [{"text": "トランジション設定を反映します"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    config = load_script_and_config(str(script_path), str(default_config_path))

    assert config["transitions"]["wait_padding_seconds"] == 0.0


def test_top_level_badges_are_inherited_by_each_scene(tmp_path):
    root = Path.cwd()
    default_config_path = tmp_path / "default.yaml"
    default_config_path.write_text(
        yaml.safe_dump({"script": {"scenes": []}, "defaults": {}}),
        encoding="utf-8",
    )

    script_path = tmp_path / "script.yaml"
    script_path.write_text(
        yaml.safe_dump(
            {
                "meta": {"title": "global badges", "version": 3},
                "badges": [
                    {
                        "id": "important-top",
                        "text": "重要",
                        "position": "top-right",
                        "visible": False,
                    }
                ],
                "scenes": [
                    {
                        "id": "s1",
                        "bg": str((root / "assets" / "bg" / "room.png").resolve()),
                        "lines": [
                            {
                                "text": "共有バッジを表示",
                                "badges": [{"id": "important-top", "visible": True}],
                            }
                        ],
                    },
                    {
                        "id": "s2",
                        "bg": str((root / "assets" / "bg" / "room.png").resolve()),
                        "lines": [{"text": "別シーンでも使えます"}],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    config = load_script_and_config(str(script_path), str(default_config_path))

    first_scene_badges = config["script"]["scenes"][0]["badges"]
    second_scene_badges = config["script"]["scenes"][1]["badges"]
    assert first_scene_badges[0]["id"] == "important-top"
    assert second_scene_badges[0]["id"] == "important-top"
    assert first_scene_badges[0]["visible"] is False
    assert second_scene_badges[0]["visible"] is False


def test_scene_badges_override_top_level_badges_by_id(tmp_path):
    root = Path.cwd()
    default_config_path = tmp_path / "default.yaml"
    default_config_path.write_text(
        yaml.safe_dump({"script": {"scenes": []}, "defaults": {}}),
        encoding="utf-8",
    )

    script_path = tmp_path / "script.yaml"
    script_path.write_text(
        yaml.safe_dump(
            {
                "meta": {"title": "badge override", "version": 3},
                "badges": [
                    {
                        "id": "important-top",
                        "text": "重要",
                        "position": "top-right",
                        "visible": False,
                        "background": {"show": True, "color": "#111111"},
                    }
                ],
                "scenes": [
                    {
                        "id": "s1",
                        "bg": str((root / "assets" / "bg" / "room.png").resolve()),
                        "badges": [
                            {
                                "id": "important-top",
                                "text": "最重要",
                                "background": {"show": True, "color": "#991B1B"},
                            }
                        ],
                        "lines": [{"text": "上書きテスト"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    config = load_script_and_config(str(script_path), str(default_config_path))
    badge = config["script"]["scenes"][0]["badges"][0]

    assert badge["id"] == "important-top"
    assert badge["text"] == "最重要"
    assert badge["position"] == "top-right"
    assert badge["background"]["color"] == "#991B1B"


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


def test_badge_config_supported_on_scene_and_line(tmp_path):
    root = Path.cwd()
    default_config_path = tmp_path / "default.yaml"
    default_config_path.write_text(
        yaml.safe_dump({"script": {"scenes": []}, "defaults": {}}),
        encoding="utf-8",
    )

    script_path = tmp_path / "script.yaml"
    script_path.write_text(
        yaml.safe_dump(
            {
                "meta": {"title": "badge", "version": 3},
                "scenes": [
                    {
                        "id": "s1",
                        "bg": str((root / "assets" / "bg" / "room.png").resolve()),
                        "badges": [
                            {
                                "id": "important-top",
                                "text": "重要",
                                "position": "top-right",
                                "visible": False,
                                "font_size": 42,
                                "font_color": "#FFFFFF",
                                "stroke_color": "#202020",
                                "background": {
                                    "show": True,
                                    "color": "#111111",
                                    "opacity": 0.72,
                                    "radius": 24,
                                    "border_color": "#FFFFFF",
                                    "border_width": 3,
                                    "border_opacity": 0.65,
                                    "padding": {
                                        "left": 48,
                                        "right": 48,
                                        "top": 18,
                                        "bottom": 18,
                                    },
                                },
                            }
                        ],
                        "lines": [
                            {
                                "text": "scene badge",
                                "badges": [{"id": "important-top", "visible": True}],
                            },
                            {
                                "id": "line_end",
                                "text": "line badge",
                                "badges": [{"id": "important-top", "visible": False}],
                                "badge": {
                                    "text": "注意",
                                    "position": "top-left",
                                    "timing": {"start": 0.25, "end": 1.0},
                                },
                            },
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    config = load_script_and_config(str(script_path), str(default_config_path))
    scene = config["script"]["scenes"][0]

    assert scene["badges"][0]["id"] == "important-top"
    assert scene["badges"][0]["visible"] is False
    assert scene["lines"][0]["badges"] == [{"id": "important-top", "visible": True}]
    assert scene["lines"][1]["badges"] == [{"id": "important-top", "visible": False}]
    assert scene["lines"][1]["badge"] == {
        "text": "注意",
        "position": "top-left",
        "timing": {"start": 0.25, "end": 1.0},
    }


def test_invalid_badge_position_rejected(tmp_path):
    root = Path.cwd()
    default_config_path = tmp_path / "default.yaml"
    default_config_path.write_text(
        yaml.safe_dump({"script": {"scenes": []}, "defaults": {}}),
        encoding="utf-8",
    )

    script_path = tmp_path / "script.yaml"
    script_path.write_text(
        yaml.safe_dump(
            {
                "meta": {"title": "badge", "version": 3},
                "scenes": [
                    {
                        "id": "s1",
                        "bg": str((root / "assets" / "bg" / "room.png").resolve()),
                        "badge": {"text": "重要", "position": "middle-right"},
                        "lines": [{"text": "invalid"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_script_and_config(str(script_path), str(default_config_path))


def test_invalid_badge_end_rejected(tmp_path):
    root = Path.cwd()
    default_config_path = tmp_path / "default.yaml"
    default_config_path.write_text(
        yaml.safe_dump({"script": {"scenes": []}, "defaults": {}}),
        encoding="utf-8",
    )

    script_path = tmp_path / "script.yaml"
    script_path.write_text(
        yaml.safe_dump(
            {
                "meta": {"title": "badge", "version": 3},
                "scenes": [
                    {
                        "id": "s1",
                        "bg": str((root / "assets" / "bg" / "room.png").resolve()),
                        "badge": {
                            "text": "重要",
                            "position": "top-right",
                            "timing": {"start": 1.0, "end": 1.0},
                        },
                        "lines": [{"text": "invalid"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_script_and_config(str(script_path), str(default_config_path))


def test_invalid_badge_show_on_line_rejected(tmp_path):
    root = Path.cwd()
    default_config_path = tmp_path / "default.yaml"
    default_config_path.write_text(
        yaml.safe_dump({"script": {"scenes": []}, "defaults": {}}),
        encoding="utf-8",
    )

    script_path = tmp_path / "script.yaml"
    script_path.write_text(
        yaml.safe_dump(
            {
                "meta": {"title": "badge", "version": 3},
                "scenes": [
                    {
                        "id": "s1",
                        "bg": str((root / "assets" / "bg" / "room.png").resolve()),
                        "badge": {
                            "text": "重要",
                            "position": "top-right",
                            "timing": {"show_on_line": 0},
                        },
                        "lines": [{"text": "invalid"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_script_and_config(str(script_path), str(default_config_path))


def test_invalid_line_badge_visible_rejected(tmp_path):
    root = Path.cwd()
    default_config_path = tmp_path / "default.yaml"
    default_config_path.write_text(
        yaml.safe_dump({"script": {"scenes": []}, "defaults": {}}),
        encoding="utf-8",
    )

    script_path = tmp_path / "script.yaml"
    script_path.write_text(
        yaml.safe_dump(
            {
                "meta": {"title": "badge", "version": 3},
                "scenes": [
                    {
                        "id": "s1",
                        "bg": str((root / "assets" / "bg" / "room.png").resolve()),
                        "badges": [
                            {
                                "id": "important-top",
                                "text": "重要",
                                "position": "top-right",
                            }
                        ],
                        "lines": [
                            {
                                "text": "invalid",
                                "badges": [{"id": "important-top", "visible": "yes"}],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_script_and_config(str(script_path), str(default_config_path))


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
