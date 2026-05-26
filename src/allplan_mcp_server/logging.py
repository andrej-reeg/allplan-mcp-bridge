import logging
import os
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import structlog
from structlog.types import EventDict, Processor


def _redact_value(value: str, root: Path | None) -> str:
    """Redact absolute paths that fall outside root. Returns '<redacted:basename>'."""
    if not os.path.isabs(value):
        return value
    p = Path(value)
    if root is not None:
        try:
            p.resolve().relative_to(root.resolve())
            return value
        except ValueError:
            pass
    return f"<redacted:{p.name}>"


def _make_path_redactor(workspace_root: Path | None, log_level: str) -> Processor:
    def _redact(
        logger: Any, method: str, event_dict: EventDict
    ) -> MutableMapping[str, Any]:
        if log_level == "DEBUG":
            return event_dict
        for key, val in list(event_dict.items()):
            if isinstance(val, (str, Path)):
                event_dict[key] = _redact_value(str(val), workspace_root)
        return event_dict

    return _redact


def configure_logging(
    log_level: str = "INFO",
    workspace_root: Path | None = None,
) -> None:
    """Configure structlog with JSON output and path redaction.

    Must be called once at application startup before any log output is emitted.
    In tests, call with log_level="WARNING" to suppress noise.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    shared_processors: list[Processor] = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _make_path_redactor(workspace_root, log_level.upper()),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)
