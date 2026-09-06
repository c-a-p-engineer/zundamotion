from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


validate_rig = load_module("validate_rig_tool", "tools/character_rig/validate_rig.py")
render_preview = load_module("render_preview_tool", "tools/character_rig/render_preview.py")


V2_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 200" data-rig-version="2">
<g id="character"><g id="body"><g id="torso"/><g id="waist"/>
<g id="arm-left"><g id="upper-arm-left" data-pivot-x="20" data-pivot-y="60"><image id="ua-l" data-source-part="upper_arm_L" href="x"/></g><g id="forearm-left" data-pivot-x="15" data-pivot-y="85"><image id="fa-l" data-source-part="forearm_L" href="x"/></g><g id="hand-left" data-pivot-x="14" data-pivot-y="105"><image id="h-l" data-source-part="hand_L" href="x"/></g></g>
<g id="arm-right"><g id="upper-arm-right" data-pivot-x="80" data-pivot-y="60"><image id="ua-r" data-source-part="upper_arm_R" href="x"/></g><g id="forearm-right" data-pivot-x="85" data-pivot-y="85"><image id="fa-r" data-source-part="forearm_R" href="x"/></g><g id="hand-right" data-pivot-x="86" data-pivot-y="105"><image id="h-r" data-source-part="hand_R" href="x"/></g></g>
<g id="leg-left"><g id="thigh-left" data-pivot-x="40" data-pivot-y="120"><image id="t-l" data-source-part="thigh_L" href="x"/></g><g id="calf-left" data-pivot-x="40" data-pivot-y="150"><image id="c-l" data-source-part="calf_L" href="x"/></g><g id="foot-left" data-pivot-x="40" data-pivot-y="185"><image id="f-l" data-source-part="foot_L" href="x"/></g></g>
<g id="leg-right"><g id="thigh-right" data-pivot-x="60" data-pivot-y="120"><image id="t-r" data-source-part="thigh_R" href="x"/></g><g id="calf-right" data-pivot-x="60" data-pivot-y="150"><image id="c-r" data-source-part="calf_R" href="x"/></g><g id="foot-right" data-pivot-x="60" data-pivot-y="185"><image id="f-r" data-source-part="foot_R" href="x"/></g></g></g>
<g id="head" data-pivot-x="50" data-pivot-y="45"><g id="hair-back" data-pivot-x="50" data-pivot-y="30"/><g id="face"><g id="face-base"/><g id="eyes"><g id="eyes-open"><image id="eyes-open-img" data-source-part="eye_L_open" href="x"/></g><g id="eyes-half"><image id="eyes-half-img" data-source-part="eye_L_half" href="x"/></g><g id="eyes-closed"><image id="eyes-closed-img" data-source-part="eye_L_closed" href="x"/></g></g><g id="mouth"><g id="mouth-closed"><image id="m-closed" data-source-part="mouth_closed" href="x"/></g><g id="mouth-small"><image id="m-small" data-source-part="mouth_small" href="x"/></g><g id="mouth-a"><image id="m-a" data-source-part="mouth_a" href="x"/></g><g id="mouth-i"><image id="m-i" data-source-part="mouth_i" href="x"/></g><g id="mouth-u"><image id="m-u" data-source-part="mouth_u" href="x"/></g><g id="mouth-e"><image id="m-e" data-source-part="mouth_e" href="x"/></g><g id="mouth-o"><image id="m-o" data-source-part="mouth_o" href="x"/></g></g></g><g id="hair-front" data-pivot-x="50" data-pivot-y="25"/><g id="hair-left" data-pivot-x="35" data-pivot-y="35"/><g id="hair-right" data-pivot-x="65" data-pivot-y="35"/><g id="ahoge" data-pivot-x="50" data-pivot-y="12"/></g></g></svg>'''


def test_validate_v2_accepts_joint_rig(tmp_path: Path):
    path = tmp_path / "rig.svg"
    path.write_text(V2_SVG, encoding="utf-8")
    result = validate_rig.validate(path)
    assert result["valid"] is True
    assert result["rig_version"] == 2
    assert result["missing_v2_joint_ids"] == []
    assert result["missing_pivots"] == []


def test_validate_v2_rejects_missing_joint_pivot(tmp_path: Path):
    path = tmp_path / "rig.svg"
    path.write_text(
        V2_SVG.replace(' data-pivot-x="15" data-pivot-y="85"', "", 1),
        encoding="utf-8",
    )
    result = validate_rig.validate(path)
    assert result["valid"] is False
    assert "forearm-left" in result["missing_pivots"]


def test_validate_v2_rejects_fullbody_ref_in_character(tmp_path: Path):
    path = tmp_path / "rig.svg"
    bad = V2_SVG.replace(
        'data-source-part="upper_arm_L"', 'data-source-part="fullbody_ref"', 1
    )
    path.write_text(bad, encoding="utf-8")
    result = validate_rig.validate(path)
    assert result["valid"] is False
    assert any("fullbody_ref" in message for message in result["errors"])


def test_preview_uses_half_blink_and_joint_pivots():
    metadata = render_preview.parse_rig_metadata(V2_SVG)
    animated = render_preview.animate(V2_SVG, 1.20, metadata)
    assert 'id="eyes-half" opacity="1"' in animated or 'opacity="1" id="eyes-half"' in animated
    assert 'id="eyes-open" opacity="0"' in animated or 'opacity="0" id="eyes-open"' in animated
    assert 'id="upper-arm-left"' in animated
    assert "rotate(" in animated
    assert "20.000 60.000" in animated
    assert "15.000 85.000" in animated


def test_preview_closed_blink_and_mouth_replacement():
    metadata = render_preview.parse_rig_metadata(V2_SVG)
    animated = render_preview.animate(V2_SVG, 1.25, metadata)
    assert 'id="eyes-closed" opacity="1"' in animated or 'opacity="1" id="eyes-closed"' in animated
    mouth_visible = [
        mouth_id
        for mouth_id in render_preview.MOUTH_IDS
        if f'id="{mouth_id}" opacity="1"' in animated
        or f'opacity="1" id="{mouth_id}"' in animated
    ]
    assert len(mouth_visible) == 1
