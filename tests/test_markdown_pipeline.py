import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zundamotion.components.markdown.pipeline import load_markdown_script
from zundamotion.components.markdown.pipeline import _tokenize_markdown_lines


def test_load_markdown_script_applies_panel_layout_and_canvas_size(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "script.md"
    script.write_text(
        """---
meta:
  title: Markdown Demo
video:
  width: 960
  height: 540
bg: assets/bg/room.png
markdown:
  layer:
    scale: 0.84
    position: {x: 0, y: -96}
  text:
    font_path: /usr/share/fonts/opentype/ipafont-gothic/ipag.ttf
    font_size: 44
    min_font_size: 24
---
# 見出し
かなり長めのMarkdown本文を入れても画像パネル内に収まることを確認します。

copetan: 本文
""",
        encoding="utf-8",
    )

    resolved = load_markdown_script(script)
    show_cfg = resolved["scenes"][0]["lines"][0]["image_layers"][0]["show"]
    assert show_cfg["scale"] == 0.84
    assert show_cfg["anchor"] == "middle_center"
    assert show_cfg["position"] == {"x": 0, "y": -96}

    panel_path = Path(show_cfg["path"])
    with Image.open(panel_path) as img:
        assert img.size == (960, 540)
        assert img.getbbox() is not None


def test_load_markdown_script_renders_custom_panel_colors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "script.md"
    script.write_text(
        """---
video:
  width: 640
  height: 360
bg: assets/bg/room.png
markdown:
  panel:
    margin: {x: 40, y: 24}
    padding: {x: 20, y: 16}
    background:
      color: "#112233"
      opacity: 1.0
      radius: 0
      border_width: 0
  text:
    font_size: 32
    min_font_size: 20
---
Title
Body

copetan: line
""",
        encoding="utf-8",
    )

    resolved = load_markdown_script(script)
    panel_path = Path(resolved["scenes"][0]["lines"][0]["image_layers"][0]["show"]["path"])
    with Image.open(panel_path) as img:
        pixel = img.getpixel((64, 48))
        assert pixel[:3] == (17, 34, 51)
        assert pixel[3] == 255


def test_tokenize_markdown_lines_preserves_markdown_structure():
    lines = _tokenize_markdown_lines(
        "# Title\n## Section\n- bullet item\n> quote\nplain"
    )
    assert lines[0].kind == "heading"
    assert lines[0].text == "Title"
    assert lines[0].level == 1
    assert lines[1].kind == "heading"
    assert lines[1].text == "Section"
    assert lines[2].kind == "bullet"
    assert lines[2].text == "bullet item"
    assert lines[3].kind == "quote"
    assert lines[3].text == "quote"
    assert lines[4].kind == "paragraph"
    assert lines[4].text == "plain"
