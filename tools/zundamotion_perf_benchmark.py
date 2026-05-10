#!/usr/bin/env python3
"""Run short zundamotion render benchmarks and emit phase timings."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml


TOOL_PATH = Path(__file__).resolve()
ZUNDAMOTION_REPO = TOOL_PATH.parents[1]
BENCHMARK_SCRIPT = Path("scripts/benchmark_short_render.yaml")
VENDORED_BENCHMARK_SCRIPT = Path("vendor/zundamotion") / BENCHMARK_SCRIPT


def find_workspace_root() -> Path:
    candidates = [Path.cwd(), *Path.cwd().parents, ZUNDAMOTION_REPO, *ZUNDAMOTION_REPO.parents]
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if (candidate / VENDORED_BENCHMARK_SCRIPT).exists() or (
            candidate / BENCHMARK_SCRIPT
        ).exists():
            return candidate
    return ZUNDAMOTION_REPO


def find_zundamotion_path(root: Path) -> Path:
    vendored = root / "vendor/zundamotion"
    if (vendored / "zundamotion").exists():
        return vendored
    return ZUNDAMOTION_REPO


ROOT = find_workspace_root()
DEFAULT_SCRIPT = (
    ROOT / VENDORED_BENCHMARK_SCRIPT
    if (ROOT / VENDORED_BENCHMARK_SCRIPT).exists()
    else ROOT / BENCHMARK_SCRIPT
)
PYTHON = Path(sys.executable)
ZUNDAMOTION_PATH = find_zundamotion_path(ROOT)


PHASE_RE = re.compile(r"Phase=(AudioPhase|VideoPhase|FinalizePhase).*Duration=([0-9.]+)s")
TOTAL_RE = re.compile(r"Event=TotalExecutionTime.*Duration=([0-9.]+)s")


def run_text(cmd: list[str], *, env: dict[str, str]) -> str:
    try:
        return subprocess.run(
            cmd,
            cwd=ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except FileNotFoundError:
        return ""


def find_windows_tool(name: str, env: dict[str, str]) -> str | None:
    output = run_text(["cmd.exe", "/c", f"where {name}"], env=env)
    for line in output.splitlines():
        line = line.strip().replace("\r", "")
        if not line:
            continue
        try:
            converted = subprocess.run(
                ["wslpath", line],
                cwd=ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except Exception:
            continue
        if converted and Path(converted).exists():
            return converted
    return None


def ensure_ffmpeg(env: dict[str, str]) -> dict[str, str]:
    if shutil.which("ffmpeg", path=env.get("PATH")) and shutil.which(
        "ffprobe", path=env.get("PATH")
    ):
        return env

    bench_bin = ROOT / ".bench/bin"
    bench_bin.mkdir(parents=True, exist_ok=True)
    for name in ("ffmpeg", "ffprobe"):
        exe = find_windows_tool(name, env)
        if not exe:
            continue
        wrapper = bench_bin / name
        wrapper.write_text(
            "#!/usr/bin/env bash\n"
            "args=()\n"
            "tmpfiles=()\n"
            "for arg in \"$@\"; do\n"
            "  if [[ \"$arg\" == /mnt/* && -f \"$arg\" && \"$arg\" == *.ffconcat* ]]; then\n"
            "    conv=\"${arg}.win\"\n"
            "    : > \"$conv\"\n"
            "    while IFS= read -r line; do\n"
            "      if [[ \"$line\" =~ ^file\\ \\'(/mnt/[^\\']+)\\'$ ]]; then\n"
            "        win=$(wslpath -w \"${BASH_REMATCH[1]}\")\n"
            "        printf \"file '%s'\\n\" \"$win\" >> \"$conv\"\n"
            "      else\n"
            "        printf \"%s\\n\" \"$line\" >> \"$conv\"\n"
            "      fi\n"
            "    done < \"$arg\"\n"
            "    tmpfiles+=(\"$conv\")\n"
            "    args+=(\"$(wslpath -w \"$conv\")\")\n"
            "  elif [[ \"$arg\" == /mnt/* ]]; then\n"
            "    args+=(\"$(wslpath -w \"$arg\")\")\n"
            "  else\n"
            "    args+=(\"$arg\")\n"
            "  fi\n"
            "done\n"
            f'"{exe}" "${{args[@]}}"\n'
            "rc=$?\n"
            "for f in \"${tmpfiles[@]}\"; do rm -f \"$f\"; done\n"
            "exit $rc\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)

    env = dict(env)
    env["PATH"] = f"{bench_bin}:{env.get('PATH', '')}"
    return env


def gpu_snapshot(env: dict[str, str]) -> str:
    smi = shutil.which("nvidia-smi", path=env.get("PATH"))
    if not smi:
        return "nvidia-smi unavailable"
    result = subprocess.run(
        [
            smi,
            "--query-gpu=name,driver_version,utilization.gpu,utilization.memory,memory.used,memory.total",
            "--format=csv,noheader",
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    return (result.stdout or result.stderr).strip() or "nvidia-smi returned no data"


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def write_variant(base_script: Path, out_path: Path, *, overrides: dict[str, Any]) -> Path:
    data = load_yaml(base_script)
    for dotted_key, value in overrides.items():
        target = data
        parts = dotted_key.split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    return out_path


def parse_timings(text: str, wall_time: float) -> dict[str, float]:
    timings: dict[str, float] = {}
    for match in PHASE_RE.finditer(text):
        timings[match.group(1)] = float(match.group(2))
    total_match = None
    for total_match in TOTAL_RE.finditer(text):
        pass
    timings["total"] = float(total_match.group(1)) if total_match else wall_time
    return timings


def run_case(
    *,
    name: str,
    script: Path,
    output_dir: Path,
    cache_mode: str,
    env: dict[str, str],
) -> dict[str, Any]:
    output = output_dir / f"{name}.mp4"
    cmd = [
        str(PYTHON),
        "-m",
        "zundamotion",
        str(script),
        "--project-root",
        str(ROOT),
        "-o",
        str(output),
        "--hw-encoder",
        "cpu",
        "--quality",
        "speed",
        "--jobs",
        "0",
        "--no-voice",
        "--debug-log",
        "--log-kv",
    ]
    if cache_mode == "off":
        cmd.append("--no-cache")
    elif cache_mode == "refresh":
        cmd.append("--cache-refresh")

    before_gpu = gpu_snapshot(env)
    started = time.perf_counter()
    timed_out = False
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=240,
        )
        returncode = proc.returncode
        combined = f"{proc.stdout}\n{proc.stderr}"
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = 124
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        combined = f"{stdout}\n{stderr}"
    elapsed = time.perf_counter() - started
    after_gpu = gpu_snapshot(env)
    timings = parse_timings(combined, elapsed)
    return {
        "name": name,
        "script": str(script),
        "cache_mode": cache_mode,
        "returncode": returncode,
        "timed_out": timed_out,
        "timings": timings,
        "gpu_before": before_gpu,
        "gpu_after": after_gpu,
        "output": str(output),
        "log_tail": "\n".join(combined.splitlines()[-80:]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", type=Path, default=DEFAULT_SCRIPT)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output/perf")
    parser.add_argument(
        "--case",
        choices=["baseline", "task1", "task4", "all"],
        default="all",
    )
    args = parser.parse_args()

    env = dict(os.environ)
    env["PYTHONPATH"] = str(ZUNDAMOTION_PATH)
    env["FFMPEG_LOG_CMD"] = "1"
    env["FFMPEG_PROGRESS_LOG_INTERVAL_SEC"] = "0"
    env["HW_FILTER_MODE"] = "cpu"
    env["ZUNDAMOTION_AUDIO_WORKERS"] = "2"
    env["ZUNDAMOTION_SCENE_WORKERS"] = "1"
    env["SUB_PNG_WORKERS"] = "2"
    env["USE_RAMDISK"] = "0"
    env = ensure_ffmpeg(env)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    variant_dir = args.output_dir / "variants"
    results: list[dict[str, Any]] = []

    if args.case in {"baseline", "all"}:
        results.append(
            run_case(
                name="baseline_cache_off",
                script=args.script,
                output_dir=args.output_dir,
                cache_mode="off",
                env=env,
            )
        )

    if args.case in {"task1", "all"}:
        before = write_variant(
            args.script,
            variant_dir / "task1_before.yaml",
            overrides={"video.subtitle_layer_video": False},
        )
        after = write_variant(
            args.script,
            variant_dir / "task1_after.yaml",
            overrides={"video.subtitle_layer_video": True},
        )
        results.append(
            run_case(
                name="task1_before",
                script=before,
                output_dir=args.output_dir,
                cache_mode="off",
                env=env,
            )
        )
        results.append(
            run_case(
                name="task1_after",
                script=after,
                output_dir=args.output_dir,
                cache_mode="off",
                env=env,
            )
        )

    if args.case in {"task4", "all"}:
        before = write_variant(
            args.script,
            variant_dir / "task4_before.yaml",
            overrides={"system.finalize_cache": False},
        )
        after = write_variant(
            args.script,
            variant_dir / "task4_after.yaml",
            overrides={"system.finalize_cache": True},
        )
        results.append(
            run_case(
                name="task4_before",
                script=before,
                output_dir=args.output_dir,
                cache_mode="refresh",
                env=env,
            )
        )
        results.append(
            run_case(
                name="task4_after_warmup",
                script=after,
                output_dir=args.output_dir,
                cache_mode="refresh",
                env=env,
            )
        )
        results.append(
            run_case(
                name="task4_after_cache_hit",
                script=after,
                output_dir=args.output_dir,
                cache_mode="on",
                env=env,
            )
        )

    report_path = args.output_dir / "benchmark_results.json"
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(item["returncode"] == 0 for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
