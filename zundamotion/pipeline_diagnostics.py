"""Failure-aware pipeline orchestration and partial performance reporting."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from .pipeline import GenerationPipeline
from .utils import perf_stats
from .utils.logger import KVLogger, logger


class DiagnosticGenerationPipeline(GenerationPipeline):
    """Generation pipeline that preserves phase diagnostics when a run aborts."""

    current_phase: str | None = None
    failure_context: dict[str, Any] | None = None

    async def _run_phase(self, phase_name: str, func, *args, **kwargs):
        """Run one phase and persist status/timing even when it raises."""
        started = time.perf_counter()
        status = "running"
        error_type: str | None = None
        error_message: str | None = None
        self.current_phase = phase_name

        current_perf = perf_stats.current_perf_stats()
        run_id = current_perf.run_id if current_perf is not None else "-"
        logger.info("[Phase] run_id=%s name=%s status=start", run_id, phase_name)
        if isinstance(logger, KVLogger):
            logger.kv_info(
                f"--- Starting Phase: {phase_name} ---",
                kv_pairs={"Event": "PhaseStart", "Phase": phase_name},
            )
        else:
            logger.info("--- Starting Phase: %s ---", phase_name)

        try:
            result = await func(*args, **kwargs)
            status = "success"
            return result
        except asyncio.CancelledError as exc:
            status = "cancelled"
            error_type = type(exc).__name__
            error_message = str(exc)
            self.failure_context = {
                "phase": phase_name,
                "status": status,
                "error_type": error_type,
                "error_message": error_message,
            }
            raise
        except BaseException as exc:
            status = "failed"
            error_type = type(exc).__name__
            error_message = str(exc)
            self.failure_context = {
                "phase": phase_name,
                "status": status,
                "error_type": error_type,
                "error_message": error_message,
            }
            logger.exception(
                "[Phase] run_id=%s name=%s status=failed error_type=%s",
                run_id,
                phase_name,
                error_type,
            )
            raise
        finally:
            duration = time.perf_counter() - started
            phase_result: dict[str, Any] = {
                "duration": duration,
                "status": status,
            }
            if error_type is not None:
                phase_result["error_type"] = error_type
            if error_message:
                phase_result["error_message"] = error_message
            self.stats.setdefault("phases", {})[phase_name] = phase_result

            current_perf = perf_stats.current_perf_stats()
            if current_perf is not None:
                current_perf.set_phase_ms(phase_name, duration * 1000.0)
                run_id = current_perf.run_id

            logger.info(
                "[Phase] run_id=%s name=%s status=%s duration_ms=%.1f",
                run_id,
                phase_name,
                status,
                duration * 1000.0,
            )
            if isinstance(logger, KVLogger):
                logger.kv_info(
                    f"--- Finished Phase: {phase_name}. Status: {status}. Duration: {duration:.2f} seconds ---",
                    kv_pairs={
                        "Event": "PhaseFinish",
                        "Phase": phase_name,
                        "Status": status,
                        "Duration": f"{duration:.2f}s",
                        "ErrorType": error_type or "",
                    },
                )
            else:
                logger.info(
                    "--- Finished Phase: %s. Status: %s. Duration: %.2f seconds ---",
                    phase_name,
                    status,
                    duration,
                )
            if status == "success":
                self.current_phase = None

    def write_failure_summary(self, output_path: str | Path, exc: BaseException) -> Path | None:
        """Write a partial PerfSummary after a failed or cancelled render."""
        perf = perf_stats.current_perf_stats()
        if perf is None:
            logger.warning("[PerfSummary] no active performance context for failed render")
            return None

        failure = dict(self.failure_context or {})
        failure.setdefault("phase", self.current_phase)
        failure.setdefault("status", "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed")
        failure.setdefault("error_type", type(exc).__name__)
        failure.setdefault("error_message", str(exc))

        payload = perf.to_dict()
        payload.update(
            {
                "status": failure["status"],
                "failure": failure,
                "phase_results": dict(self.stats.get("phases", {})),
                "output_path": str(output_path),
            }
        )
        self.stats["perf_summary"] = payload

        configured = (
            (self.config.get("system", {}) or {}).get("performance", {})
            if isinstance((self.config.get("system", {}) or {}).get("performance", {}), dict)
            else {}
        )
        raw_path = configured.get("summary_json", "output/perf/perf_summary.json")
        summary_path = Path(raw_path)
        if not summary_path.is_absolute():
            summary_path = Path.cwd() / summary_path

        try:
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            summary_path.write_text(serialized, encoding="utf-8")
            history_path = summary_path.with_name(
                f"{summary_path.stem}.{perf.run_id}{summary_path.suffix}"
            )
            history_path.write_text(serialized, encoding="utf-8")
            logger.error(
                "[Render] run_id=%s status=%s phase=%s error_type=%s",
                perf.run_id,
                failure["status"],
                failure.get("phase") or "unknown",
                failure["error_type"],
            )
            logger.info("[PerfSummary] partial_json=%s", summary_path)
            logger.info("[PerfSummary] partial_history_json=%s", history_path)
            return summary_path
        except Exception as write_error:
            logger.warning(
                "[PerfSummary] failed to write partial json summary: %s",
                write_error,
            )
            return None
