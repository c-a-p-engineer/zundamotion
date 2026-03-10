"""コマンドラインから動画生成パイプラインを実行するエントリポイント。"""

import argparse
import os
import sys
import time
import traceback
from pathlib import Path

repo_root = Path(__file__).parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import asyncio

from zundamotion.exceptions import DependencyError, ValidationError
from zundamotion.pipeline import run_generation
from zundamotion.utils.logger import (
    KVLogger,
    get_logger,
    setup_logging,
    shutdown_logging,
)
from zundamotion.utils.dependency_checks import ensure_ffmpeg_dependencies


def _resolve_project_root(cli_value: str | None) -> Path | None:
    raw = (cli_value or os.getenv("ZUNDAMOTION_PROJECT_ROOT") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _apply_project_root(cli_value: str | None) -> Path | None:
    """Change working directory for relative-path resolution.

    Priority: CLI ``--project-root`` > env ``ZUNDAMOTION_PROJECT_ROOT`` > current cwd.
    Returns the previous working directory when a change is applied.
    """

    project_root = _resolve_project_root(cli_value)
    if project_root is None:
        return None

    resolved = project_root.resolve()
    if not resolved.exists():
        raise ValueError(f"--project-root does not exist: {resolved}")
    if not resolved.is_dir():
        raise ValueError(f"--project-root is not a directory: {resolved}")

    prev = Path.cwd()
    os.chdir(resolved)
    return prev


async def main() -> None:
    """コマンドライン引数を解析し動画生成を実行する。"""
    parser = argparse.ArgumentParser(
        description="Generate a video from a YAML/Markdown script using VOICEVOX and FFmpeg."
    )
    parser.add_argument(
        "script_path",
        type=str,
        help="Path to the input script file (.yaml/.yml or frontmatter .md).",
    )
    parser.add_argument(
        "--project-root",
        type=str,
        default=None,
        help=(
            "Base directory for resolving relative paths (assets/, plugins/, output/, etc.). "
            "Overrides env var ZUNDAMOTION_PROJECT_ROOT."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help=(
            "Path to the output video file. If omitted, a timestamped file like "
            "'output/final_YYYYMMDD_HHMMSS.mp4' is used."
        ),
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="If set, disables caching and regenerates all intermediate files.",
    )
    parser.add_argument(
        "--cache-refresh",
        action="store_true",
        help="If set, regenerates all intermediate files and updates the cache.",
    )
    parser.add_argument(
        "--jobs",
        type=str,
        default="0",
        help='Number of parallel jobs to use for FFmpeg. "auto" for CPU cores.',
    )
    parser.add_argument(
        "--timeline",
        type=str,
        nargs="?",
        const="md",
        default=None,
        help='Enable timeline generation. Optionally specify format: "md", "csv", "both". If no format is specified, "md" is used. Overrides config file setting.',
    )
    parser.add_argument(
        "--no-timeline",
        action="store_true",
        help="Disable timeline generation. Overrides config file setting.",
    )
    parser.add_argument(
        "--subtitle-file",
        type=str,
        nargs="?",
        const="srt",
        default=None,
        help='Enable subtitle file generation. Optionally specify format: "srt", "ass", "both". If no format is specified, "srt" is used. Overrides config file setting.',
    )
    parser.add_argument(
        "--no-subtitle-file",
        action="store_true",
        help="Disable subtitle file generation. Overrides config file setting.",
    )
    parser.add_argument(
        "--log-json",
        action="store_true",
        help="If set, outputs logs in machine-readable JSON format.",
    )
    parser.add_argument(
        "--log-kv",
        action="store_true",
        help="If set, outputs logs in human-readable Key-Value pair format.",
    )
    parser.add_argument(
        "--hw-encoder",
        type=str,
        default="auto",
        choices=["auto", "cpu", "gpu"],
        help="Hardware encoder selection. 'auto' uses GPU if available, 'gpu' forces GPU with CPU fallback, 'cpu' forces CPU.",
    )
    parser.add_argument(
        "--quality",
        type=str,
        default="balanced",
        choices=["speed", "balanced", "quality"],
        help="Encoding quality preset.",
    )
    parser.add_argument(
        "--final-copy-only",
        action="store_true",
        help="Force final concat to use -c copy only; fail if re-encode would be required.",
    )
    parser.add_argument(
        "--plugin-path",
        action="append",
        dest="plugin_paths",
        default=[],
        help="Additional plugin search path (can be repeated).",
    )
    parser.add_argument(
        "--plugin-allow",
        action="append",
        dest="plugin_allow",
        default=[],
        help="Only load plugins with these IDs (can be repeated).",
    )
    parser.add_argument(
        "--plugin-deny",
        action="append",
        dest="plugin_deny",
        default=[],
        help="Deny-list plugin IDs (can be repeated).",
    )
    parser.add_argument(
        "--no-plugins",
        action="store_true",
        help="Disable plugin discovery and use built-in registry only.",
    )
    parser.add_argument(
        "--no-voice",
        action="store_true",
        help="Disable VOICEVOX synthesis and use silent audio with estimated durations.",
    )
    parser.add_argument(
        "--dump-resolved",
        type=str,
        default=None,
        help="Write the resolved YAML (includes/vars expanded) to the given path.",
    )
    parser.add_argument(
        "--debug-include",
        action="store_true",
        help="Print include resolution chains for debugging.",
    )

    args = parser.parse_args()

    try:
        _apply_project_root(args.project_root)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)

    # Setup logging based on --log-json or --log-kv argument
    # If both are set, --log-kv takes precedence for console output
    setup_logging(log_json=args.log_json, log_kv=args.log_kv)
    logger: KVLogger = get_logger()  # Explicitly type hint logger as KVLogger

    # Ensure FFmpeg/ffprobe dependencies are available before proceeding
    try:
        await ensure_ffmpeg_dependencies(logger)
    except DependencyError as e:
        logger.kv_error(
            "必須依存ツールの検証に失敗したため処理を中断します。",
            kv_pairs={
                "Event": "DependencyCheckFailed",
                "Message": str(e),
            },
        )
        sys.exit(1)

    # Resolve default output if not explicitly provided
    if not args.output:
        script_name = os.path.splitext(os.path.basename(args.script_path))[0]
        ts = time.strftime("%Y%m%d_%H%M%S")
        args.output = f"output/{script_name}_{ts}.mp4"

    # Ensure output directory exists
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    start_time = time.time()  # Record start time

    try:
        logger.kv_info(
            "Video generation started.", kv_pairs={"Event": "GenerationStart"}
        )
        await run_generation(
            args.script_path,
            args.output,
            args.no_cache,
            args.cache_refresh,
            args.jobs,
            args.timeline,
            args.no_timeline,
            args.subtitle_file,
            args.no_subtitle_file,
            args.hw_encoder,
            args.quality,
            final_copy_only=args.final_copy_only,
            disable_plugins=args.no_plugins,
            plugin_paths=args.plugin_paths,
            plugin_allow=args.plugin_allow,
            plugin_deny=args.plugin_deny,
            dump_resolved_path=args.dump_resolved,
            debug_include=args.debug_include,
            disable_voice=args.no_voice,
        )
        logger.kv_info(
            "Video generation completed successfully.",
            kv_pairs={"Event": "GenerationSuccess"},
        )
        end_time = time.time()  # Record end time
        elapsed_time = end_time - start_time
        logger.kv_info(
            f"Total execution time: {elapsed_time:.2f} seconds.",
            kv_pairs={
                "Event": "TotalExecutionTime",
                "Duration": f"{elapsed_time:.2f}s",
            },
        )
    except DependencyError as e:
        end_time = time.time()
        elapsed_time = end_time - start_time
        logger.kv_error(
            "依存関係エラーにより処理を中断しました。",
            kv_pairs={
                "Event": "DependencyError",
                "Message": str(e),
            },
        )
        logger.kv_error(
            f"Total execution time before error: {elapsed_time:.2f} seconds.",
            kv_pairs={
                "Event": "TotalExecutionTimeOnError",
                "Duration": f"{elapsed_time:.2f}s",
            },
        )
        sys.exit(1)
    except ValidationError as e:
        end_time = time.time()  # Record end time even on error
        elapsed_time = end_time - start_time
        logger.kv_error(
            f"Validation Error: {e.message}",
            kv_pairs={
                "Event": "ValidationError",
                "Message": e.message,
                "Line": e.line_number,
                "Column": e.column_number,
            },
        )
        logger.kv_error(
            f"Total execution time before error: {elapsed_time:.2f} seconds.",
            kv_pairs={
                "Event": "TotalExecutionTimeOnError",
                "Duration": f"{elapsed_time:.2f}s",
            },
        )
        sys.exit(1)
    except Exception as e:
        end_time = time.time()  # Record end time even on error
        elapsed_time = end_time - start_time
        logger.kv_error(
            f"An unexpected error occurred during generation: {e}",
            kv_pairs={
                "Event": "UnexpectedError",
                "Message": str(e),
                "Traceback": traceback.format_exc(),
            },
        )
        logger.kv_error(
            f"Total execution time before error: {elapsed_time:.2f} seconds.",
            kv_pairs={
                "Event": "TotalExecutionTimeOnError",
                "Duration": f"{elapsed_time:.2f}s",
            },
        )
        sys.exit(1)
    finally:
        shutdown_logging()


def cli() -> None:
    """Synchronous entrypoint for console_scripts and ``python -m zundamotion``."""
    asyncio.run(main())


if __name__ == "__main__":
    cli()
