"""コマンドラインから動画生成パイプラインを実行するエントリポイント。"""

import argparse
import os
import sys
import time
import traceback
from pathlib import Path

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import asyncio

from zundamotion.exceptions import ValidationError
from zundamotion.pipeline import run_generation
from zundamotion.utils.logger import (
    KVLogger,
    get_logger,
    setup_logging,
    shutdown_logging,
)


async def main() -> None:
    """コマンドライン引数を解析し動画生成を実行する。"""
    parser = argparse.ArgumentParser(
        description="Generate a video from a YAML script using VOICEVOX and FFmpeg."
    )
    parser.add_argument(
        "script_path",
        type=str,
        help="Path to the input YAML script file.",
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

    args = parser.parse_args()

    # Setup logging based on --log-json or --log-kv argument
    # If both are set, --log-kv takes precedence for console output
    setup_logging(log_json=args.log_json, log_kv=args.log_kv)
    logger: KVLogger = get_logger()  # Explicitly type hint logger as KVLogger

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


if __name__ == "__main__":
    asyncio.run(main())  # Run the async main function
