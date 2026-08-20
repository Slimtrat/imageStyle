import logging
from pathlib import Path

from artanimate.observability import (
    PACKAGE_LOGGER_NAME,
    configure_console_logging,
    configure_file_logging,
    detach_handler,
)


def test_console_configuration_is_idempotent() -> None:
    first = configure_console_logging("WARNING")
    second = configure_console_logging(logging.ERROR)
    assert first is second
    assert second.level == logging.ERROR
    detach_handler(first)


def test_rotating_file_receives_package_logs(tmp_path: Path) -> None:
    destination = tmp_path / "artanimate.log"
    handler = configure_file_logging(destination)
    logger = logging.getLogger(f"{PACKAGE_LOGGER_NAME}.test")
    logger.info("render started")
    handler.flush()
    content = destination.read_text(encoding="utf-8")
    assert "INFO" in content
    assert "render started" in content
    detach_handler(handler)
