"""autoplay_sdk.exceptions — Structured exception hierarchy for the SDK.

Raises these instead of plain ``RuntimeError``/``ValueError`` so callers can
distinguish configuration errors from transient upstream failures without
fragile string matching::

    from autoplay_sdk.exceptions import SdkError, SdkUpstreamError

    try:
        client.run()
    except SdkUpstreamError as exc:
        logger.error("LLM or network failure: %s", exc, exc_info=True)
    except SdkConfigError as exc:
        raise  # programming error — re-raise immediately
"""

from __future__ import annotations


class SdkError(Exception):
    """Base class for all autoplay-sdk errors.

    Catch this to handle any SDK-raised exception in one place.
    """


class SdkConfigError(SdkError):
    """Raised when the SDK is misconfigured.

    Examples: invalid constructor arguments, missing required settings, or
    incompatible option combinations.  These are programming errors that should
    be fixed before deployment — do not silently swallow them.
    """


class SdkUpstreamError(SdkError):
    """Raised when an upstream dependency (LLM, network) fails fatally.

    Returned after ``max_retries`` is exhausted or after a non-retryable HTTP
    error (401, 403, 404).  Transient errors that are successfully retried
    internally do not surface as ``SdkUpstreamError``.
    """


class SdkBufferFullError(SdkError):
    """Raised when the SDK's internal buffer is saturated and cannot accept more events.

    Indicates that the consumer (callback, LLM, vector store) is slower than
    the incoming event rate.  Consider increasing ``max_queue_size``,
    optimising the callback, or horizontally scaling consumers.
    """
