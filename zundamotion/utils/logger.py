import inspect
import json
import logging
import os
import queue
import sys
import time
import atexit
from contextlib import suppress
from datetime import datetime
from functools import wraps
from logging.handlers import QueueHandler, QueueListener
from typing import Any, Dict, Optional

from tqdm import tqdm


class JsonFormatter(logging.Formatter):
    """
    A custom formatter that outputs logs in JSON format.
    """

    def format(self, record):
        log_record = {
            # Ensure fixed 3-digit milliseconds
            "timestamp": f"{self.formatTime(record, self.datefmt)}.{int(record.msecs):03d}",
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_record["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            log_record["stack_info"] = self.formatStack(record.stack_info)
        # Add custom KV pairs if present
        if hasattr(record, "kv_pairs"):  # Access via record.__dict__
            log_record.update(record.kv_pairs)
        return json.dumps(log_record, ensure_ascii=False)


class KVFormatter(logging.Formatter):
    """
    A custom formatter that outputs logs in Key-Value pair format.
    Example: [Phase=Video][Task=RenderClip][Scene=intro][Idx=3/6] Message
    """

    def format(self, record):
        kv_string = ""
        # Access kv_pairs from record.__dict__
        kv_pairs = getattr(record, "kv_pairs", None)
        if kv_pairs:
            kv_string = "".join([f"[{k}={v}]" for k, v in kv_pairs.items()])
        # Ensure fixed 3-digit milliseconds in timestamp
        ts = self.formatTime(record, self.datefmt)
        return f"{ts}.{int(record.msecs):03d} - {record.levelname} - {kv_string} {record.getMessage()}"


class TqdmLoggingHandler(logging.Handler):
    """A logging handler that writes via tqdm.write to stderr to avoid breaking progress bars."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            # Write alongside tqdm bars (which default to stderr) to keep streams consistent
            tqdm.write(msg, file=sys.stderr)
        except Exception:  # pragma: no cover (best-effort logging)
            # Fallback to plain stderr to avoid losing logs
            try:
                sys.stderr.write(getattr(record, "getMessage", lambda: str(record))())
                sys.stderr.write("\n")
            except Exception:
                pass


class ProgressLogger:
    """
    A simple logger for progress messages, to be replaced by tqdm later.
    """

    def __init__(self, total: int, description: str = ""):
        self.total = total
        self.current = 0
        self.description = description
        self.logger = logging.getLogger("progress")
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter("%(message)s"))
            self.logger.addHandler(handler)

    def update(self, increment: int = 1, message: Optional[str] = None):
        self.current += increment
        percent = (self.current / self.total) * 100
        msg = f"{self.description}: {self.current}/{self.total} ({percent:.1f}%)"
        if message:
            msg += f" - {message}"
        self.logger.info(msg)

    def close(self):
        self.logger.info(f"{self.description}: Completed.")


def setup_logging(
    log_json: bool = False,
    debug_mode: bool = False,
    log_kv: bool = False,
):
    """
    Sets up the logging configuration.

    Args:
        log_json (bool): If True, logs will be output in JSON format.
        debug_mode (bool): If True, sets the log level to DEBUG.
        log_kv (bool): If True, logs will be output in Key-Value pair format.
    """
    logger = logging.getLogger("zundamotion")
    if logger.handlers:
        # Logger is already set up, return it
        return logger

    # Remove all existing handlers to prevent duplicate logs (important for re-runs in some environments)
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    for logger_name in list(logging.Logger.manager.loggerDict.keys()):
        temp_logger = logging.getLogger(logger_name)
        for handler in temp_logger.handlers[:]:
            temp_logger.removeHandler(handler)

    if debug_mode:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)  # Default level

    # Common formatters (fixed 3-digit milliseconds)
    datefmt = "%Y-%m-%d %H:%M:%S"
    if log_json:
        console_formatter: logging.Formatter = JsonFormatter(datefmt=datefmt)
        file_formatter: logging.Formatter = JsonFormatter(datefmt=datefmt)
    elif log_kv:
        console_formatter = KVFormatter(datefmt=datefmt)
        file_formatter = KVFormatter(datefmt=datefmt)
    else:
        fmt = "%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s"
        console_formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)
        file_formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)

    # Handlers to be managed by QueueListener
    console_handler = TqdmLoggingHandler()
    console_handler.setFormatter(console_formatter)

    # File handler
    log_dir = "./logs"
    os.makedirs(log_dir, exist_ok=True)
    log_filename = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3] + ".log"
    file_handler = logging.FileHandler(
        os.path.join(log_dir, log_filename), encoding="utf-8"
    )
    file_handler.setFormatter(file_formatter)

    # Queue-based logging to avoid handler contention and ensure ordering
    q: "queue.Queue[logging.LogRecord]" = queue.Queue(-1)
    qh = QueueHandler(q)
    logger.addHandler(qh)
    logger.propagate = False

    listener = QueueListener(
        q, console_handler, file_handler, respect_handler_level=True
    )
    listener.start()
    # Attach listener to logger for potential teardown if needed
    logger._queue_listener = listener  # type: ignore[attr-defined]

    # Track handlers for shutdown cleanup
    logger._console_handler = console_handler  # type: ignore[attr-defined]
    logger._file_handler = file_handler  # type: ignore[attr-defined]

    # Suppress other loggers if not in debug mode
    if not debug_mode:  # debug_mode が False の場合のみ抑制
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

    # Set root logger to the same level as zundamotion logger
    logging.root.setLevel(logger.level)

    # Ensure the 'progress' logger writes via tqdm as well
    progress_logger = logging.getLogger("progress")
    progress_logger.setLevel(logging.INFO)
    if not progress_logger.handlers:
        progress_logger.addHandler(console_handler)
        progress_logger.propagate = False

    # As an additional safety net, register cleanup on interpreter exit
    try:
        atexit.register(shutdown_logging)
    except Exception:
        pass

    return logger


def shutdown_logging() -> None:
    """Stop logging queue listener and close handlers safely."""
    zunda_logger = logging.getLogger("zundamotion")

    listener = getattr(zunda_logger, "_queue_listener", None)
    if listener is not None:
        with suppress(Exception):
            listener.stop()

    # Close handlers attached to zundamotion logger
    for handler_attr in ("_console_handler", "_file_handler"):
        handler = getattr(zunda_logger, handler_attr, None)
        if handler is not None:
            with suppress(Exception):
                handler.flush()
            with suppress(Exception):
                handler.close()

    for handler in list(zunda_logger.handlers):
        with suppress(Exception):
            handler.flush()
        with suppress(Exception):
            handler.close()
        zunda_logger.removeHandler(handler)

    # Proactively close any active tqdm instances and restore terminal state
    try:
        # Close and clear any live progress bars to ensure clean prompt
        inst = getattr(tqdm, "_instances", None)
        if inst is not None:
            try:
                for bar in list(inst):
                    with suppress(Exception):
                        bar.close()
                inst.clear()
            except Exception:
                pass
        # Ensure cursor is visible and end on a fresh line
        try:
            sys.stderr.write("\x1b[?25h\n")
            sys.stderr.flush()
        except Exception:
            pass
        with suppress(Exception):
            sys.stdout.flush()
        # As a last resort, reset terminal modes (echo, cooked) if available
        try:
            if sys.stdin and sys.stdin.isatty():
                import subprocess as _sp
                _sp.run(["stty", "sane"], check=False, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        except Exception:
            pass
    except Exception:
        pass

    logging.shutdown()


class KVLogger(logging.Logger):
    """
    A custom logger that provides methods for logging with KV pairs.
    """

    def _log_kv(
        self, level, msg, kv_pairs: Optional[Dict[str, Any]] = None, *args, **kwargs
    ):
        if kv_pairs is None:
            kv_pairs = {}
        # Attach kv_pairs to the LogRecord
        kwargs["extra"] = {"kv_pairs": kv_pairs}
        self.log(level, msg, *args, **kwargs)

    def kv_debug(self, msg, kv_pairs: Optional[Dict[str, Any]] = None, *args, **kwargs):
        self._log_kv(logging.DEBUG, msg, kv_pairs, *args, **kwargs)

    def kv_info(self, msg, kv_pairs: Optional[Dict[str, Any]] = None, *args, **kwargs):
        self._log_kv(logging.INFO, msg, kv_pairs, *args, **kwargs)

    def kv_warning(
        self, msg, kv_pairs: Optional[Dict[str, Any]] = None, *args, **kwargs
    ):
        self._log_kv(logging.WARNING, msg, kv_pairs, *args, **kwargs)

    def kv_error(self, msg, kv_pairs: Optional[Dict[str, Any]] = None, *args, **kwargs):
        self._log_kv(logging.ERROR, msg, kv_pairs, *args, **kwargs)

    def kv_critical(
        self, msg, kv_pairs: Optional[Dict[str, Any]] = None, *args, **kwargs
    ):
        self._log_kv(logging.CRITICAL, msg, kv_pairs, *args, **kwargs)


def time_log(logger_instance: logging.Logger):
    """A decorator to log execution time for sync and async functions.

    - Detects coroutine functions and wraps them with an async wrapper that awaits
      the function to ensure accurate timing and correct log ordering.
    - Uses time.monotonic() for reliable duration measurement.
    """

    def decorator(func):
        log_target_name = func.__name__

        def _resolve_name(args):
            if args and hasattr(args[0], "__class__"):
                return f"{args[0].__class__.__name__}.{func.__name__}"
            return log_target_name

        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                log_name = _resolve_name(args)
                start_time = time.monotonic()
                if isinstance(logger_instance, KVLogger):
                    logger_instance.kv_info(
                        f"--- Starting: {log_name} ---",
                        kv_pairs={"Event": "Start", "Function": log_name},
                    )
                else:
                    logger_instance.info(f"--- Starting: {log_name} ---")
                try:
                    return await func(*args, **kwargs)
                finally:
                    duration = time.monotonic() - start_time
                    if isinstance(logger_instance, KVLogger):
                        logger_instance.kv_info(
                            f"--- Finished: {log_name}. Duration: {duration:.2f} seconds ---",
                            kv_pairs={
                                "Event": "Finish",
                                "Function": log_name,
                                "Duration": f"{duration:.2f}s",
                            },
                        )
                    else:
                        logger_instance.info(
                            f"--- Finished: {log_name}. Duration: {duration:.2f} seconds ---"
                        )

            return async_wrapper

        else:

            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                log_name = _resolve_name(args)
                start_time = time.monotonic()
                if isinstance(logger_instance, KVLogger):
                    logger_instance.kv_info(
                        f"--- Starting: {log_name} ---",
                        kv_pairs={"Event": "Start", "Function": log_name},
                    )
                else:
                    logger_instance.info(f"--- Starting: {log_name} ---")
                try:
                    return func(*args, **kwargs)
                finally:
                    duration = time.monotonic() - start_time
                    if isinstance(logger_instance, KVLogger):
                        logger_instance.kv_info(
                            f"--- Finished: {log_name}. Duration: {duration:.2f} seconds ---",
                            kv_pairs={
                                "Event": "Finish",
                                "Function": log_name,
                                "Duration": f"{duration:.2f}s",
                            },
                        )
                    else:
                        logger_instance.info(
                            f"--- Finished: {log_name}. Duration: {duration:.2f} seconds ---"
                        )

            return sync_wrapper

    return decorator


def get_logger():
    """
    Returns the 'zundamotion' logger instance.
    If logging has not been set up yet, it will set it up with default settings.
    """
    # Set the logger class to KVLogger before getting the logger instance
    logging.setLoggerClass(KVLogger)
    logger = logging.getLogger("zundamotion")
    if not logger.handlers:
        setup_logging()
    return logger


# Set the logger class to KVLogger at the module level
logging.setLoggerClass(KVLogger)
logger = get_logger()
