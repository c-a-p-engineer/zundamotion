import pathlib
import sys

import pytest

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
from zundamotion.components.script import load_script_and_config, ValidationError
from zundamotion.cache import CacheManager
from zundamotion.components.video import VideoRenderer


def test_load_script_with_fg_overlays():
    cfg = load_script_and_config('scripts/sample.yaml', 'zundamotion/templates/config.yaml')
    scenes = cfg['script']['scenes']
    assert any('fg_overlays' in s for s in scenes)
    assert any(
        'fg_overlays' in line
        for s in scenes
        for line in s.get('lines', [])
    )


def test_invalid_fg_overlay_mode(tmp_path):
    bad_yaml = tmp_path / 'bad.yaml'
    bad_yaml.write_text(
        'scenes:\n'
        '  - id: s1\n'
        '    fg_overlays:\n'
        '      - id: fg1\n'
        '        src: assets/overlay/sakura_bg_black.mp4\n'
        '        mode: invalid\n'
        '    lines: []\n'
    )
    with pytest.raises(ValidationError):
        load_script_and_config(str(bad_yaml), 'zundamotion/templates/config.yaml')


def test_invalid_fg_overlay_blend_mode(tmp_path):
    bad_yaml = tmp_path / 'bad_blend.yaml'
    bad_yaml.write_text(
        'scenes:\n'
        '  - id: s1\n'
        '    fg_overlays:\n'
        '      - id: fg1\n'
        '        src: assets/overlay/sakura_bg_black.mp4\n'
        '        mode: blend\n'
        '        blend_mode: unknown\n'
        '    lines: []\n'
    )
    with pytest.raises(ValidationError):
        load_script_and_config(str(bad_yaml), 'zundamotion/templates/config.yaml')


def test_invalid_fg_overlay_chroma_similarity(tmp_path):
    bad_yaml = tmp_path / 'bad_chroma.yaml'
    bad_yaml.write_text(
        'scenes:\n'
        '  - id: s1\n'
        '    fg_overlays:\n'
        '      - id: fg1\n'
        '        src: assets/overlay/sakura_bg_black.mp4\n'
        '        mode: chroma\n'
        '        chroma:\n'
        '          key_color: "#000000"\n'
        '          similarity: 1.5\n'
        '    lines: []\n'
    )
    with pytest.raises(ValidationError):
        load_script_and_config(str(bad_yaml), 'zundamotion/templates/config.yaml')


def test_invalid_line_fg_overlay_mode(tmp_path):
    bad_yaml = tmp_path / 'bad_line_overlay.yaml'
    bad_yaml.write_text(
        'scenes:\n'
        '  - id: s1\n'
        '    lines:\n'
        '      - text: "hi"\n'
        '        speaker_name: "zundamon"\n'
        '        fg_overlays:\n'
        '          - id: fg1\n'
        '            src: assets/overlay/sakura_bg_black.mp4\n'
        '            mode: invalid\n'
    )
    with pytest.raises(ValidationError):
        load_script_and_config(str(bad_yaml), 'zundamotion/templates/config.yaml')


def test_subtitles_applied_after_overlays(monkeypatch, tmp_path):
    cache = CacheManager(tmp_path / 'cache')
    renderer = VideoRenderer({}, tmp_path, cache)

    base = tmp_path / 'base.mp4'
    base.write_text('dummy')

    import zundamotion.components.video as video_module

    captured = {}

    async def fake_run(cmd):
        captured['cmd'] = cmd

    async def fake_build(text, duration, line_config, in_label, index, force_cpu=False, allow_cuda=None, existing_png_path=None):
        return {'-loop': '1', '-i': 'sub.png'}, f"[{in_label}][{index}:v]overlay=enable='between(t,0,{duration})'[with_subtitle_{index}]"

    monkeypatch.setattr(video_module, '_run_ffmpeg_async', fake_run)
    monkeypatch.setattr(renderer.subtitle_gen, 'build_subtitle_overlay', fake_build)

    subtitles = [{
        'text': 'hello',
        'duration': 1.0,
        'start': 0.5,
        'line_config': {},
    }]

    import asyncio

    asyncio.run(renderer.apply_subtitle_overlays(base, subtitles))
    cmd = captured['cmd']
    filter_arg = cmd[cmd.index('-filter_complex') + 1]
    assert "between(t,0.5,1.5)" in filter_arg
