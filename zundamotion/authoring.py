"""Machine-readable authoring contracts for AI/CI clients.

This module deliberately reuses the same script loader and validation path as
rendering.  The compiled document is the canonical resolved configuration sent
toward the renderer; it is not a second, speculative render IR.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import __version__
from .components.audio.chatterbox_provider import ChatterboxTTSProvider
from .components.audio.voicevox_client import VoicevoxTTSProvider
from .components.script.loader import load_script_and_config
from .exceptions import ValidationError
from .plugins.loader import builtin_plugin_paths, discover_plugins
from .utils.export_presets import EXPORT_PRESETS

COMPILED_FORMAT = "zundamotion.compiled-config"
COMPILED_FORMAT_VERSION = 1
VALIDATION_FORMAT = "zundamotion.validation"
VALIDATION_FORMAT_VERSION = 1
CAPABILITIES_FORMAT = "zundamotion.capabilities"
CAPABILITIES_FORMAT_VERSION = 1


def default_config_path() -> Path:
    """Return the packaged default configuration used by normal rendering."""

    return Path(__file__).resolve().parent / "templates" / "config.yaml"


def load_canonical_config(
    script_path: str,
    *,
    dump_resolved_path: str | None = None,
    debug_include: bool = False,
) -> dict[str, Any]:
    """Load, resolve, merge defaults/presets and validate one input script."""

    return load_script_and_config(
        script_path,
        str(default_config_path()),
        dump_resolved_path=dump_resolved_path,
        debug_include=debug_include,
    )


def compiled_document(script_path: str) -> dict[str, Any]:
    """Build canonical compiled-config v1 for a script without rendering."""

    config = load_canonical_config(script_path)
    return {
        "format": COMPILED_FORMAT,
        "format_version": COMPILED_FORMAT_VERSION,
        "zundamotion_version": __version__,
        "config": _json_value(config),
    }


def validation_document(script_path: str) -> dict[str, Any]:
    """Validate a script and return a stable machine-readable result."""

    try:
        load_canonical_config(script_path)
    except ValidationError as exc:
        return {
            "format": VALIDATION_FORMAT,
            "format_version": VALIDATION_FORMAT_VERSION,
            "valid": False,
            "errors": [
                {
                    "code": "ZDM-E1000",
                    "kind": "validation",
                    "message": exc.message,
                    "line": exc.line_number,
                    "column": exc.column_number,
                }
            ],
        }
    except (OSError, ValueError) as exc:
        return {
            "format": VALIDATION_FORMAT,
            "format_version": VALIDATION_FORMAT_VERSION,
            "valid": False,
            "errors": [
                {
                    "code": "ZDM-E1001",
                    "kind": "input",
                    "message": str(exc),
                    "line": None,
                    "column": None,
                }
            ],
        }

    return {
        "format": VALIDATION_FORMAT,
        "format_version": VALIDATION_FORMAT_VERSION,
        "valid": True,
        "errors": [],
    }


def capabilities_document() -> dict[str, Any]:
    """Describe stable package capabilities without starting FFmpeg or TTS."""

    plugins = []
    for spec in discover_plugins(builtin_plugin_paths()):
        meta = spec.meta
        plugins.append(
            {
                "id": meta.plugin_id,
                "version": meta.version,
                "kind": meta.kind,
                "provides": sorted(meta.provides),
                "params_schema": _json_value(meta.params_schema),
                "capabilities": _json_value(meta.capabilities),
            }
        )

    plugins.sort(key=lambda item: (str(item["kind"]), str(item["id"])))
    providers = [VoicevoxTTSProvider(), ChatterboxTTSProvider()]
    provider_capabilities = {
        provider.provider_id: provider.capabilities.as_dict() for provider in providers
    }
    return {
        "format": CAPABILITIES_FORMAT,
        "format_version": CAPABILITIES_FORMAT_VERSION,
        "zundamotion_version": __version__,
        "inputs": ["yaml", "markdown"],
        "commands": [
            "render",
            "validate",
            "compile",
            "capabilities",
            "lock",
            "verify-lock",
        ],
        "export_presets": sorted(EXPORT_PRESETS),
        "subtitle_render_modes": ["png", "auto", "ass"],
        "tts": {
            "providers": [provider.provider_id for provider in providers],
            "default_provider": "voicevox",
            "provider_capabilities": provider_capabilities,
        },
        "plugins": plugins,
    }


def _json_value(value: Any) -> Any:
    """Normalize loader/plugin values into deterministic JSON-compatible data."""

    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, set):
        return sorted((_json_value(item) for item in value), key=repr)
    return value
