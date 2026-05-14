"""Tests for autoplay_sdk.exceptions — structured exception hierarchy.

One test per exception type, asserting the correct subclass relationship.
Also verifies that the exceptions are raised by the wired call sites.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_SDK_DIR = Path(__file__).parent.parent / "src" / "customer_sdk"
sys.path.insert(0, str(_SDK_DIR))

from autoplay_sdk.exceptions import (  # noqa: E402
    SdkBufferFullError,
    SdkConfigError,
    SdkError,
    SdkUpstreamError,
)


# ---------------------------------------------------------------------------
# Hierarchy
# ---------------------------------------------------------------------------


class TestExceptionHierarchy:
    def test_sdk_error_is_exception(self):
        assert issubclass(SdkError, Exception)

    def test_sdk_config_error_is_sdk_error(self):
        assert issubclass(SdkConfigError, SdkError)

    def test_sdk_upstream_error_is_sdk_error(self):
        assert issubclass(SdkUpstreamError, SdkError)

    def test_sdk_buffer_full_error_is_sdk_error(self):
        assert issubclass(SdkBufferFullError, SdkError)

    def test_raise_sdk_config_error(self):
        with pytest.raises(SdkConfigError):
            raise SdkConfigError("bad config")

    def test_raise_sdk_upstream_error(self):
        with pytest.raises(SdkUpstreamError):
            raise SdkUpstreamError("upstream down")

    def test_raise_sdk_buffer_full_error(self):
        with pytest.raises(SdkBufferFullError):
            raise SdkBufferFullError("buffer saturated")

    def test_catch_by_base_class(self):
        """All sdk exceptions are catchable via SdkError."""
        for exc_cls in (SdkConfigError, SdkUpstreamError, SdkBufferFullError):
            with pytest.raises(SdkError):
                raise exc_cls("test")


# ---------------------------------------------------------------------------
# Call-site wiring
# ---------------------------------------------------------------------------


class TestExceptionWiring:
    def test_session_summarizer_threshold_raises_sdk_config_error(self):
        """SessionSummarizer raises SdkConfigError (not ValueError) for bad threshold."""
        from autoplay_sdk.summarizer import SessionSummarizer

        with pytest.raises(SdkConfigError):
            SessionSummarizer(llm=MagicMock(), threshold=0)

    def test_async_session_summarizer_threshold_raises_sdk_config_error(self):
        """AsyncSessionSummarizer raises SdkConfigError for threshold < 1."""
        from autoplay_sdk.summarizer import AsyncSessionSummarizer

        with pytest.raises(SdkConfigError):
            AsyncSessionSummarizer(llm=MagicMock(), threshold=-1)

    def test_rag_pipeline_non_callable_embed_raises_sdk_config_error(self):
        """RagPipeline raises SdkConfigError when embed is not callable."""
        from autoplay_sdk.rag import RagPipeline

        with pytest.raises(SdkConfigError):
            RagPipeline(embed="not_a_callable", upsert=MagicMock())

    def test_rag_pipeline_non_callable_upsert_raises_sdk_config_error(self):
        """RagPipeline raises SdkConfigError when upsert is not callable."""
        from autoplay_sdk.rag import RagPipeline

        with pytest.raises(SdkConfigError):
            RagPipeline(embed=MagicMock(), upsert=42)

    def test_async_rag_pipeline_non_callable_embed_raises_sdk_config_error(self):
        """AsyncRagPipeline raises SdkConfigError when embed is not callable."""
        from autoplay_sdk.rag import AsyncRagPipeline

        with pytest.raises(SdkConfigError):
            AsyncRagPipeline(embed=None, upsert=MagicMock())

    def test_exceptions_exported_from_init(self):
        """All four exception classes are accessible via the top-level package."""
        import autoplay_sdk

        assert autoplay_sdk.SdkError is SdkError
        assert autoplay_sdk.SdkConfigError is SdkConfigError
        assert autoplay_sdk.SdkUpstreamError is SdkUpstreamError
        assert autoplay_sdk.SdkBufferFullError is SdkBufferFullError
