import argparse
from pathlib import Path

from .pipeline import run_generation


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
        )
    except Exception as e:
        print(f"\nAn error occurred during generation: {e}")
        # Consider adding more specific error handling or logging here
        exit(1)


if __name__ == "__main__":
    main()
