"""Structured logging configuration (structlog over stdlib logging).

Call :func:`configure_logging` once at startup. Use :func:`get_logger` everywhere
else. A ``trace_id`` can be bound via :func:`bind_trace` to thread context
through request -> service -> agent -> tool.
"""
from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def configure_logging(level: str = "INFO", json_logs: bool = False) -> None:
    """Configure structlog + stdlib for the whole process (idempotent)."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[*shared_processors, structlog.processors.format_exc_info, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def bind_trace(trace_id: str, **extra: Any) -> None:
    """Bind trace context for the current async/thread context."""
    structlog.contextvars.bind_contextvars(trace_id=trace_id, **extra)


def clear_trace() -> None:
    structlog.contextvars.clear_contextvars()
