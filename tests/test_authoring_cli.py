from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import yaml

from zundamotion.authoring import (
    CAPABILITIES_FORMAT,
    COMPILED_FORMAT,
    VALIDATION_FORMAT,
    capabilities_document,
    compiled_document,
    validation_document,
)

ROOT = Path(__file__).resolve().parents[1]


def _write_script(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_capabilities_document_is_machine_readable_and_stable() -> None:
    document = capabilities_document()

    assert document["format"] == CAPABILITIES_FORMAT
    assert document["format_version"] == 1
    assert document["tts"]["default_provider"] == "voicevox"
    assert document["tts"]["providers"] == ["voicevox", "chatterbox"]
    chatterbox = document["tts"]["provider_capabilities"]["chatterbox"]
    assert len(chatterbox["languages"]) == 23
    assert chatterbox["supports_voice_cloning"] is True
    assert chatterbox["optional_runtime"] is True
    assert "youtube_1080p" in document["export_presets"]
    assert document["motion"] == {
        "version": 1,
        "character": {
            "multi_keyframe": True,
            "properties": ["position.x", "position.y", "scale", "rotate", "opacity"],
            "easings": ["linear", "ease_in", "ease_out", "ease_in_out"],
        },
        "camera": {
            "multi_keyframe": True,
            "properties": ["focus.x", "focus.y", "zoom"],
            "zoom_range": [1.0, 4.0],
            "bounded_world_viewport": True,
        },
        "background": {
            "pan_zoom_multi_keyframe": True,
            "effect_types": ["bg:pan_zoom", "bg:ken_burns"],
            "properties": ["pan.x", "pan.y", "zoom"],
            "easings": ["linear", "ease_in", "ease_out", "ease_in_out"],
            "zoom_range": [1.0, 4.0],
            "focus_range": [0.0, 1.0],
            "legacy_single_segment_compatible": True,
        },
    }
    assert {
        "validate",
        "compile",
        "capabilities",
        "lock",
        "verify-lock",
    }.issubset(document["commands"])
    assert document["plugins"] == sorted(
        document["plugins"], key=lambda item: (item["kind"], item["id"])
    )


def test_compile_uses_render_loader_contract(tmp_path: Path) -> None:
    script = tmp_path / "minimal.yaml"
    _write_script(script, {"meta": {"title": "minimal", "version": 3}, "scenes": []})

    document = compiled_document(str(script))

    assert document["format"] == COMPILED_FORMAT
    assert document["format_version"] == 1
    assert document["config"]["script"]["meta"]["title"] == "minimal"
    assert document["config"]["script"]["scenes"] == []


def test_compile_preserves_motion_keyframes_without_renderer_ir(tmp_path: Path) -> None:
    script = tmp_path / "motion.yaml"
    _write_script(
        script,
        {
            "meta": {"title": "motion", "version": 3},
            "scenes": [
                {
                    "id": "motion",
                    "lines": [
                        {
                            "text": "motion",
                            "characters": [
                                {
                                    "name": "copetan",
                                    "visible": True,
                                    "position": {"x": 120, "y": -32},
                                    "scale": 1.0,
                                    "move": {
                                        "from": {"x": -120, "y": -32, "scale": 0.8},
                                        "duration": 1.0,
                                        "easing": "ease_in_out",
                                        "keyframes": [
                                            {"at": 0.25, "x": -40, "easing": "ease_out"},
                                            {"at": 0.65, "x": 40, "scale": 1.2},
                                        ],
                                    },
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    )

    document = compiled_document(str(script))
    move = document["config"]["script"]["scenes"][0]["lines"][0]["characters"][0]["move"]

    assert document["format_version"] == 1
    assert move["keyframes"] == [
        {"at": 0.25, "easing": "ease_out", "x": -40},
        {"at": 0.65, "scale": 1.2, "x": 40},
    ]
    assert "tracks" not in move
    assert "ffmpeg" not in move


def test_compile_preserves_rotate_authoring_without_renderer_geometry(
    tmp_path: Path,
) -> None:
    script = tmp_path / "rotate.yaml"
    _write_script(
        script,
        {
            "meta": {"title": "rotate", "version": 3},
            "scenes": [
                {
                    "id": "rotate",
                    "lines": [
                        {
                            "text": "rotate",
                            "characters": [
                                {
                                    "name": "copetan",
                                    "visible": True,
                                    "position": {"x": 0, "y": -32},
                                    "scale": 1.0,
                                    "rotate": 0,
                                    "move": {
                                        "from": {"rotate": -10},
                                        "duration": 1.0,
                                        "keyframes": [
                                            {"at": 0.5, "rotate": 20}
                                        ],
                                    },
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    )

    document = compiled_document(str(script))
    character = document["config"]["script"]["scenes"][0]["lines"][0]["characters"][0]

    assert document["format_version"] == 1
    assert character["rotate"] == 0
    assert character["move"]["from"]["rotate"] == -10
    assert character["move"]["keyframes"][0]["rotate"] == 20
    assert "rotation_canvas" not in character
    assert "rotate_expr" not in character


def test_compile_preserves_opacity_authoring_without_alpha_ir(
    tmp_path: Path,
) -> None:
    script = tmp_path / "opacity.yaml"
    _write_script(
        script,
        {
            "meta": {"title": "opacity", "version": 3},
            "scenes": [
                {
                    "id": "opacity",
                    "lines": [
                        {
                            "text": "opacity",
                            "characters": [
                                {
                                    "name": "copetan",
                                    "visible": True,
                                    "position": {"x": 0, "y": -32},
                                    "scale": 1.0,
                                    "opacity": 0.5,
                                    "move": {
                                        "from": {"opacity": 0.0},
                                        "duration": 1.0,
                                        "keyframes": [
                                            {"at": 0.5, "opacity": 1.0}
                                        ],
                                    },
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    )

    document = compiled_document(str(script))
    character = document["config"]["script"]["scenes"][0]["lines"][0]["characters"][0]

    assert document["format_version"] == 1
    assert character["opacity"] == 0.5
    assert character["move"]["from"]["opacity"] == 0.0
    assert character["move"]["keyframes"][0]["opacity"] == 1.0
    assert "opacity_expr" not in character
    assert "alpha_filter" not in character


def test_compile_preserves_camera_authoring_without_renderer_ir(
    tmp_path: Path,
) -> None:
    script = tmp_path / "camera.yaml"
    _write_script(
        script,
        {
            "meta": {"title": "camera", "version": 3},
            "scenes": [
                {
                    "id": "camera",
                    "lines": [
                        {
                            "text": "camera",
                            "camera": {
                                "focus": {"x": 0.7, "y": 0.45},
                                "zoom": 1.4,
                                "move": {
                                    "from": {
                                        "focus": {"x": 0.5},
                                        "zoom": 1.0,
                                    },
                                    "duration": 1.0,
                                    "keyframes": [
                                        {
                                            "at": 0.5,
                                            "focus": {"x": 0.62},
                                            "zoom": 1.2,
                                        }
                                    ],
                                },
                            },
                        }
                    ],
                }
            ],
        },
    )

    document = compiled_document(str(script))
    camera = document["config"]["script"]["scenes"][0]["lines"][0]["camera"]

    assert document["format_version"] == 1
    assert camera["focus"] == {"x": 0.7, "y": 0.45}
    assert camera["zoom"] == 1.4
    assert camera["move"]["from"] == {
        "focus": {"x": 0.5},
        "zoom": 1.0,
    }
    assert camera["move"]["keyframes"][0] == {
        "at": 0.5,
        "focus": {"x": 0.62},
        "zoom": 1.2,
    }
    assert "zoompan" not in camera
    assert "cpu_fallback" not in camera
    assert "tracks" not in camera


def test_compile_preserves_background_pan_zoom_keyframes_without_renderer_ir(
    tmp_path: Path,
) -> None:
    script = tmp_path / "background-motion.yaml"
    _write_script(
        script,
        {
            "meta": {"title": "background motion", "version": 3},
            "scenes": [
                {
                    "id": "background-motion",
                    "lines": [
                        {
                            "text": "background motion",
                            "background_effects": [
                                {
                                    "type": "bg:pan_zoom",
                                    "zoom": {"from": 1.0, "to": 1.4},
                                    "pan": {
                                        "from": {"x": 0.2, "y": 0.5},
                                        "to": {"x": 0.8, "y": 0.5},
                                    },
                                    "start": 0.1,
                                    "duration": 1.2,
                                    "easing": "ease_in_out",
                                    "keyframes": [
                                        {
                                            "at": 0.4,
                                            "zoom": 1.15,
                                            "easing": "ease_out",
                                        },
                                        {
                                            "at": 0.8,
                                            "pan": {"x": 0.6},
                                            "zoom": 1.3,
                                        },
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    )

    document = compiled_document(str(script))
    effect = document["config"]["script"]["scenes"][0]["lines"][0][
        "background_effects"
    ][0]

    assert document["format_version"] == 1
    assert effect["type"] == "bg:pan_zoom"
    assert effect["start"] == 0.1
    assert effect["duration"] == 1.2
    assert effect["easing"] == "ease_in_out"
    assert effect["keyframes"] == [
        {"at": 0.4, "easing": "ease_out", "zoom": 1.15},
        {"at": 0.8, "pan": {"x": 0.6}, "zoom": 1.3},
    ]
    assert "tracks" not in effect
    assert "zoompan" not in effect
    assert "cpu_fallback" not in effect


def test_validation_document_reports_stable_error_code(tmp_path: Path) -> None:
    script = tmp_path / "invalid.yaml"
    _write_script(script, {"meta": {"title": "invalid", "version": 3}, "scenes": "bad"})

    document = validation_document(str(script))

    assert document["format"] == VALIDATION_FORMAT
    assert document["format_version"] == 1
    assert document["valid"] is False
    assert document["errors"][0]["code"] == "ZDM-E1000"
    assert "scenes" in document["errors"][0]["message"]


def test_module_cli_help_lists_authoring_commands() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "zundamotion", "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert "validate" in proc.stdout
    assert "compile" in proc.stdout
    assert "capabilities" in proc.stdout
    assert "lock" in proc.stdout
    assert "verify-lock" in proc.stdout
    assert "render" in proc.stdout


def test_module_cli_capabilities_json_does_not_start_render_runtime() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "zundamotion", "capabilities", "--json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    document = json.loads(proc.stdout)
    assert document["format"] == CAPABILITIES_FORMAT
    assert document["tts"]["providers"] == ["voicevox", "chatterbox"]
    assert "en" in document["tts"]["provider_capabilities"]["chatterbox"]["languages"]


def test_module_cli_compile_to_stdout(tmp_path: Path) -> None:
    script = tmp_path / "minimal.yaml"
    _write_script(script, {"meta": {"title": "cli", "version": 3}, "scenes": []})

    proc = subprocess.run(
        [sys.executable, "-m", "zundamotion", "compile", str(script)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    document = json.loads(proc.stdout)
    assert document["format"] == COMPILED_FORMAT
    assert document["config"]["script"]["meta"]["title"] == "cli"
