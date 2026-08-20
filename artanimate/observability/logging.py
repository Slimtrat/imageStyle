from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys


PACKAGE_LOGGER_NAME = "artanimate"
_CONSOLE_FORMAT = "%(asctime)s  %(levelname)-7s  %(name)s — %(message)s"
_FILE_FORMAT = "%(asctime)s.%(msecs)03d  %(levelname)-8s  %(name)s — %(message)s"


def _package_logger() -> logging.Logger:
    logger = logging.getLogger(PACKAGE_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    if not any(isinstance(handler, logging.NullHandler) for handler in logger.handlers):
        logger.addHandler(logging.NullHandler())
    return logger


def _coerce_level(level: int | str) -> int:
    if isinstance(level, int):
        return level
    value = logging.getLevelName(level.upper())
    if not isinstance(value, int):
        raise ValueError(f"Niveau de log inconnu : {level}")
    return value


def attach_handler(handler: logging.Handler, level: int | str = logging.INFO) -> logging.Handler:
    handler.setLevel(_coerce_level(level))
    logger = _package_logger()
    if handler not in logger.handlers:
        logger.addHandler(handler)
    return handler


def detach_handler(handler: logging.Handler) -> None:
    logger = _package_logger()
    logger.removeHandler(handler)
    handler.close()


def configure_console_logging(level: int | str = logging.INFO) -> logging.Handler:
    logger = _package_logger()
    for handler in logger.handlers:
        if getattr(handler, "_artanimate_destination", None) == "console":
            handler.setLevel(_coerce_level(level))
            return handler
    handler = logging.StreamHandler(sys.stderr)
    handler._artanimate_destination = "console"  # type: ignore[attr-defined]
    handler.setFormatter(logging.Formatter(_CONSOLE_FORMAT, datefmt="%H:%M:%S"))
    return attach_handler(handler, level)


def configure_file_logging(
    path: str | Path,
    level: int | str = logging.INFO,
    max_bytes: int = 2_000_000,
    backups: int = 3,
) -> logging.Handler:
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    marker = f"file:{destination}"
    logger = _package_logger()
    for handler in logger.handlers:
        if getattr(handler, "_artanimate_destination", None) == marker:
            handler.setLevel(_coerce_level(level))
            return handler
    handler = RotatingFileHandler(
        destination,
        maxBytes=max_bytes,
        backupCount=backups,
        encoding="utf-8",
    )
    handler._artanimate_destination = marker  # type: ignore[attr-defined]
    handler.setFormatter(logging.Formatter(_FILE_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
    return attach_handler(handler, level)


_package_logger()
