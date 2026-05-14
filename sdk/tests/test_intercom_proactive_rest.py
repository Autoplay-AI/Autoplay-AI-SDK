"""Tests for Intercom REST helpers used by proactive new-thread delivery."""

from __future__ import annotations

import pytest

from autoplay_sdk.integrations.intercom import (
    INTERCOM_API_VERSION_DELETE_CONVERSATION,
    INTERCOM_API_VERSION_REST,
    INTERCOM_CREATE_CONVERSATION_DEFAULT_BODY,
    build_create_user_conversation_payload,
    build_intercom_delete_conversation_request,
    contacts_search_query_email,
    contacts_search_query_external_id,
    conversation_id_from_create_conversation_response,
    first_contact_id_from_search_response,
    intercom_rest_json_headers,
)


def test_build_intercom_delete_conversation_request() -> None:
    url, h = build_intercom_delete_conversation_request("tok", "cv9")
    assert "/conversations/cv9" in url
    assert "retain_metrics=true" in url
    assert h["Authorization"] == "Bearer tok"
    assert h["Intercom-Version"] == INTERCOM_API_VERSION_DELETE_CONVERSATION


def test_intercom_rest_json_headers_default_version() -> None:
    h = intercom_rest_json_headers("tok")
    assert h["Authorization"] == "Bearer tok"
    assert h["Content-Type"] == "application/json"
    assert h["Accept"] == "application/json"
    assert h["Intercom-Version"] == INTERCOM_API_VERSION_REST


def test_intercom_rest_json_headers_override_version() -> None:
    h = intercom_rest_json_headers("tok", api_version="2.10")
    assert h["Intercom-Version"] == "2.10"


def test_contacts_search_query_email() -> None:
    q = contacts_search_query_email("User@Example.com")
    assert q["query"]["field"] == "email"
    assert q["query"]["operator"] == "="
    assert q["query"]["value"] == "User@Example.com"


def test_contacts_search_query_external_id() -> None:
    q = contacts_search_query_external_id("distinct_xyz")
    assert q["query"]["field"] == "external_id"
    assert q["query"]["value"] == "distinct_xyz"


def test_first_contact_id_from_search_response() -> None:
    assert first_contact_id_from_search_response({}) is None
    assert first_contact_id_from_search_response({"data": []}) is None
    assert (
        first_contact_id_from_search_response({"data": [{"id": "abc123"}]}) == "abc123"
    )
    assert first_contact_id_from_search_response({"data": [{}]}) is None


def test_build_create_user_conversation_payload() -> None:
    p = build_create_user_conversation_payload("contact_1", "Hello")
    assert p["from"] == {"type": "user", "id": "contact_1"}
    assert p["body"] == "Hello"
    p2 = build_create_user_conversation_payload("c2", None)
    assert p2["body"] == INTERCOM_CREATE_CONVERSATION_DEFAULT_BODY


@pytest.mark.parametrize(
    "data,expected",
    [
        ({}, None),
        ({"conversation_id": "cv1"}, "cv1"),
        ({"id": "mid1"}, "mid1"),
        ({"conversation": {"id": "nested"}}, "nested"),
        ({"conversation": {"conversation_id": "nc"}}, "nc"),
    ],
)
def test_conversation_id_from_create_conversation_response(
    data: dict, expected: str | None
) -> None:
    assert conversation_id_from_create_conversation_response(data) == expected
