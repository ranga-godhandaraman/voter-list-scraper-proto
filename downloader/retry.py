"""Retry helpers for transient network failures only."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

import requests
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

T = TypeVar("T")


def is_transient(exc: BaseException) -> bool:
    """Return True for timeouts, connection errors, and HTTP 5xx."""
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return 500 <= exc.response.status_code < 600
    # Playwright / generic
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "timeout" in name or "timeout" in msg:
        return True
    if "connection" in msg or "reset" in msg:
        return True
    return False


def with_retries(fn: Callable[[], T], *, attempts: int = 3, label: str = "op") -> T:
    """Run callable with exponential backoff on transient errors."""

    @retry(
        reraise=True,
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=1.5, min=1, max=20),
        retry=retry_if_exception(is_transient),
        before_sleep=before_sleep_log(logger, "WARNING"),
    )
    def _inner() -> T:
        return fn()

    logger.debug("retry-wrapped {}", label)
    return _inner()
