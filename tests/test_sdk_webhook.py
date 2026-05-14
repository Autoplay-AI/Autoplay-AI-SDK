"""Tests for autoplay_sdk.webhook_receiver.WebhookReceiver."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from autoplay_sdk.models import ActionsPayload, SummaryPayload
from autoplay_sdk.webhook_receiver import WebhookReceiver

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SECRET = "test-secret"


def _sign(body: bytes, secret: str = _SECRET) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _actions_body(**overrides) -> bytes:
    payload: dict = {
        "type": "actions",
        "product_id": "p1",
        "session_id": "s1",
        "user_id": None,
        "email": None,
        "actions": [],
        "count": 0,
        "forwarded_at": 1.0,
    }
    payload.update(overrides)
    return json.dumps(payload).encode()


def _summary_body(**overrides) -> bytes:
    payload: dict = {
        "type": "summary",
        "product_id": "p1",
        "session_id": "s1",
        "summary": "User did stuff",
        "replaces": 3,
        "forwarded_at": 1.0,
    }
    payload.update(overrides)
    return json.dumps(payload).encode()


# ---------------------------------------------------------------------------
# verify()
# ---------------------------------------------------------------------------


class TestVerify:
    def test_valid_signature_returns_true(self):
        r = WebhookReceiver(secret=_SECRET)
        body = b"hello"
        assert r.verify(body, _sign(body)) is True

    def test_wrong_signature_returns_false(self):
        r = WebhookReceiver(secret=_SECRET)
        assert r.verify(b"hello", "sha256=deadbeef") is False

    def test_missing_header_returns_false(self):
        r = WebhookReceiver(secret=_SECRET)
        assert r.verify(b"hello", None) is False

    def test_header_without_prefix_returns_false(self):
        r = WebhookReceiver(secret=_SECRET)
        assert r.verify(b"hello", "no-sha256-prefix") is False

    def test_no_secret_accepts_any_body(self):
        r = WebhookReceiver(secret="")
        assert r.verify(b"any body", None) is True

    def test_no_secret_accepts_garbage_signature(self):
        r = WebhookReceiver(secret="")
        assert r.verify(b"any body", "sha256=garbage") is True

    def test_wrong_secret_returns_false(self):
        r = WebhookReceiver(secret="correct-secret")
        body = b"payload"
        sig = _sign(body, secret="wrong-secret")
        assert r.verify(body, sig) is False


# ---------------------------------------------------------------------------
# parse()
# ---------------------------------------------------------------------------


class TestParse:
    def test_parse_actions_returns_actions_payload(self):
        r = WebhookReceiver()
        result = r.parse(_actions_body())
        assert isinstance(result, ActionsPayload)
        assert result.session_id == "s1"
        assert result.product_id == "p1"

    def test_parse_summary_returns_summary_payload(self):
        r = WebhookReceiver()
        result = r.parse(_summary_body())
        assert isinstance(result, SummaryPayload)
        assert result.summary == "User did stuff"
        assert result.replaces == 3

    def test_parse_bad_json_returns_none(self):
        r = WebhookReceiver()
        assert r.parse(b"not json at all") is None

    def test_parse_unknown_type_returns_none(self):
        r = WebhookReceiver()
        body = json.dumps({"type": "heartbeat", "session_id": "s1"}).encode()
        assert r.parse(body) is None

    def test_parse_missing_type_key_returns_none(self):
        r = WebhookReceiver()
        body = json.dumps({"session_id": "s1", "product_id": "p1"}).encode()
        assert r.parse(body) is None

    def test_parse_actions_preserves_session_id(self):
        r = WebhookReceiver()
        result = r.parse(_actions_body(session_id="my-session"))
        assert isinstance(result, ActionsPayload)
        assert result.session_id == "my-session"

    def test_parse_summary_preserves_summary_text(self):
        r = WebhookReceiver()
        result = r.parse(_summary_body(summary="Custom summary"))
        assert isinstance(result, SummaryPayload)
        assert result.summary == "Custom summary"


# ---------------------------------------------------------------------------
# handle() — async
# ---------------------------------------------------------------------------


class TestHandleAsync:
    @pytest.mark.asyncio
    async def test_handle_dispatches_async_actions_callback(self):
        received: list[ActionsPayload] = []

        async def cb(p: ActionsPayload) -> None:
            received.append(p)

        r = WebhookReceiver(secret=_SECRET, on_actions=cb)
        body = _actions_body()
        result = await r.handle(body, _sign(body))

        assert isinstance(result, ActionsPayload)
        assert len(received) == 1
        assert received[0].session_id == "s1"

    @pytest.mark.asyncio
    async def test_handle_dispatches_async_summary_callback(self):
        received: list[SummaryPayload] = []

        async def cb(p: SummaryPayload) -> None:
            received.append(p)

        r = WebhookReceiver(secret=_SECRET, on_summary=cb)
        body = _summary_body()
        result = await r.handle(body, _sign(body))

        assert isinstance(result, SummaryPayload)
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_handle_dispatches_sync_actions_callback(self):
        """handle() transparently supports synchronous callbacks."""
        received: list[ActionsPayload] = []

        def cb(p: ActionsPayload) -> None:
            received.append(p)

        r = WebhookReceiver(secret=_SECRET, on_actions=cb)
        body = _actions_body()
        await r.handle(body, _sign(body))
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_handle_raises_value_error_on_bad_signature(self):
        r = WebhookReceiver(secret=_SECRET)
        with pytest.raises(ValueError, match="Invalid"):
            await r.handle(_actions_body(), "sha256=badbad")

    @pytest.mark.asyncio
    async def test_handle_raises_value_error_on_missing_signature(self):
        r = WebhookReceiver(secret=_SECRET)
        with pytest.raises(ValueError, match="Invalid"):
            await r.handle(_actions_body(), None)

    @pytest.mark.asyncio
    async def test_handle_no_secret_accepts_unsigned_request(self):
        received: list = []
        r = WebhookReceiver(secret="", on_actions=lambda p: received.append(p))
        await r.handle(_actions_body())
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_handle_callback_error_does_not_propagate(self):
        async def bad_cb(p):
            raise RuntimeError("boom")

        r = WebhookReceiver(secret=_SECRET, on_actions=bad_cb)
        body = _actions_body()
        result = await r.handle(body, _sign(body))
        assert isinstance(result, ActionsPayload)

    @pytest.mark.asyncio
    async def test_handle_returns_none_for_unknown_event_type(self):
        r = WebhookReceiver(secret="")
        body = json.dumps({"type": "unknown"}).encode()
        result = await r.handle(body)
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_returns_none_for_bad_json(self):
        r = WebhookReceiver(secret="")
        result = await r.handle(b"not json")
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_no_matching_callback_still_returns_payload(self):
        """Payload is returned even when no callback is registered."""
        r = WebhookReceiver(secret="")
        body = _actions_body()
        result = await r.handle(body)
        assert isinstance(result, ActionsPayload)


# ---------------------------------------------------------------------------
# handle_sync()
# ---------------------------------------------------------------------------


class TestHandleSync:
    def test_handle_sync_dispatches_actions_callback(self):
        received: list[ActionsPayload] = []
        r = WebhookReceiver(secret=_SECRET, on_actions=lambda p: received.append(p))
        body = _actions_body()
        result = r.handle_sync(body, _sign(body))
        assert isinstance(result, ActionsPayload)
        assert len(received) == 1

    def test_handle_sync_dispatches_summary_callback(self):
        received: list[SummaryPayload] = []
        r = WebhookReceiver(secret=_SECRET, on_summary=lambda p: received.append(p))
        body = _summary_body()
        result = r.handle_sync(body, _sign(body))
        assert isinstance(result, SummaryPayload)
        assert len(received) == 1

    def test_handle_sync_raises_value_error_on_bad_signature(self):
        r = WebhookReceiver(secret=_SECRET)
        with pytest.raises(ValueError, match="Invalid"):
            r.handle_sync(_actions_body(), "sha256=wrong")

    def test_handle_sync_raises_value_error_on_missing_signature(self):
        r = WebhookReceiver(secret=_SECRET)
        with pytest.raises(ValueError, match="Invalid"):
            r.handle_sync(_actions_body(), None)

    def test_handle_sync_callback_error_does_not_propagate(self):
        def bad_cb(p):
            raise RuntimeError("boom")

        r = WebhookReceiver(secret=_SECRET, on_actions=bad_cb)
        body = _actions_body()
        result = r.handle_sync(body, _sign(body))
        assert isinstance(result, ActionsPayload)

    def test_handle_sync_returns_none_for_bad_json(self):
        r = WebhookReceiver(secret="")
        assert r.handle_sync(b"not json") is None

    def test_handle_sync_no_callback_still_returns_payload(self):
        r = WebhookReceiver(secret="")
        body = _actions_body()
        result = r.handle_sync(body)
        assert isinstance(result, ActionsPayload)

    def test_handle_sync_no_secret_accepts_unsigned_request(self):
        received: list = []
        r = WebhookReceiver(secret="", on_actions=lambda p: received.append(p))
        r.handle_sync(_actions_body())
        assert len(received) == 1


# ---------------------------------------------------------------------------
# Builder interface
# ---------------------------------------------------------------------------


class TestBuilder:
    def test_on_actions_returns_self_for_chaining(self):
        r = WebhookReceiver()
        assert r.on_actions(lambda p: None) is r

    def test_on_summary_returns_self_for_chaining(self):
        r = WebhookReceiver()
        assert r.on_summary(lambda p: None) is r

    def test_repr_shows_secret_set(self):
        assert "secret=set" in repr(WebhookReceiver(secret="s"))

    def test_repr_shows_secret_unset(self):
        assert "secret=unset" in repr(WebhookReceiver(secret=""))

    def test_repr_shows_callback_presence(self):
        r = WebhookReceiver(on_actions=lambda p: None)
        assert "on_actions=True" in repr(r)
        assert "on_summary=False" in repr(r)
