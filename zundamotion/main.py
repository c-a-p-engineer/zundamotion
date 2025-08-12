import argparse
import sys
from pathlib import Path

# Add the project root to the sys.path to enable absolute imports
# This is necessary when running the module directly or as a package from a higher directory.
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from zundamotion.exceptions import ValidationError
from zundamotion.pipeline import run_generation


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
        "--keep-intermediate",
        action="store_true",
        help="If set, keeps the intermediate audio and video clips in an 'intermediate' folder.",
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
        default="1",
        help="Number of parallel jobs for rendering. Use 'auto' to detect CPU cores. Defaults to 1.",
    )

    args = parser.parse_args()

    # Ensure output directory exists
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    try:
        run_generation(
            args.script_path,
            args.output,
            args.keep_intermediate,
            args.no_cache,
            args.cache_refresh,
            args.jobs,
        )
    except ValidationError as e:
        print(f"\nValidation Error: {e.message}")
        if e.line_number is not None:
            print(f"  Line: {e.line_number}")
        if e.column_number is not None:
            print(f"  Column: {e.column_number}")
        exit(1)
    except Exception as e:
        print(f"\nAn unexpected error occurred during generation: {e}")
        exit(1)


if __name__ == "__main__":
    main()
