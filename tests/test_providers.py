"""Tests for autoplay_sdk.providers — ActivityProvider interface, PostHogProvider, AmplitudeProvider."""

from __future__ import annotations

import pytest

from autoplay_sdk.providers import (
    ActivityProvider,
    AmplitudeProvider,
    PostHogProvider,
    ProviderRegistrationBody,
)
from autoplay_sdk.providers.base import ActivityProvider as ActivityProviderBase
from autoplay_sdk.admin.connector_registration_http import (
    redact_connector_error_response_text,
    _SENSITIVE_JSON_KEYS,
)
from autoplay_sdk.integrations.intercom import format_reactive_session_link_script


# ---------------------------------------------------------------------------
# ProviderRegistrationBody
# ---------------------------------------------------------------------------


class TestProviderRegistrationBody:
    def test_fields_stored(self):
        body = ProviderRegistrationBody(
            provider_name="posthog",
            webhook_url="https://conn.example.com/webhook/prod",
            webhook_secret="whsec_test",
            auth_header_name="X-PostHog-Secret",
            sensitive_config_keys=frozenset({"x_posthog_secret"}),
        )
        assert body.provider_name == "posthog"
        assert body.webhook_url == "https://conn.example.com/webhook/prod"
        assert body.webhook_secret == "whsec_test"
        assert body.auth_header_name == "X-PostHog-Secret"
        assert "x_posthog_secret" in body.sensitive_config_keys

    def test_sensitive_config_keys_defaults_to_empty_frozenset(self):
        body = ProviderRegistrationBody(
            provider_name="test",
            webhook_url="https://x.example.com/w/p",
            webhook_secret="s",
            auth_header_name="X-Test-Secret",
        )
        assert body.sensitive_config_keys == frozenset()


# ---------------------------------------------------------------------------
# ActivityProvider — abstract enforcement
# ---------------------------------------------------------------------------


class TestActivityProviderAbstract:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            ActivityProvider()  # type: ignore[abstract]

    def test_concrete_subclass_must_implement_all_methods(self):
        """A partial implementation should raise TypeError on instantiation."""

        class Partial(ActivityProvider):
            @property
            def name(self):
                return "partial"

        with pytest.raises(TypeError):
            Partial()  # missing build_registration_body, get_session_id_js, format_operator_summary


# ---------------------------------------------------------------------------
# PostHogProvider
# ---------------------------------------------------------------------------


