from __future__ import annotations

import inspect
from pathlib import Path

from zundamotion.components.markdown import pipeline
from zundamotion.components.markdown.render_config import (
    resolve_markdown_background,
    resolve_markdown_characters,
    resolve_markdown_render_config,
)


def test_pipeline_preserves_historical_private_config_aliases() -> None:
    assert pipeline._resolve_bg is resolve_markdown_background
    assert pipeline._character_defaults is resolve_markdown_characters
    assert pipeline._markdown_render_config is resolve_markdown_render_config


def test_markdown_pipeline_is_below_file_limit() -> None:
    path = Path(pipeline.__file__)
    assert len(path.read_text(encoding="utf-8").splitlines()) <= 500


def test_markdown_config_entrypoints_are_bounded() -> None:
    for target in (
        resolve_markdown_background,
        resolve_markdown_characters,
        resolve_markdown_render_config,
    ):
        lines, _ = inspect.getsourcelines(target)
        assert len(lines) <= 80, (target.__module__, target.__name__, len(lines))
