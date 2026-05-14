"""Tests for autoplay_sdk.integrations.intercom recipe helpers."""

from __future__ import annotations

import pytest

from autoplay_sdk.integrations.intercom import (
    INTERCOM_API_VERSION_QUICK_REPLY,
    INTERCOM_API_VERSION_UNSTABLE,
    INTERCOM_HTTP_HEADER_VERSION,
    INTERCOM_PROACTIVE_PROMPTS_MAX,
    INTERCOM_PROACTIVE_QUICK_REPLY_DEFAULT_BODY,
    INTERCOM_WEBHOOK_TOPICS,
    IntercomProactivePolicyConfig,
    build_connector_llm_prompt_labels_request_body,
    build_intercom_quick_reply_reply_payload,
    format_reactive_session_link_script,
    intercom_chatbot_webhook_url,
    intercom_connector_llm_prompt_labels_url,
    intercom_quick_reply_http_headers,
    normalize_intercom_quick_reply_labels,
    proactive_trigger_canonical_url_ping_pong,
    proactive_trigger_canonical_url_ping_pong_projects_either_leg,
)


def test_intercom_webhook_topics_contains_created_and_replied():
    assert "conversation.user.created" in INTERCOM_WEBHOOK_TOPICS
    assert "conversation.user.replied" in INTERCOM_WEBHOOK_TOPICS


@pytest.mark.parametrize(
    "host,expected",
    [
        (
            "event-connector-xxxx.onrender.com",
            "https://event-connector-xxxx.onrender.com/chatbot-webhook/acme",
        ),
        (
            "https://event-connector-xxxx.onrender.com",
            "https://event-connector-xxxx.onrender.com/chatbot-webhook/acme",
        ),
        (
            "https://event-connector-xxxx.onrender.com/",
            "https://event-connector-xxxx.onrender.com/chatbot-webhook/acme",
        ),
    ],
)
def test_intercom_chatbot_webhook_url(host: str, expected: str) -> None:
    assert intercom_chatbot_webhook_url(host, "acme") == expected


@pytest.mark.parametrize(
    "host,expected",
    [
        (
            "event-connector-xxxx.onrender.com",
            "https://event-connector-xxxx.onrender.com/intercom/proactive/acme",
        ),
        (
            "https://conn.example.com/",
            "https://conn.example.com/intercom/proactive/acme",
        ),
    ],
)
def test_intercom_connector_llm_prompt_labels_url(host: str, expected: str) -> None:
    assert intercom_connector_llm_prompt_labels_url(host, "acme") == expected


def test_intercom_chatbot_webhook_url_rejects_bad_product_id() -> None:
    with pytest.raises(ValueError, match="product_id"):
        intercom_chatbot_webhook_url("example.com", "bad/id")


def test_format_reactive_session_link_script_contains_paths() -> None:
    s = format_reactive_session_link_script("https://conn.example.com", "prod_1")
    assert "/sessions/link" in s
    assert "prod_1" in s
    assert "https://conn.example.com" in s


def test_version_constants_quick_reply_unstable() -> None:
    assert INTERCOM_API_VERSION_QUICK_REPLY == "Unstable"
    assert INTERCOM_API_VERSION_UNSTABLE == INTERCOM_API_VERSION_QUICK_REPLY


def test_intercom_quick_reply_http_headers() -> None:
    h = intercom_quick_reply_http_headers("  tok  ")
    assert h["Authorization"] == "Bearer tok"
    assert h["Content-Type"] == "application/json"
    assert h[INTERCOM_HTTP_HEADER_VERSION] == "Unstable"


def test_build_connector_llm_prompt_labels_request_body() -> None:
    d = build_connector_llm_prompt_labels_request_body(
        session_id="s1",
        conversation_id="c1",
        action_count=5,
    )
    assert d == {"session_id": "s1", "conversation_id": "c1", "action_count": 5}


def test_normalize_intercom_quick_reply_labels_caps_and_strips() -> None:
    raw = ["  a ", "", "b", "c", "d", "e"]
    assert normalize_intercom_quick_reply_labels(raw) == ["a", "b", "c"]
    assert (
        len(normalize_intercom_quick_reply_labels(raw))
        <= INTERCOM_PROACTIVE_PROMPTS_MAX
    )


def test_build_intercom_quick_reply_reply_payload() -> None:
    p = build_intercom_quick_reply_reply_payload(
        admin_id="adm1",
        body="Hello",
        prompt_labels=["Yes", "No"],
    )
    assert p["message_type"] == "quick_reply"
    assert p["type"] == "admin"
    assert p["admin_id"] == "adm1"
    assert p["body"] == "Hello"
    assert len(p["reply_options"]) == 2
    assert p["reply_options"][0]["text"] == "Yes"
    assert p["reply_options"][0]["uuid"] == "yes"


def test_intercom_proactive_policy_fragment() -> None:
    cfg = IntercomProactivePolicyConfig(
        enabled=False,
        min_actions=3,
        cooldown_seconds=120.0,
    )
    assert cfg.to_integration_config_fragment() == {
        "proactive": {
            "enabled": False,
            "min_actions": 3,
            "cooldown_seconds": 120.0,
        }
    }


@pytest.mark.parametrize(
    "urls,expected",
    [
        (["/a", "/b", "/a"], True),
        (["/a", "/b", "/c"], False),
        (["/a", "/a", "/a"], False),
        ([None, "", "/x", "/y", "/x"], True),
    ],
)
def test_proactive_trigger_canonical_url_ping_pong(
    urls: list,
    expected: bool,
) -> None:
    assert proactive_trigger_canonical_url_ping_pong(urls) is expected


@pytest.mark.parametrize(
    "urls,expected",
    [
        # A→B→A; only B contains "projects"
        (
            [
                "https://app.example/dashboard",
                "https://app.example/projects",
                "https://app.example/dashboard",
            ],
            True,
        ),
        # A→B→A; only A contains "projects"
        (
            [
                "https://app.example/projects",
                "https://app.example/dashboard",
                "https://app.example/projects",
            ],
            True,
        ),
        # Neither leg contains "projects"
        (
            [
                "https://app.example/dashboard",
                "https://app.example/settings",
                "https://app.example/dashboard",
            ],
            False,
        ),
        # Not an A→B→A oscillation
        (["/a", "/b", "/c"], False),
    ],
)
def test_proactive_trigger_canonical_url_ping_pong_projects_either_leg(
    urls: list,
    expected: bool,
) -> None:
    assert (
        proactive_trigger_canonical_url_ping_pong_projects_either_leg(urls) is expected
    )


def test_default_body_constant() -> None:
    assert INTERCOM_PROACTIVE_QUICK_REPLY_DEFAULT_BODY == "Need my expert help?"