class TestPostHogProvider:
    def setup_method(self):
        self.provider = PostHogProvider()

    def test_name(self):
        assert self.provider.name == "posthog"

    def test_is_activity_provider_subclass(self):
        assert isinstance(self.provider, ActivityProviderBase)

    def test_build_registration_body_type(self):
        body = self.provider.build_registration_body(
            "https://conn.example.com/webhook/prod", "whsec_abc"
        )
        assert isinstance(body, ProviderRegistrationBody)

    def test_build_registration_body_provider_name(self):
        body = self.provider.build_registration_body("https://x/w/p", "s")
        assert body.provider_name == "posthog"

    def test_build_registration_body_auth_header(self):
        body = self.provider.build_registration_body("https://x/w/p", "s")
        assert body.auth_header_name == "X-PostHog-Secret"

    def test_build_registration_body_passes_through_secret(self):
        body = self.provider.build_registration_body("https://x/w/p", "my_secret")
        assert body.webhook_secret == "my_secret"

    def test_build_registration_body_sensitive_keys_includes_alias(self):
        body = self.provider.build_registration_body("https://x/w/p", "s")
        assert "x_posthog_secret" in body.sensitive_config_keys

    def test_get_session_id_js_is_string(self):
        js = self.provider.get_session_id_js()
        assert isinstance(js, str)
        assert len(js) > 0

    def test_get_session_id_js_references_posthog(self):
        js = self.provider.get_session_id_js()
        assert "posthog" in js
        assert "get_session_id" in js

    def test_get_session_id_js_handles_undefined_posthog(self):
        """Expression must guard against posthog not being loaded."""
        js = self.provider.get_session_id_js()
        assert "null" in js  # falls back to null when posthog absent

    def test_format_operator_summary_prints_product_id(self, capsys):
        self.provider.format_operator_summary(
            connector_url="https://conn.example.com",
            product_id="my_product",
            webhook_secret="whsec_test",
            integration_type="event_stream",
            unkey_key=None,
            key_id=None,
        )
        captured = capsys.readouterr()
        assert "my_product" in captured.out

    def test_format_operator_summary_prints_posthog_header(self, capsys):
        self.provider.format_operator_summary(
            connector_url="https://conn.example.com",
            product_id="prod",
            webhook_secret="whsec_test",
            integration_type="event_stream",
            unkey_key=None,
            key_id=None,
        )
        captured = capsys.readouterr()
        assert "X-PostHog-Secret" in captured.out
        assert "whsec_test" in captured.out

    def test_format_operator_summary_prints_webhook_url(self, capsys):
        self.provider.format_operator_summary(
            connector_url="https://conn.example.com",
            product_id="prod",
            webhook_secret="s",
            integration_type="event_stream",
            unkey_key=None,
            key_id=None,
        )
        captured = capsys.readouterr()
        assert "https://conn.example.com/webhook/prod" in captured.out

    def test_format_operator_summary_includes_unkey_block_when_present(self, capsys):
        self.provider.format_operator_summary(
            connector_url="https://conn.example.com",
            product_id="prod",
            webhook_secret="s",
            integration_type="event_stream",
            unkey_key="uk_live_abc",
            key_id="key_xyz",
        )
        captured = capsys.readouterr()
        assert "uk_live_abc" in captured.out
        assert "key_xyz" in captured.out

    def test_format_operator_summary_omits_unkey_block_when_none(self, capsys):
        self.provider.format_operator_summary(
            connector_url="https://conn.example.com",
            product_id="prod",
            webhook_secret="s",
            integration_type="event_stream",
            unkey_key=None,
            key_id=None,
        )
        captured = capsys.readouterr()
        assert "Unkey" not in captured.out


# ---------------------------------------------------------------------------
# AmplitudeProvider
# ---------------------------------------------------------------------------


