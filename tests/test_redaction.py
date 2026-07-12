import json

from llm_bench.redaction import redact_secrets


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
