from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest
from PIL import Image

from zundamotion.components.config.validate_character_rig import (
    validate_character_rig_config,
)
from zundamotion.components.video.character_rig_materializer import (
    CharacterRigMaterializer,
    rig_runtime_enabled,
)
from zundamotion.components.video.character_rig_validation import validate
from zundamotion.exceptions import ValidationError


RIG_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100">
<g id="character">
  <g id="body"><rect x="20" y="30" width="60" height="60" fill="#00ff00"/></g>
  <g id="head">
    <g id="face">
      <g id="face-base"><circle cx="50" cy="25" r="20" fill="#ffffff"/></g>
      <g id="eyes">
        <g id="eyes-open"><rect x="35" y="20" width="8" height="4" fill="#0000ff"/></g>
        <g id="eyes-half"><rect x="35" y="21" width="8" height="2" fill="#00ffff"/></g>
        <g id="eyes-closed"><rect x="35" y="22" width="8" height="2" fill="#ff0000"/></g>
      </g>
      <g id="mouth">
        <g id="mouth-closed"><rect x="45" y="32" width="10" height="2" fill="#000000"/></g>
        <g id="mouth-small"><rect x="46" y="31" width="8" height="4" fill="#ffff00"/></g>
        <g id="mouth-a"><rect x="45" y="29" width="10" height="8" fill="#ff00ff"/></g>
        <g id="mouth-i"/>
        <g id="mouth-u"/>
        <g id="mouth-e"/>
        <g id="mouth-o"/>
      </g>
    </g>
  </g>
</g>
</svg>"""


class _Cache:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.memo: dict[str, Path] = {}
        self.creations = 0

    async def get_or_create(self, *, key_data, file_name, extension, creator_func):
        key = json.dumps(key_data, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        existing = self.memo.get(digest)
        if existing is not None and existing.exists():
            return existing
        path = self.root / f"{file_name}_{digest[:16]}.{extension}"
        self.creations += 1
        result = await creator_func(path)
        self.memo[digest] = Path(result)
        return Path(result)


def _write_rig(root: Path, content: str = RIG_SVG) -> Path:
    path = root / "assets" / "characters" / "hero" / "character.svg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_runtime_and_tool_validation_share_valid_rig_semantics(tmp_path: Path) -> None:
    path = _write_rig(tmp_path)
    result = validate(path)

    assert result["valid"] is True
    assert result["rig_version"] == 1


def test_character_rig_validation_requires_explicit_local_valid_svg(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_rig(tmp_path)

    validate_character_rig_config(
        {"path": "assets/characters/hero/character.svg"},
        "character.rig",
    )

    with pytest.raises(ValidationError, match="project-relative"):
        validate_character_rig_config(
            {"path": str((tmp_path / "outside.svg").resolve())},
            "character.rig",
        )
    with pytest.raises(ValidationError, match="does not exist"):
        validate_character_rig_config(
            {"path": "assets/characters/missing.svg"},
            "character.rig",
        )
    with pytest.raises(ValidationError, match="unsupported properties"):
        validate_character_rig_config(
            {
                "path": "assets/characters/hero/character.svg",
                "fps": 30,
            },
            "character.rig",
        )


def test_disabled_rig_does_not_require_path() -> None:
    validate_character_rig_config({"enabled": False}, "character.rig")
    assert rig_runtime_enabled({"rig": {"enabled": False}}) is False
    assert rig_runtime_enabled({}) is False


@pytest.mark.asyncio
async def test_materializer_builds_face_compatible_png_assets_and_reuses_cache(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    rig_path = _write_rig(tmp_path)
    cache = _Cache(tmp_path / "cache")
    cache.root.mkdir(parents=True)
    materializer = CharacterRigMaterializer(cache)  # type: ignore[arg-type]

    assets = await materializer.materialize(
        {
            "path": "assets/characters/hero/character.svg",
            "raster_width": 100,
        }
    )
    first_creations = cache.creations

    assert assets.base.exists()
    assert set(assets.eyes) == {"open", "close"}
    assert set(assets.mouth) == {"close", "half", "open"}
    assert first_creations == 6

    base = Image.open(assets.base).convert("RGBA")
    eye_close = Image.open(assets.eyes["close"]).convert("RGBA")
    mouth_open = Image.open(assets.mouth["open"]).convert("RGBA")

    # Base contains neutral body/open-eye state.
    assert base.getpixel((25, 70))[1] > 200
    assert base.getpixel((38, 21))[2] > 200

    # Face overlays keep the full canvas but isolate only the requested state.
    assert eye_close.size == base.size == (100, 100)
    assert eye_close.getpixel((25, 70))[3] == 0
    assert eye_close.getpixel((38, 22))[0] > 200
    assert mouth_open.getpixel((50, 32))[0] > 200
    assert mouth_open.getpixel((25, 70))[3] == 0

    again = await materializer.materialize(
        {
            "path": "assets/characters/hero/character.svg",
            "raster_width": 100,
        }
    )
    assert cache.creations == first_creations
    assert again.base == assets.base

    rig_path.write_text(RIG_SVG.replace("#00ff00", "#008800"), encoding="utf-8")
    changed = await materializer.materialize(
        {
            "path": "assets/characters/hero/character.svg",
            "raster_width": 100,
        }
    )
    assert cache.creations == first_creations + 6
    assert changed.base != assets.base


@pytest.mark.asyncio
async def test_materializer_rejects_network_and_project_escape_resources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    cache = _Cache(tmp_path / "cache")
    cache.root.mkdir(parents=True)
    materializer = CharacterRigMaterializer(cache)  # type: ignore[arg-type]

    remote = RIG_SVG.replace(
        '<g id="body"><rect',
        '<g id="body"><image href="https://example.com/a.png"/><rect',
    )
    _write_rig(tmp_path, remote)
    with pytest.raises(ValidationError, match="must be local or embedded"):
        await materializer.materialize(
            {"path": "assets/characters/hero/character.svg"}
        )

    escaped = RIG_SVG.replace(
        '<g id="body"><rect',
        '<g id="body"><image href="../../../../../outside.png"/><rect',
    )
    _write_rig(tmp_path, escaped)
    with pytest.raises(ValidationError, match="escapes the project"):
        await materializer.materialize(
            {"path": "assets/characters/hero/character.svg"}
        )


def test_materializer_module_does_not_eager_import_cairosvg() -> None:
    module = sys.modules["zundamotion.components.video.character_rig_materializer"]
    assert "cairosvg" not in module.__dict__