class TestAmplitudeProvider:
    def setup_method(self):
        self.provider = AmplitudeProvider()

    def test_name(self):
        assert self.provider.name == "amplitude"

    def test_is_activity_provider_subclass(self):
        assert isinstance(self.provider, ActivityProviderBase)

    def test_build_registration_body_type(self):
        body = self.provider.build_registration_body(
            "https://conn.example.com/webhook/prod", "whsec_amp"
        )
        assert isinstance(body, ProviderRegistrationBody)

    def test_build_registration_body_provider_name(self):
        body = self.provider.build_registration_body("https://x/w/p", "s")
        assert body.provider_name == "amplitude"

    def test_build_registration_body_auth_header(self):
        body = self.provider.build_registration_body("https://x/w/p", "s")
        # Amplitude uses Bearer token auth, not a custom secret header.
        assert body.auth_header_name == "Authorization"

    def test_build_registration_body_passes_through_secret(self):
        body = self.provider.build_registration_body("https://x/w/p", "amp_bearer")
        assert body.webhook_secret == "amp_bearer"

    def test_build_registration_body_sensitive_keys_includes_bearer_alias(self):
        body = self.provider.build_registration_body("https://x/w/p", "s")
        assert "amplitude_bearer_token" in body.sensitive_config_keys

    def test_get_session_id_js_is_string(self):
        js = self.provider.get_session_id_js()
        assert isinstance(js, str)
        assert len(js) > 0

    def test_get_session_id_js_references_amplitude(self):
        js = self.provider.get_session_id_js()
        assert "amplitude" in js
        assert "getSessionId" in js

    def test_get_session_id_js_stringifies_numeric_result(self):
        js = self.provider.get_session_id_js()
        assert "String(" in js

    def test_get_session_id_js_handles_undefined_amplitude(self):
        js = self.provider.get_session_id_js()
        assert "null" in js

    def test_get_session_id_js_no_posthog_reference(self):
        js = self.provider.get_session_id_js()
        assert "posthog" not in js

    def test_format_operator_summary_prints_product_id(self, capsys):
        self.provider.format_operator_summary(
            connector_url="https://conn.example.com",
            product_id="my_product",
            webhook_secret="whsec_amp",
            integration_type="event_stream",
            unkey_key=None,
            key_id=None,
        )
        captured = capsys.readouterr()
        assert "my_product" in captured.out

    def test_format_operator_summary_prints_bearer_token(self, capsys):
        self.provider.format_operator_summary(
            connector_url="https://conn.example.com",
            product_id="prod",
            webhook_secret="ignored",
            integration_type="event_stream",
            unkey_key="uk_live_bearer",
            key_id="key_123",
        )
        captured = capsys.readouterr()
        assert "uk_live_bearer" in captured.out
        assert "Bearer" in captured.out

    def test_format_operator_summary_prints_ingest_url(self, capsys):
        self.provider.format_operator_summary(
            connector_url="https://conn.example.com",
            product_id="prod",
            webhook_secret="s",
            integration_type="event_stream",
            unkey_key=None,
            key_id=None,
        )
        captured = capsys.readouterr()
        # Amplitude uses /ingest/amplitude/, NOT the PostHog /webhook/ path.
        assert "https://conn.example.com/ingest/amplitude/prod" in captured.out
        assert "/webhook/" not in captured.out

    def test_format_operator_summary_includes_unkey_block_when_present(self, capsys):
        self.provider.format_operator_summary(
            connector_url="https://conn.example.com",
            product_id="prod",
            webhook_secret="s",
            integration_type="event_stream",
            unkey_key="uk_live_amp",
            key_id="key_amp_xyz",
        )
        captured = capsys.readouterr()
        assert "uk_live_amp" in captured.out
        assert "key_amp_xyz" in captured.out

    def test_format_operator_summary_omits_unkey_block_when_none(self, capsys):
        self.provider.format_operator_summary(
            connector_url="https://conn.example.com",
            product_id="prod",
            webhook_secret="s",
            integration_type="event_stream",
            unkey_key=None,
            key_id=None,
        )
        captured = capsys.readouterr()
        assert "Unkey" not in captured.out

    def test_format_operator_summary_mentions_amplitude_event_streaming_path(
        self, capsys
    ):
        self.provider.format_operator_summary(
            connector_url="https://conn.example.com",
            product_id="prod",
            webhook_secret="s",
            integration_type="event_stream",
            unkey_key=None,
            key_id=None,
        )
        captured = capsys.readouterr()
        assert "Amplitude" in captured.out
        assert "Event Streaming" in captured.out

    def test_different_from_posthog_summary(self, capsys):
        self.provider.format_operator_summary(
            connector_url="https://conn.example.com",
            product_id="prod",
            webhook_secret="s",
            integration_type="event_stream",
            unkey_key=None,
            key_id=None,
        )
        captured = capsys.readouterr()
        assert "PostHog" not in captured.out
        assert "X-PostHog-Secret" not in captured.out


# ---------------------------------------------------------------------------
# redact_connector_error_response_text — extra_sensitive_keys
# ---------------------------------------------------------------------------


