import json

import pytest

from llm_preflight.providers import PROVIDER_DEFAULTS
from llm_preflight.redaction import mask_base_url, redact_secrets


def test_redact_secrets_masks_sensitive_keys_recursively():
    value = {
        "api_key": "sk-test-redaction-secret",
        "headers": {
            "Authorization": "Bearer header-redaction-secret",
            "X-API-Key": "x-api-redaction-secret",
        },
        "models": [
            {
                "model": "private",
                "custom_token": "token-redaction-secret",
                "nested": {"password": "password-redaction-secret"},
            }
        ],
        "safe": "visible",
    }

    redacted = redact_secrets(value)
    rendered = json.dumps(redacted)

    assert "sk-test-redaction-secret" not in rendered
    assert "header-redaction-secret" not in rendered
    assert "x-api-redaction-secret" not in rendered
    assert "token-redaction-secret" not in rendered
    assert "password-redaction-secret" not in rendered
    assert redacted["safe"] == "visible"
    assert redacted["api_key"] == "[REDACTED]"


def test_redact_secrets_masks_all_custom_header_values():
    value = {
        "headers": {
            "X-Client-Credential": "custom-header-redaction-secret",
            "X-Trace-Mode": "private",
        }
    }

    redacted = redact_secrets(value)

    assert redacted["headers"] == {
        "X-Client-Credential": "[REDACTED]",
        "X-Trace-Mode": "[REDACTED]",
    }


def test_redact_secrets_masks_secret_values_inside_strings():
    redacted = redact_secrets(
        {
            "error": (
                "provider rejected Authorization: Bearer "
                "sk-test-redaction-secret in request"
            )
        }
    )

    assert redacted["error"] == (
        "provider rejected Authorization: Bearer [REDACTED] in request"
    )


def test_redact_secrets_replaces_bare_openai_style_keys():
    redacted = redact_secrets("error: invalid key sk-abc123SECRET")

    assert redacted == "error: invalid key [REDACTED]"


def test_redact_secrets_replaces_gemini_and_xai_style_keys():
    value = "AIza" + "a" * 35 + " and xai-" + "b" * 24

    assert redact_secrets(value) == "[REDACTED] and [REDACTED]"


@pytest.mark.parametrize(
    ("value", "masked"),
    [
        (
            "https://proxy.example:8443/tok/v1;p=1?q=2#f",
            "https://proxy.example:8443/[REDACTED]",
        ),
        ("https://proxy.example/tok", "https://proxy.example/[REDACTED]"),
        ("https://proxy.example/v1?key=tok", "https://proxy.example/[REDACTED]"),
        ("https://u:p@host", "https://host/[REDACTED]"),
        ("https://u:p@host/x", "https://host/[REDACTED]"),
        ("https://host#tok", "https://host"),
        ("https://host", "https://host"),
        ("https://host/", "https://host"),
        ("HTTPS://Host.Example/tok", "https://Host.Example/[REDACTED]"),
        ("http://[::1]:8080/tok", "http://[::1]:8080/[REDACTED]"),
        ("http://my_service:8080/v1", "http://my_service:8080/[REDACTED]"),
    ],
)
def test_mask_base_url_hides_everything_but_scheme_and_authority(value, masked):
    assert mask_base_url(value) == masked


@pytest.mark.parametrize(
    "url", [d["base_url"] for d in PROVIDER_DEFAULTS.values() if "base_url" in d]
)
def test_mask_base_url_keeps_exact_public_routes(url):
    assert mask_base_url(url) == url
    assert mask_base_url(url + "/") == url + "/"
    assert "tok" not in mask_base_url(url + "/tok")
    assert "tok" not in mask_base_url(url + "?key=tok")


@pytest.mark.parametrize(
    "value",
    [
        "https://host;tok=1",
        "https://ho%73t/x",
        "https://höst/tok",
        "http://[bad",
        "host/v1/tok",
        "//host/tok",
        "ftp://host/tok",
        "https://host:port/tok",
        "https://ho st/tok",
        5,
        ["https://host/tok"],
        {"u": "tok"},
    ],
)
def test_mask_base_url_redacts_what_it_cannot_parse(value):
    assert mask_base_url(value) == "[REDACTED]"


def test_mask_base_url_leaves_none_alone():
    assert mask_base_url(None) is None
