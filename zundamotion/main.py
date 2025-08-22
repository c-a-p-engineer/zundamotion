import argparse
import sys
import traceback
from pathlib import Path

# Add the project root to the sys.path to enable absolute imports
# This is necessary when running the module directly or as a package from a higher directory.
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from zundamotion.exceptions import ValidationError
from zundamotion.pipeline import run_generation
from zundamotion.utils.logger import logger, setup_logging


def main():
    """Main function to run the command line interface."""
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
        default="output/final.mp4",
        help="Path to the output video file. Defaults to 'output/final.mp4'.",
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

    args = parser.parse_args()

    # Setup logging based on --log-json argument
    setup_logging(log_json=args.log_json)

    # Ensure output directory exists
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    try:
        logger.info("Video generation started.")
        run_generation(
            args.script_path,
            args.output,
            args.no_cache,
            args.cache_refresh,
            args.jobs,
            args.timeline,
            args.no_timeline,
            args.subtitle_file,
            args.no_subtitle_file,
        )
        logger.info("Video generation completed successfully.")
    except ValidationError as e:
        logger.error(f"Validation Error: {e.message}")
        if e.line_number is not None:
            logger.error(f"  Line: {e.line_number}")
        if e.column_number is not None:
            logger.error(f"  Column: {e.column_number}")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"An unexpected error occurred during generation: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