class TestRedactConnectorErrorResponseText:
    def test_base_sensitive_keys_still_redacted(self):
        result = redact_connector_error_response_text('{"webhook_secret":"abc"}')
        assert "[REDACTED]" in result
        assert "abc" not in result

    def test_x_posthog_secret_redacted_in_base_set(self):
        """x_posthog_secret is kept in the base set so internal error paths redact it."""
        assert "x_posthog_secret" in _SENSITIVE_JSON_KEYS
        result = redact_connector_error_response_text('{"x_posthog_secret":"mysecret"}')
        assert "[REDACTED]" in result
        assert "mysecret" not in result

    def test_extra_sensitive_keys_parameter_redacts_additional_key(self):
        result = redact_connector_error_response_text(
            '{"custom_provider_secret":"val"}',
            extra_sensitive_keys=frozenset({"custom_provider_secret"}),
        )
        assert "[REDACTED]" in result
        assert "val" not in result

    def test_extra_sensitive_keys_does_not_affect_non_sensitive_keys(self):
        result = redact_connector_error_response_text(
            '{"product_id":"my_product"}',
            extra_sensitive_keys=frozenset({"custom_provider_secret"}),
        )
        assert "my_product" in result

    def test_posthog_provider_sensitive_keys_work_with_extra_param(self):
        body = PostHogProvider().build_registration_body("", "")
        result = redact_connector_error_response_text(
            '{"x_posthog_secret":"secret_value"}',
            extra_sensitive_keys=body.sensitive_config_keys,
        )
        assert "[REDACTED]" in result
        assert "secret_value" not in result

    def test_empty_body_returns_empty_string(self):
        assert redact_connector_error_response_text("") == ""

    def test_non_json_body_passes_through_unchanged(self):
        result = redact_connector_error_response_text("not json")
        assert result == "not json"


# ---------------------------------------------------------------------------
# format_reactive_session_link_script — session_id_js parameter
# ---------------------------------------------------------------------------


class TestFormatReactiveSessionLinkScript:
    def test_default_uses_posthog_expression(self):
        script = format_reactive_session_link_script("conn.example.com", "prod")
        assert "posthog.get_session_id()" in script

    def test_default_same_as_passing_posthog_provider_js(self):
        default_script = format_reactive_session_link_script("conn.example.com", "prod")
        explicit_script = format_reactive_session_link_script(
            "conn.example.com",
            "prod",
            session_id_js=PostHogProvider().get_session_id_js(),
        )
        assert default_script == explicit_script

    def test_custom_session_id_js_injected(self):
        script = format_reactive_session_link_script(
            "conn.example.com",
            "prod",
            session_id_js="amplitude.getSessionId()?.toString() ?? null",
        )
        assert "amplitude.getSessionId()" in script
        assert "posthog" not in script

    def test_product_id_in_script(self):
        script = format_reactive_session_link_script("conn.example.com", "my_prod")
        assert "my_prod" in script

    def test_connector_host_in_script(self):
        script = format_reactive_session_link_script("conn.example.com", "prod")
        assert "conn.example.com" in script


# ---------------------------------------------------------------------------
# Top-level package exports
# ---------------------------------------------------------------------------


class TestTopLevelExports:
    def test_activity_provider_exported(self):
        import autoplay_sdk

        assert hasattr(autoplay_sdk, "ActivityProvider")

    def test_posthog_provider_exported(self):
        import autoplay_sdk

        assert hasattr(autoplay_sdk, "PostHogProvider")

    def test_amplitude_provider_exported(self):
        import autoplay_sdk

        assert hasattr(autoplay_sdk, "AmplitudeProvider")

    def test_provider_registration_body_exported(self):
        import autoplay_sdk

        assert hasattr(autoplay_sdk, "ProviderRegistrationBody")

    def test_posthog_provider_in_all(self):
        import autoplay_sdk

        assert "PostHogProvider" in autoplay_sdk.__all__

    def test_amplitude_provider_in_all(self):
        import autoplay_sdk

        assert "AmplitudeProvider" in autoplay_sdk.__all__

    def test_activity_provider_in_all(self):
        import autoplay_sdk

        assert "ActivityProvider" in autoplay_sdk.__all__
