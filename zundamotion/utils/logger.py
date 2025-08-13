import json
import logging
import sys
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


def setup_logging(log_json: bool = False):
    """
    Sets up the logging configuration.

    Args:
        log_json (bool): If True, logs will be output in JSON format.
    """
    # Remove all existing handlers to prevent duplicate logs
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    for logger_name in logging.root.manager.loggerDict:
        logger = logging.getLogger(logger_name)
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

    logger = logging.getLogger("zundamotion")
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

    # Suppress other loggers if not in debug mode
    if logger.level > logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

    # Set root logger to INFO to catch everything by default
    logging.root.setLevel(logging.INFO)

    # Ensure the 'progress' logger also uses the main handler
    progress_logger = logging.getLogger("progress")
    progress_logger.setLevel(logging.INFO)
    if not progress_logger.handlers:
        progress_logger.addHandler(console_handler)
        progress_logger.propagate = (
            False  # Prevent it from sending to root logger again
        )

    return logger


# Global logger instance
logger = setup_logging()
