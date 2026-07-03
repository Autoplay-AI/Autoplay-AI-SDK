"""Pluggable error-reporter seam for the SDK.

The SDK ships standalone and must not depend on any host (connector) module.
To still give the host full traceability into SDK-internal failures, the SDK
calls :func:`report_error` at its swallow points. By default that only logs; a
host process can register a reporter via :func:`set_error_reporter` to also
forward the error to Slack / Bugsnag / any sink.

Contract: reporting is best-effort and never raises into SDK logic.

Host usage::

    from autoplay_sdk.observability import set_error_reporter
    set_error_reporter(lambda event, exc=None, **ctx: my_alert(event, exc, **ctx))

SDK usage::

    from autoplay_sdk.observability import report_error
    try:
        ...
    except Exception as exc:
        report_error("redis write failed", exc, product_id=pid, severity="error")
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Signature: (event: str, exc: BaseException | None, **context) -> None
ErrorReporter = Callable[..., None]

_reporter: Optional[ErrorReporter] = None


def set_error_reporter(reporter: Optional[ErrorReporter]) -> None:
    """Register (or clear with ``None``) the host error reporter."""
    global _reporter
    _reporter = reporter


def report_error(
    event: str,
    exc: BaseException | None = None,
    **context: Any,
) -> None:
    """Report an SDK-internal error. Always logs; forwards if a reporter is set.

    Never raises — a broken reporter must not break SDK logic.
    """
    logger.warning("sdk_error: %s (%s)", event, context, exc_info=exc is not None)
    if _reporter is None:
        return
    try:
        _reporter(event, exc=exc, **context)
    except Exception:
        logger.debug("sdk_error: reporter raised", exc_info=True)
