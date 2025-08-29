import json
import logging
import os
import sys
import time
from datetime import datetime
from functools import wraps
from typing import Any, Dict, Optional


class JsonFormatter(logging.Formatter):
    """
    A custom formatter that outputs logs in JSON format.
    """

    def format(self, record):
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
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
        return f"{self.formatTime(record, self.datefmt)} - {record.levelname} - {kv_string} {record.getMessage()}"


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
    log_json: bool = False, debug_mode: bool = False, log_kv: bool = False
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

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    if log_json:
        console_handler.setFormatter(JsonFormatter())
    elif log_kv:
        console_handler.setFormatter(KVFormatter())
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler
    log_dir = "./logs"
    os.makedirs(log_dir, exist_ok=True)
    log_filename = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3] + ".log"
    file_handler = logging.FileHandler(
        os.path.join(log_dir, log_filename), encoding="utf-8"
    )
    if log_json:
        file_handler.setFormatter(JsonFormatter())
    elif log_kv:
        file_handler.setFormatter(KVFormatter())
    else:
        file_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Suppress other loggers if not in debug mode
    if not debug_mode:  # debug_mode が False の場合のみ抑制
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

    # Set root logger to the same level as zundamotion logger
    logging.root.setLevel(logger.level)

    # Ensure the 'progress' logger also uses the main handler
    progress_logger = logging.getLogger("progress")
    progress_logger.setLevel(logging.INFO)
    if not progress_logger.handlers:
        progress_logger.addHandler(console_handler)
        progress_logger.propagate = (
            False  # Prevent it from sending to root logger again
        )

    return logger


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
    """A decorator to log the execution time of a function."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Check if the function is a method of a class
            if args and hasattr(args[0], "__class__"):
                class_name = args[0].__class__.__name__
                log_name = f"{class_name}.{func.__name__}"
            else:
                log_name = func.__name__

            start_time = time.time()
            if isinstance(logger_instance, KVLogger):
                logger_instance.kv_info(
                    f"--- Starting: {log_name} ---",
                    kv_pairs={"Event": "Start", "Function": log_name},
                )
            else:
                logger_instance.info(f"--- Starting: {log_name} ---")

            result = func(*args, **kwargs)
            end_time = time.time()
            duration = end_time - start_time

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
            return result

        return wrapper

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
