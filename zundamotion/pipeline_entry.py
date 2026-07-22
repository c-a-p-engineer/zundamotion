"""High-level script loading and GenerationPipeline entry point."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .components.script import load_script_and_config
from .components.subtitles.lifecycle import shutdown_subtitle_executor
from .plugins.manager import initialize_plugins
from .utils.logger import logger
from .pipeline import GenerationPipeline


async def run_generation(
    script_path: str,
    output_path: str,
    no_cache: bool = False,
    cache_refresh: bool = False,
    jobs: str = "0",
    timeline_format: Optional[str] = None,
    no_timeline: bool = False,
    subtitle_file_format: Optional[str] = None,
    no_subtitle_file: bool = False,
    hw_encoder: str = "auto",
    quality: str = "balanced",
    final_copy_only: bool = False,
    disable_plugins: bool = False,
    plugin_paths: Optional[List[str]] = None,
    plugin_allow: Optional[List[str]] = None,
    plugin_deny: Optional[List[str]] = None,
    dump_resolved_path: Optional[str] = None,
    debug_include: bool = False,
    disable_voice: bool = False,
):
    """動画生成を高レベルに実行するユーティリティ関数。"""
    # Get the path to the default config file
    default_config_path = Path(__file__).parent / "templates" / "config.yaml"

    # Load script and config
    config = load_script_and_config(
        script_path,
        str(default_config_path),
        dump_resolved_path=dump_resolved_path,
        debug_include=debug_include,
    )
    if disable_voice:
        config.setdefault("voice", {})["enabled"] = False

    # Override timeline settings from CLI
    if no_timeline:
        config.setdefault("system", {}).setdefault("timeline", {})["enabled"] = False
    elif timeline_format:
        config.setdefault("system", {}).setdefault("timeline", {})["enabled"] = True
        config["system"]["timeline"]["format"] = timeline_format

    # Override subtitle file settings from CLI
    if no_subtitle_file:
        config.setdefault("system", {}).setdefault("subtitle_file", {})[
            "enabled"
        ] = False
    elif subtitle_file_format:
        config.setdefault("system", {}).setdefault("subtitle_file", {})[
            "enabled"
        ] = True
        config["system"]["subtitle_file"]["format"] = subtitle_file_format

    # Initialize plugin system before pipeline creation
    if not disable_plugins:
        try:
            initialize_plugins(
                config=config,
                cli_paths=plugin_paths,
                allow_ids=plugin_allow,
                deny_ids=plugin_deny,
            )
        except Exception:
            logger.warning("[PluginLoader] Plugin initialization failed; continuing with built-ins")

    # Resolve VideoParams and AudioParams once from the preset-expanded config.
    pipeline = GenerationPipeline(
        config,
        no_cache,
        cache_refresh,
        jobs,
        hw_encoder=hw_encoder,
        quality=quality,
        final_copy_only=final_copy_only,
    )
    try:
        await pipeline.run(output_path)
    finally:
        shutdown_subtitle_executor()
