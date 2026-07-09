import io
import urllib.error

import pytest

from llm_bench.client import (
    AnthropicClient,
    GeminiClient,
    OpenAICompatibleClient,
    create_client,
)


def test_factory_applies_openai_defaults():
    client = create_client({"provider": "openai", "model": "model-a"}, 10)
    assert isinstance(client, OpenAICompatibleClient)
    assert client.model["base_url"] == "https://api.openai.com/v1"
    assert client.model["api_key_env"] == "OPENAI_API_KEY"
    body = client.body("hello", {"max_output_tokens": 1})
    assert body["max_completion_tokens"] == 1
    assert "max_tokens" not in body


def test_gpt_5_5_omits_unsupported_temperature():
    client = create_client({"provider": "openai", "model": "gpt-5.5"}, 10)
    body = client.body("hello", {"temperature": 0, "max_output_tokens": 16})
    assert "temperature" not in body

    older = create_client({"provider": "openai", "model": "gpt-5.4-mini"}, 10)
    assert older.body("hello", {"temperature": 0})["temperature"] == 0


def test_openrouter_uses_compatible_adapter():
    client = create_client({"provider": "openrouter", "model": "vendor/model"}, 10)
    assert isinstance(client, OpenAICompatibleClient)
    assert client.model["base_url"] == "https://openrouter.ai/api/v1"
    body = client.body("hello", {"max_output_tokens": 1})
    assert body["max_tokens"] == 1
    assert "max_completion_tokens" not in body


def test_xai_uses_native_compatible_api_defaults():
    client = create_client({"provider": "xai", "model": "grok-4.3"}, 10)
    assert isinstance(client, OpenAICompatibleClient)
    assert client.model["base_url"] == "https://api.x.ai/v1"
    assert client.model["api_key_env"] == "XAI_API_KEY"
    assert client.headers("secret") == {"Authorization": "Bearer secret"}
    body = client.body("hello", {"max_output_tokens": 16})
    assert body["max_tokens"] == 16


def test_anthropic_request_and_events():
    client = create_client({"provider": "anthropic", "model": "claude-test"}, 10)
    assert isinstance(client, AnthropicClient)
    body = client.body(
        "hello",
        {"system_prompt": "brief", "temperature": 0, "max_output_tokens": 42},
    )
    assert body["system"] == "brief"
    assert body["max_tokens"] == 42
    text, usage = client.parse_event(
        {"delta": {"text": "hi"}, "usage": {"output_tokens": 2}}
    )
    assert text == "hi"
    assert usage["output_tokens"] == 2


def test_current_anthropic_models_omit_unsupported_temperature():
    for model in ("claude-sonnet-5", "claude-fable-5", "claude-opus-4-8"):
        client = create_client({"provider": "anthropic", "model": model}, 10)
        assert "temperature" not in client.body(
            "hello", {"temperature": 0, "max_output_tokens": 16}
        )


def test_gemini_request_and_events():
    client = create_client({"provider": "gemini", "model": "gemini-test"}, 10)
    assert isinstance(client, GeminiClient)
    body = client.body("hello", {"max_output_tokens": 42})
    assert body["generationConfig"]["maxOutputTokens"] == 42
    text, usage = client.parse_event(
        {
            "candidates": [{"content": {"parts": [{"text": "hi"}]}}],
            "usageMetadata": {
                "promptTokenCount": 1,
                "candidatesTokenCount": 2,
            },
        }
    )
    assert text == "hi"
    assert usage == {"input_tokens": 1, "output_tokens": 2}


def test_custom_compatible_provider():
    client = create_client(
        {
            "provider": "openai_compatible",
            "model": "local",
            "base_url": "http://localhost:1234/v1",
        },
        10,
    )
    assert client.endpoint() == "http://localhost:1234/v1/chat/completions"


@pytest.mark.parametrize(
    ("base_url", "message"),
    [
        ("file:///etc", "http or https"),
        ("https:///missing-host", "http or https"),
        ("https://user:secret@example.test/v1", "embedded credentials"),
    ],
)
def test_custom_provider_rejects_unsafe_base_url(base_url, message):
    with pytest.raises(ValueError, match=message):
        create_client(
            {
                "provider": "openai_compatible",
                "model": "local",
                "base_url": base_url,
            },
            10,
        )


def test_compatible_client_streams_text_and_usage(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter(
                [
                    b'data: {"choices":[{"delta":{"content":"hi"}}]}\n',
                    b'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":1}}\n',
                    b"data: [DONE]\n",
                ]
            )

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request, timeout: FakeResponse()
    )
    sample = create_client({"provider": "openai", "model": "model-a"}, 10).run(
        "hello", {"max_output_tokens": 4}
    )
    assert sample["ok"] is True
    assert sample["response"] == "hi"
    assert sample["input_tokens"] == 3
    assert sample["output_tokens"] == 1
    assert sample["error"] is None


def test_client_reports_missing_key_and_http_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = create_client({"provider": "openai", "model": "model-a"}, 10)
    assert "OPENAI_API_KEY" in client.run("hello", {})["error"]

    monkeypatch.setenv("OPENAI_API_KEY", "test")

    def raise_http_error(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            429,
            "rate limited",
            {},
            io.BytesIO(b'{"error":"rate limited"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", raise_http_error)
    sample = client.run("hello", {})
    assert sample["ok"] is False
    assert sample["error"] == 'HTTP 429: {"error":"rate limited"}'
