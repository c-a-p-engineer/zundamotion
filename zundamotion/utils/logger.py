import json
import logging
import os
import sys
import time
from datetime import datetime
from functools import wraps
from typing import Optional


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
        return json.dumps(log_record, ensure_ascii=False)


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


def setup_logging(log_json: bool = False, debug_mode: bool = False):
    """
    Sets up the logging configuration.

    Args:
        log_json (bool): If True, logs will be output in JSON format.
        debug_mode (bool): If True, sets the log level to DEBUG.
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


def time_log(logger_instance):
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
            logger_instance.info(f"--- Starting: {log_name} ---")
            result = func(*args, **kwargs)
            end_time = time.time()
            duration = end_time - start_time
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
    if not logging.getLogger("zundamotion").handlers:
        setup_logging()
    return logging.getLogger("zundamotion")


logger = get_logger()
