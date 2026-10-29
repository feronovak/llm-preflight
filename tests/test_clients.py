import hashlib
import io
import json
import urllib.error

import pytest

from llm_preflight.client import (
    MAX_RESPONSE_BYTES,
    AnthropicClient,
    GeminiClient,
    OpenAICompatibleClient,
    OpenAIResponsesClient,
    _retry_delay,
    create_client,
)


def test_openai_responses_adapter_uses_minimal_safe_probe_request():
    client = create_client(
        {"provider": "openai", "model": "gpt-test", "adapter": "openai_responses"},
        10,
    )

    assert isinstance(client, OpenAIResponsesClient)
    assert client.endpoint() == "https://api.openai.com/v1/responses"
    assert client.body("Reply with OK.", {"max_output_tokens": 32}) == {
        "model": "gpt-test",
        "input": "Reply with OK.",
        "max_output_tokens": 32,
        "store": False,
    }


def test_openai_responses_adapter_preserves_system_prompt_for_contract_checks():
    client = create_client(
        {"provider": "openai", "model": "gpt-test", "adapter": "openai_responses"},
        10,
    )

    body = client.body(
        "A customer was charged twice. Route the ticket.",
        {
            "system_prompt": "Return only the support queue label.",
            "max_output_tokens": 128,
        },
    )

    assert body["input"] == "A customer was charged twice. Route the ticket."
    assert body["instructions"] == "Return only the support queue label."


@pytest.fixture(autouse=True)
def _resolve_provider_hosts_to_a_public_address(monkeypatch):
    """Keep unit fixtures independent from the machine's DNS configuration."""
    monkeypatch.setattr(
        "llm_preflight.security.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("8.8.8.8", 443))],
    )
    monkeypatch.setattr(
        "llm_preflight.client.open_public_url",
        lambda request, timeout: urllib.request.urlopen(request, timeout),
    )


def test_factory_applies_openai_defaults():
    client = create_client({"provider": "openai", "model": "model-a"}, 10)
    assert isinstance(client, OpenAICompatibleClient)
    assert client.model["base_url"] == "https://api.openai.com/v1"
    assert client.model["api_key_env"] == "OPENAI_API_KEY"
    body = client.body("hello", {"max_output_tokens": 1})
    assert body["max_completion_tokens"] == 1
    assert "max_tokens" not in body


@pytest.mark.parametrize(
    "provider", ["openai", "gemini", "openrouter", "xai", "deepseek", "qwen"]
)
def test_non_anthropic_clients_apply_the_safe_default_output_limit(provider):
    client = create_client({"provider": provider, "model": "model-a"}, 10)

    body = client.body("hello", {})

    if provider == "gemini":
        assert body["generationConfig"]["maxOutputTokens"] == 256
    else:
        parameter = client.model.get("max_tokens_parameter", "max_tokens")
        assert body[parameter] == 256


def test_runtime_url_validation_failure_becomes_a_normal_api_failure(monkeypatch):
    client = OpenAICompatibleClient(
        {
            "provider": "openai_compatible",
            "model": "broken",
            "base_url": "https://api.example.test/v1",
        },
        10,
    )
    monkeypatch.setattr(
        "llm_preflight.client.require_http_url",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("URL host could not be resolved: 'api.example.test'")
        ),
    )

    result = client.run("Reply with ok.", {"retry": {"max_attempts": 1}})

    assert result["ok"] is False
    assert result["failure_category"] == "provider_error"


@pytest.mark.parametrize(
    "model",
    [
        "gpt-5.5",
        "gpt-5.6-luna",
        "gpt-5.6-terra",
        "gpt-5.6-sol",
        "gpt-6-astra",
        "gpt-6.1-sol",
        "gpt-6.1-terra",
        "gpt-6-sol",
        "gpt-6-luna",
    ],
)
def test_current_gpt_models_omit_unsupported_temperature(model):
    client = create_client({"provider": "openai", "model": model}, 10)
    body = client.body("hello", {"temperature": 0, "max_output_tokens": 16})
    assert "temperature" not in body

    older = create_client({"provider": "openai", "model": "gpt-5.4-mini"}, 10)
    assert older.body("hello", {"temperature": 0})["temperature"] == 0


@pytest.mark.parametrize(
    "model_id,expected_cost", [("gpt-6.1-sol", 0.00073), ("gpt-6.1-terra", 0.000365)]
)
@pytest.mark.parametrize("adapter", ["openai_compatible_chat", "openai_responses"])
def test_gpt_6_1_protocol_preserves_cache_reads_and_writes(
    monkeypatch, adapter, model_id, expected_cost
):
    captured = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            event = {
                "choices": [{"delta": {"content": "billing"}}],
                "usage": {
                    "prompt_tokens": 1000,
                    "prompt_tokens_details": {
                        "cached_tokens": 800,
                        "cache_write_tokens": 100,
                    },
                    "completion_tokens": 20,
                },
            }
            return iter([f"data: {json.dumps(event)}\n".encode()])

        def read(self, *args):
            return json.dumps(
                {
                    "status": "completed",
                    "output": [
                        {"content": [{"type": "output_text", "text": "billing"}]}
                    ],
                    "usage": {
                        "input_tokens": 1000,
                        "input_tokens_details": {
                            "cached_tokens": 800,
                            "cache_write_tokens": 100,
                        },
                        "output_tokens": 20,
                    },
                }
            ).encode()

    def transport(request, timeout):
        captured.append(json.loads(request.data))
        return Response()

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", transport)
    client = create_client(
        {"provider": "openai", "model": model_id, "adapter": adapter}, 10
    )

    sample = client.run(
        "I was charged twice.",
        {
            "temperature": 0,
            "system_prompt": "Return only the queue label.",
            "max_output_tokens": 512,
            "retry": {"max_attempts": 1},
        },
    )

    assert sample["ok"] is True
    assert sample["response"] == "billing"
    assert sample["input_tokens"] == 1000
    assert sample["cached_input_tokens"] == 800
    assert sample["cache_write_input_tokens"] == 100
    assert sample["output_tokens"] == 20
    assert captured[0]["model"] == model_id
    assert "temperature" not in captured[0]

    from llm_preflight.metrics import summarize
    from llm_preflight.pricing import apply_public_pricing

    summary = summarize([sample], apply_public_pricing(client.model))
    assert summary["cache_write_input_tokens"] == 100
    assert summary["estimated_cost_usd"] == pytest.approx(expected_cost)


def test_glm_5_3_native_stream_preserves_usage_and_ignores_reasoning_text(monkeypatch):
    from llm_preflight.metrics import summarize
    from llm_preflight.pricing import apply_public_pricing

    captured = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            events = [
                {"choices": [{"delta": {"reasoning_content": "private reasoning"}}]},
                {"choices": [{"delta": {"content": "billing"}}]},
                {
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 1000,
                        "prompt_tokens_details": {"cached_tokens": 800},
                        "completion_tokens": 100,
                    },
                },
            ]
            return iter(
                [f"data: {json.dumps(e)}\n".encode() for e in events]
                + [b"data: [DONE]\n"]
            )

    def transport(request, timeout):
        captured.append(request)
        return Response()

    monkeypatch.setenv("ZAI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", transport)
    client = create_client({"provider": "zai", "model": "glm-5.3"}, 10)
    sample = client.run(
        "Charged twice",
        {
            "temperature": 0,
            "max_output_tokens": 512,
            "system_prompt": "Return the queue",
            "provider_options": {"zai": {"reasoning_effort": "low"}},
        },
    )
    assert sample["ok"] is True
    assert sample["response"] == "billing"
    assert sample["input_tokens"] == 1000
    assert sample["cached_input_tokens"] == 800
    assert sample["output_tokens"] == 100
    assert captured[0].full_url == "https://api.z.ai/api/paas/v4/chat/completions"
    assert captured[0].get_header("Authorization") == "Bearer test"
    body = json.loads(captured[0].data)
    assert body["model"] == "glm-5.3"
    assert body["max_tokens"] == 512
    assert body["temperature"] == 0
    assert body["reasoning_effort"] == "low"
    assert body["messages"][0] == {"role": "system", "content": "Return the queue"}
    assert "stream_options" not in body
    assert summarize([sample], apply_public_pricing(client.model))[
        "estimated_cost_usd"
    ] == pytest.approx(0.000928)


@pytest.mark.parametrize(
    "provider_options",
    [
        {"thinking": {"type": "disabled"}},
        {"reasoning_effort": "none"},
        {"reasoning_effort": "medium"},
    ],
)
def test_glm_5_3_rejects_unsupported_reasoning_before_transport(
    monkeypatch, provider_options
):
    def unexpected_transport(*args, **kwargs):
        pytest.fail("invalid GLM reasoning must fail before transport")

    monkeypatch.setenv("ZAI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", unexpected_transport)
    client = create_client({"provider": "zai", "model": "glm-5.3"}, 10)
    sample = client.run(
        "hello",
        {"retry": {"max_attempts": 1}, "provider_options": {"zai": provider_options}},
    )
    assert sample["ok"] is False
    assert "reasoning" in sample["error"]


def test_glm_5_3_rejects_image_input():
    client = create_client({"provider": "zai", "model": "glm-5.3"}, 10)
    with pytest.raises(ValueError, match="text-only"):
        client.body("hello", {"input_images": [{"path": "does-not-exist.png"}]})


def test_model_can_explicitly_override_temperature_support():
    unsupported = create_client(
        {
            "provider": "openai",
            "model": "custom-no-temp",
            "capabilities": {"temperature": False},
        },
        10,
    )
    assert "temperature" not in unsupported.body("hello", {"temperature": 0.5})

    supported = create_client(
        {"provider": "openai", "model": "gpt-5.5", "supports_temperature": True},
        10,
    )
    assert supported.body("hello", {"temperature": 0.5})["temperature"] == 0.5


def test_deepseek_uses_the_openai_compatible_chat_adapter():
    client = create_client({"provider": "deepseek", "model": "deepseek-flash"}, 10)

    assert isinstance(client, OpenAICompatibleClient)
    assert client.model["base_url"] == "https://api.deepseek.com/v1"
    assert client.model["api_key_env"] == "DEEPSEEK_API_KEY"
    assert client.endpoint() == "https://api.deepseek.com/v1/chat/completions"


def test_qwen_uses_the_model_studio_compatible_chat_adapter():
    client = create_client({"provider": "qwen", "model": "qwen3.8-max"}, 10)

    assert isinstance(client, OpenAICompatibleClient)
    assert client.model["base_url"] == (
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    )
    assert client.model["api_key_env"] == "DASHSCOPE_API_KEY"


@pytest.mark.parametrize("model", ["qwen3.8-max", "qwen3.8-max-0902", "qwen3.8-flash"])
@pytest.mark.parametrize("limit", [None, 1, 4096])
def test_native_qwen_3_8_caps_reasoning_and_answer_tokens_together(model, limit):
    client = create_client({"provider": "qwen", "model": model}, 10)
    options = {
        "provider_options": {
            "qwen": {"enable_thinking": True, "reasoning_effort": "low"}
        }
    }
    if limit is not None:
        options["max_output_tokens"] = limit

    body = client.body("Reply with ok", options)

    assert body["max_completion_tokens"] == (256 if limit is None else limit)
    assert "max_tokens" not in body
    assert body["enable_thinking"] is True
    assert body["reasoning_effort"] == "low"


@pytest.mark.parametrize(
    "provider,model,key,endpoint,options,parameter,cached_price,cost",
    [
        (
            "zai",
            "glm-5.3",
            "ZAI_API_KEY",
            "https://api.z.ai/api/paas/v4/chat/completions",
            {"thinking": {"type": "enabled"}, "reasoning_effort": "low"},
            "max_tokens",
            0.26,
            0.001016,
        ),
        (
            "deepseek",
            "deepseek-flash",
            "DEEPSEEK_API_KEY",
            "https://api.deepseek.com/v1/chat/completions",
            {"thinking": {"type": "enabled"}, "reasoning_effort": "low"},
            "max_tokens",
            0.006,
            0.0002088,
        ),
        (
            "qwen",
            "qwen3.8-max",
            "DASHSCOPE_API_KEY",
            "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
            {"enable_thinking": True, "reasoning_effort": "low"},
            "max_completion_tokens",
            None,
            None,
        ),
    ],
)
@pytest.mark.parametrize("reported_usage", [True, False])
def test_native_chinese_models_stream_answer_and_usage_without_openrouter(
    monkeypatch,
    provider,
    model,
    key,
    endpoint,
    options,
    parameter,
    cached_price,
    cost,
    reported_usage,
):
    from llm_preflight.metrics import summarize
    from llm_preflight.pricing import apply_public_pricing

    captured = []
    events = [
        {
            "choices": [
                {"delta": {"reasoning_content": "private reasoning, not the answer"}}
            ]
        },
        {"choices": [{"delta": {"content": '{"queue":'}}]},
        {"choices": [{"delta": {"content": '"billing"}'}, "finish_reason": "stop"}]},
    ]
    if reported_usage:
        usage = {
            "prompt_tokens": 1000,
            "completion_tokens": 120,
            "prompt_tokens_details": {"cached_tokens": 800},
            "completion_tokens_details": {"reasoning_tokens": 100},
        }
        if provider == "deepseek":
            usage.update(prompt_cache_hit_tokens=800, prompt_cache_miss_tokens=200)
        events.append({"choices": [], "usage": usage})

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter(
                [f"data: {json.dumps(event)}\n".encode() for event in events]
                + [b"data: [DONE]\n"]
            )

    def transport(request, timeout):
        captured.append(request)
        return Response()

    monkeypatch.setenv(key, "test")
    monkeypatch.setattr("urllib.request.urlopen", transport)
    configured = {"provider": provider, "model": model}
    if provider == "qwen":
        # Model Studio's Qwen 3.8 cache-hit rate is account-console evidence,
        # not the separately bundled QwenCloud rate.
        configured.update(
            input_cost_per_million=2.0,
            output_cost_per_million=6.0,
            cached_input_cost_per_million=None,
            pricing_metadata={"source": "user override"},
        )
    client = create_client(configured, 10)
    sample = client.run(
        "Charged twice",
        {
            "system_prompt": "Return only the routing JSON",
            "max_output_tokens": 4096,
            "retry": {"max_attempts": 1},
            "provider_options": {provider: options},
        },
    )

    assert len(captured) == 1
    request = captured[0]
    assert request.full_url == endpoint
    assert "openrouter" not in request.full_url
    assert request.get_header("Authorization") == "Bearer test"
    body = json.loads(request.data)
    assert body["model"] == model and body[parameter] == 4096
    assert body["stream"] is True
    assert body["messages"] == [
        {"role": "system", "content": "Return only the routing JSON"},
        {"role": "user", "content": "Charged twice"},
    ]
    for name, value in options.items():
        assert body[name] == value
    assert "temperature" not in body
    assert ("stream_options" in body) is (provider != "zai")
    if provider != "zai":
        assert body["stream_options"] == {"include_usage": True}
    assert sample["ok"] is True and sample["retry_count"] == 0
    assert sample["response"] == '{"queue":"billing"}'
    assert sample["input_tokens"] == (1000 if reported_usage else None)
    assert sample["cached_input_tokens"] == (800 if reported_usage else None)
    assert sample["output_tokens"] == (120 if reported_usage else None)
    pricing = apply_public_pricing(client.model)
    assert pricing["cached_input_cost_per_million"] == cached_price
    actual = summarize([sample], pricing)["estimated_cost_usd"]
    if reported_usage and cost is not None:
        assert actual == pytest.approx(cost)
    else:
        assert actual is None


@pytest.mark.parametrize(
    "provider,model,key",
    [
        ("zai", "glm-5.3", "ZAI_API_KEY"),
        ("deepseek", "deepseek-flash", "DEEPSEEK_API_KEY"),
        ("qwen", "qwen3.8-max", "DASHSCOPE_API_KEY"),
    ],
)
def test_native_chinese_models_retain_native_auth_failures_without_fallback(
    monkeypatch, provider, model, key
):
    captured = []

    def transport(request, timeout):
        captured.append(request.full_url)
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"error":{"message":"invalid native credential"}}'),
        )

    monkeypatch.setenv(key, "test")
    monkeypatch.setattr("urllib.request.urlopen", transport)
    client = create_client({"provider": provider, "model": model}, 10)
    sample = client.run("ok", {"retry": {"max_attempts": 1}})

    assert captured == [client.endpoint()]
    assert "openrouter" not in captured[0]
    assert sample["ok"] is False and sample["failure_category"] == "credentials"
    assert sample["retry_count"] == 0
    assert sample["input_tokens"] is None and sample["output_tokens"] is None
    assert "HTTP 401" in sample["error"]


@pytest.mark.parametrize(
    "provider,model",
    [
        ("qwen", "qwen3-vl-plus"),
        ("qwen", "qwen3.8-max-unreviewed"),
        ("openrouter", "qwen/qwen3.8-max-0902"),
        ("openai_compatible", "qwen3.8-max"),
    ],
)
def test_native_qwen_cap_change_keeps_other_protocols_unchanged(provider, model):
    configured = {"provider": provider, "model": model}
    if provider == "openai_compatible":
        configured["base_url"] = "https://custom.example/v1"
    body = create_client(configured, 10).body("ok", {"max_output_tokens": 42})
    assert body["max_tokens"] == 42 and "max_completion_tokens" not in body


@pytest.mark.parametrize("parameter", ["max_tokens", "max_completion_tokens"])
def test_native_qwen_preserves_an_explicit_model_token_parameter(parameter):
    client = create_client(
        {"provider": "qwen", "model": "qwen3.8-max", "max_tokens_parameter": parameter},
        10,
    )
    body = client.body(
        "ok",
        {
            "max_output_tokens": 42,
            "provider_options": {"qwen": {"enable_thinking": False}},
        },
    )
    assert client.model["max_tokens_parameter"] == parameter
    assert body[parameter] == 42
    other = (
        "max_tokens"
        if parameter == "max_completion_tokens"
        else "max_completion_tokens"
    )
    assert other not in body


@pytest.mark.parametrize(
    "provider,model,key",
    [
        ("qwen", "qwen3.8-max", "DASHSCOPE_API_KEY"),
        ("deepseek", "deepseek-flash", "DEEPSEEK_API_KEY"),
        ("zai", "glm-5.3", "ZAI_API_KEY"),
    ],
)
@pytest.mark.parametrize("scope", ["flat", "provider", "all"])
@pytest.mark.parametrize(
    "parameter",
    [
        "max_tokens",
        "max_completion_tokens",
        "max_output_tokens",
        "model",
        "messages",
        "stream",
        "stream_options",
    ],
)
@pytest.mark.parametrize("surface", ["wire", "budget", "doctor"])
def test_native_overrides_cannot_change_the_planned_request(
    monkeypatch, provider, model, key, scope, parameter, surface
):
    from llm_preflight.features import check_budget, doctor_report

    raw = {parameter: 4096}
    overrides = (
        raw if scope == "flat" else {provider if scope == "provider" else scope: raw}
    )
    config = {
        "prompt": "ok",
        "models": [{"provider": provider, "model": model}],
        "repetitions": 1,
        "warmups": 0,
        "max_requests": 1,
        "max_estimated_cost_usd": 0.0001,
        "request": {
            "max_output_tokens": 1,
            "retry": {"max_attempts": 1},
            "provider_options": overrides,
        },
    }
    monkeypatch.setenv(key, "test")
    if surface == "doctor":
        report = doctor_report(config)
        assert report["ok"] is False
        assert any(
            "request.max_output_tokens" in check["message"]
            for check in report["checks"]
        )
    else:
        with pytest.raises(ValueError, match="request.max_output_tokens"):
            if surface == "budget":
                check_budget(config)
            else:
                create_client(config["models"][0], 10).body("ok", config["request"])


@pytest.mark.parametrize("surface", ["wire", "budget", "doctor"])
def test_native_qwen_legacy_answer_limit_cannot_leave_reasoning_unbounded(
    monkeypatch, surface
):
    from llm_preflight.features import check_budget, doctor_report

    model = {
        "provider": "qwen",
        "model": "qwen3.8-max",
        "max_tokens_parameter": "max_tokens",
    }
    config = {
        "models": [model],
        "prompt": "ok",
        "repetitions": 1,
        "warmups": 0,
        "request": {"max_output_tokens": 1},
        "max_estimated_cost_usd": 0.0001,
    }
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test")
    if surface == "doctor":
        report = doctor_report(config)
        assert report["ok"] is False
        assert any(
            "max_completion_tokens" in check["message"] for check in report["checks"]
        )
    else:
        with pytest.raises(ValueError, match="max_completion_tokens"):
            if surface == "budget":
                check_budget(config)
            else:
                create_client(model, 10).body("ok", config["request"])


def test_typesafe_rejects_the_text_smoke_adapter():
    with pytest.raises(ValueError, match="text smoke adapter"):
        create_client({"provider": "typesafe", "model": "jev-latest"}, 10)


def test_openrouter_jev_is_refused_as_a_typed_decision_model():
    with pytest.raises(ValueError, match="text smoke adapter"):
        create_client(
            {
                "provider": "openrouter",
                "model": "typesafe/jev-latest",
                "catalog_type": "decision",
            },
            10,
        )


def test_decision_catalog_type_is_refused_regardless_of_provider():
    with pytest.raises(ValueError, match="text smoke adapter"):
        create_client(
            {
                "provider": "openai_compatible",
                "model": "custom-jev",
                "base_url": "https://example.test/v1",
                "catalog_type": "decision",
            },
            10,
        )


def test_openrouter_uses_compatible_adapter():
    client = create_client({"provider": "openrouter", "model": "vendor/model"}, 10)
    assert isinstance(client, OpenAICompatibleClient)
    assert client.model["base_url"] == "https://openrouter.ai/api/v1"
    body = client.body("hello", {"max_output_tokens": 1})
    assert body["max_tokens"] == 1
    assert "max_completion_tokens" not in body


def test_openrouter_uses_openai_multipart_content_for_local_image_inputs(tmp_path):
    image = tmp_path / "receipt.png"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + (1).to_bytes(4, "big")
        + (1).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )
    client = create_client({"provider": "openrouter", "model": "qwen/qwen3-vl"}, 10)

    body = client.body(
        "Read the receipt.",
        {
            "input_images": [
                {
                    "path": "receipt.png",
                    "mime_type": "image/png",
                    "width": 1,
                    "height": 1,
                    "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                }
            ],
            "_image_base_dir": str(tmp_path),
        },
    )

    assert body["messages"][-1]["content"][0] == {
        "type": "text",
        "text": "Read the receipt.",
    }
    assert body["messages"][-1]["content"][1]["type"] == "image_url"
    assert body["messages"][-1]["content"][1]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )


def test_qwen_model_studio_uses_the_openai_compatible_image_protocol(tmp_path):
    image = tmp_path / "receipt.png"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + (1).to_bytes(4, "big")
        + (1).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )
    client = create_client(
        {
            "provider": "openai_compatible",
            "model": "qwen3-vl-plus",
            "base_url": "https://workspace.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
        },
        10,
    )
    body = client.body(
        "Read the receipt.",
        {
            "input_images": [
                {
                    "path": "receipt.png",
                    "mime_type": "image/png",
                    "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                }
            ],
            "_image_base_dir": str(tmp_path),
        },
    )

    assert client.endpoint().endswith("/compatible-mode/v1/chat/completions")
    assert body["messages"][-1]["content"][1]["type"] == "image_url"


def test_gemini_uses_inline_data_for_local_image_inputs(tmp_path):
    image = tmp_path / "receipt.png"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + (1).to_bytes(4, "big")
        + (1).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )
    client = create_client({"provider": "gemini", "model": "gemini-test"}, 10)

    body = client.body(
        "Read the receipt.",
        {
            "input_images": [
                {
                    "path": "receipt.png",
                    "mime_type": "image/png",
                    "width": 1,
                    "height": 1,
                    "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                }
            ],
            "_image_base_dir": str(tmp_path),
        },
    )

    assert body["contents"][0]["parts"][0] == {"text": "Read the receipt."}
    assert body["contents"][0]["parts"][1]["inlineData"]["mimeType"] == "image/png"
    assert body["contents"][0]["parts"][1]["inlineData"]["data"]


def test_image_input_fails_if_the_local_file_changes_after_validation(tmp_path):
    image = tmp_path / "receipt.png"
    original = (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + (1).to_bytes(4, "big")
        + (1).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )
    image.write_bytes(original)
    client = create_client({"provider": "openrouter", "model": "qwen/qwen3-vl"}, 10)
    options = {
        "input_images": [
            {
                "path": "receipt.png",
                "mime_type": "image/png",
                "sha256": hashlib.sha256(original).hexdigest(),
            }
        ],
        "_image_base_dir": str(tmp_path),
    }
    image.write_bytes(original + b"changed")

    with pytest.raises(ValueError, match="changed after configuration was loaded"):
        client.body("Read the receipt.", options)


def test_anthropic_rejects_image_inputs_instead_of_ignoring_them(tmp_path):
    image = tmp_path / "receipt.png"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + (1).to_bytes(4, "big")
        + (1).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )
    client = create_client({"provider": "anthropic", "model": "claude-test"}, 10)

    with pytest.raises(ValueError, match="does not support input_images"):
        client.body(
            "Read the receipt.",
            {
                "input_images": [{"path": "receipt.png", "mime_type": "image/png"}],
                "_image_base_dir": str(tmp_path),
            },
        )


def test_openai_responses_rejects_image_inputs_instead_of_ignoring_them():
    client = create_client(
        {"provider": "openai", "model": "gpt-test", "adapter": "openai_responses"},
        10,
    )

    with pytest.raises(ValueError, match="does not support input_images"):
        client.body("Read this.", {"input_images": [{"path": "receipt.png"}]})


def test_xai_uses_the_verified_openai_compatible_image_protocol(tmp_path):
    image = tmp_path / "receipt.png"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + (1).to_bytes(4, "big")
        + (1).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )
    client = create_client({"provider": "xai", "model": "grok-test"}, 10)

    body = client.body(
        "Read this.",
        {
            "input_images": [
                {
                    "path": "receipt.png",
                    "mime_type": "image/png",
                    "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                }
            ],
            "_image_base_dir": str(tmp_path),
        },
    )

    assert body["messages"][-1]["content"][1]["type"] == "image_url"


def test_openrouter_applies_provider_specific_options():
    client = create_client({"provider": "openrouter", "model": "vendor/model"}, 10)
    body = client.body(
        "hello",
        {
            "provider_options": {
                "gemini": {
                    "generationConfig": {"responseMimeType": "application/json"}
                },
                "openrouter": {
                    "response_format": {"type": "json_object"},
                    "include_reasoning": False,
                    "reasoning": {"enabled": False},
                },
            }
        },
    )

    assert body["response_format"] == {"type": "json_object"}
    assert body["include_reasoning"] is False
    assert body["reasoning"] == {"enabled": False}
    assert "gemini" not in body


def test_compatible_client_ignores_other_provider_options():
    client = create_client({"provider": "openai", "model": "model-a"}, 10)
    body = client.body(
        "hello",
        {
            "provider_options": {
                "gemini": {"generationConfig": {"responseMimeType": "application/json"}}
            }
        },
    )
    assert "generationConfig" not in body
    assert "gemini" not in body


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
    for model in (
        "claude-sonnet-5",
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
        "claude-fable-5",
        "claude-fable-5-1",
        "claude-opus-4-8",
        "claude-opus-5",
        "claude-opus-5-5",
    ):
        client = create_client({"provider": "anthropic", "model": model}, 10)
        assert "temperature" not in client.body(
            "hello", {"temperature": 0, "max_output_tokens": 16}
        )


@pytest.mark.parametrize(
    ("model_id", "expected_cost"),
    [("claude-haiku-5-5", 0.000028), ("claude-sonnet-5-5", 0.00048)],
)
@pytest.mark.parametrize("written", [0, 100])
def test_anthropic_stream_preserves_total_input_and_cache_usage(
    monkeypatch, model_id, expected_cost, written
):
    from llm_preflight.metrics import summarize
    from llm_preflight.pricing import apply_public_pricing

    captured = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            events = [
                {
                    "type": "message_start",
                    "message": {
                        "usage": {
                            "input_tokens": 100,
                            "cache_read_input_tokens": 800,
                            "cache_creation_input_tokens": written,
                            "output_tokens": 0,
                        }
                    },
                },
                {
                    "type": "content_block_delta",
                    "delta": {"type": "thinking_delta", "thinking": "internal"},
                },
                {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "billing"},
                },
                {"type": "message_delta", "usage": {"output_tokens": 20}},
            ]
            return iter(f"data: {json.dumps(event)}\n".encode() for event in events)

    def transport(request, timeout):
        captured.append(json.loads(request.data))
        return Response()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", transport)
    model = apply_public_pricing({"provider": "anthropic", "model": model_id})
    client = create_client(model, 10)

    sample = client.run(
        "I was charged twice.",
        {
            "temperature": 0,
            "max_output_tokens": 128,
            "system_prompt": "Return only the queue label.",
            "provider_options": {"anthropic": {"output_config": {"effort": "low"}}},
            "retry": {"max_attempts": 1},
        },
    )

    assert sample["ok"] is True
    assert sample["response"] == "billing"
    assert sample["input_tokens"] == 900 + written
    assert sample["cached_input_tokens"] == 800
    assert sample["cache_write_input_tokens"] == written
    assert sample["output_tokens"] == 20
    assert "temperature" not in captured[0]
    assert captured[0]["system"] == "Return only the queue label."
    assert captured[0]["output_config"] == {"effort": "low"}
    summary = summarize([sample], model)
    assert summary["input_tokens"] == 900 + written
    assert summary["cache_write_input_tokens"] == written
    if written:
        # Anthropic write prices vary by TTL; an aggregate count cannot pick one.
        assert summary["estimated_cost_usd"] is None
        assert summary["cost_coverage"]["missing_price_requests"] == 1
    else:
        assert summary["estimated_cost_usd"] == pytest.approx(expected_cost)


@pytest.mark.parametrize(
    "cache_usage",
    [
        {"cache_read_input_tokens": -1},
        {"cache_read_input_tokens": "800"},
        {"cache_creation_input_tokens": 0.5},
        {"cache_creation_input_tokens": True},
        {"cache_creation_input_tokens": None},
    ],
)
def test_anthropic_invalid_cache_usage_cannot_produce_a_cost(cache_usage):
    from llm_preflight.pricing import apply_public_pricing, estimate_sample_cost

    model = apply_public_pricing({"provider": "anthropic", "model": "claude-haiku-5-5"})
    client = create_client(model, 10)
    _, usage = client.parse_event(
        {
            "message": {
                "usage": {"input_tokens": 100, "output_tokens": 20, **cache_usage}
            }
        }
    )

    assert estimate_sample_cost(usage, model) is None


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
                "thoughtsTokenCount": 8,
            },
        }
    )
    assert text == "hi"
    assert usage == {"input_tokens": 1, "output_tokens": 10}


@pytest.mark.parametrize(
    "usage_metadata", [{}, {"promptTokenCount": 100}, {"thoughtsTokenCount": 8}]
)
def test_gemini_does_not_invent_missing_output_usage(usage_metadata):
    client = create_client({"provider": "gemini", "model": "gemini-test"}, 10)
    _, usage = client.parse_event({"usageMetadata": usage_metadata})
    assert usage.get("output_tokens") is None


@pytest.mark.parametrize("value", [True, -1, "2", 1.5, float("nan"), float("inf")])
def test_gemini_does_not_coerce_invalid_output_components(value):
    client = create_client({"provider": "gemini", "model": "gemini-test"}, 10)
    _, usage = client.parse_event(
        {
            "usageMetadata": {
                "promptTokenCount": 100,
                "candidatesTokenCount": value,
                "thoughtsTokenCount": 8,
            }
        }
    )
    from llm_preflight.pricing import estimate_sample_cost

    assert (
        estimate_sample_cost(
            usage, {"input_cost_per_million": 1, "output_cost_per_million": 2}
        )
        is None
    )


def test_gemini_merges_provider_specific_generation_config():
    client = create_client({"provider": "gemini", "model": "gemini-test"}, 10)
    body = client.body(
        "hello",
        {
            "temperature": 0,
            "max_output_tokens": 42,
            "provider_options": {
                "gemini": {
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "thinkingConfig": {
                            "includeThoughts": False,
                        },
                    }
                }
            },
        },
    )

    assert body["generationConfig"] == {
        "temperature": 0,
        "maxOutputTokens": 42,
        "responseMimeType": "application/json",
        "thinkingConfig": {"includeThoughts": False},
    }


def test_gemini_parser_ignores_thought_parts():
    client = create_client({"provider": "gemini", "model": "gemini-test"}, 10)

    text, usage = client.parse_event(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Draft: I should make JSON.", "thought": True},
                            {"text": '{"questions":[]}'},
                        ]
                    }
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 1,
                "candidatesTokenCount": 8,
            },
        }
    )

    assert text == '{"questions":[]}'
    assert usage == {"input_tokens": 1, "output_tokens": 8}


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


def test_single_chunk_response_reports_no_throughput(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter(
                [
                    (
                        b'data: {"choices":[{"delta":{"content":"whole body at once"}}],'
                        b'"usage":{"prompt_tokens":3,"completion_tokens":140}}\n'
                    ),
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
    assert sample["output_tokens"] == 140
    assert sample["output_tokens_per_second"] is None


def test_incremental_stream_reports_throughput(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter(
                [
                    b'data: {"choices":[{"delta":{"content":"first"}}]}\n',
                    (
                        b'data: {"choices":[{"delta":{"content":" second"}}],'
                        b'"usage":{"prompt_tokens":3,"completion_tokens":2}}\n'
                    ),
                    b"data: [DONE]\n",
                ]
            )

    ticks = iter(i * 0.5 for i in range(100))
    monkeypatch.setattr("llm_preflight.client.time.perf_counter", lambda: next(ticks))
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request, timeout: FakeResponse()
    )
    sample = create_client({"provider": "openai", "model": "model-a"}, 10).run(
        "hello", {"max_output_tokens": 4}
    )
    assert sample["ok"] is True
    assert sample["output_tokens_per_second"] is not None
    assert sample["output_tokens_per_second"] > 0


def test_burst_stream_below_generation_window_reports_no_throughput(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter(
                [
                    b'data: {"choices":[{"delta":{"content":"first"}}]}\n',
                    (
                        b'data: {"choices":[{"delta":{"content":" second"}}],'
                        b'"usage":{"prompt_tokens":3,"completion_tokens":140}}\n'
                    ),
                    b"data: [DONE]\n",
                ]
            )

    # Everything after the first token arrives within 1 ms — a terminal
    # burst, not incremental generation.
    ticks = iter([0.0, 3.0, 3.001, 3.002])
    monkeypatch.setattr("llm_preflight.client.time.perf_counter", lambda: next(ticks))
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request, timeout: FakeResponse()
    )
    sample = create_client({"provider": "openai", "model": "model-a"}, 10).run(
        "hello", {"max_output_tokens": 4}
    )
    assert sample["ok"] is True
    assert sample["output_tokens_per_second"] is None


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


def test_client_retries_retryable_http_error_and_records_attempts(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter(
                [
                    b'data: {"choices":[{"delta":{"content":"ok"}}]}\n',
                    b'data: {"choices":[],"usage":{"prompt_tokens":2,"completion_tokens":1}}\n',
                    b"data: [DONE]\n",
                ]
            )

    calls = 0

    def flaky_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "rate limited",
                {},
                io.BytesIO(b'{"error":"rate limited"}'),
            )
        return FakeResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", flaky_urlopen)
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    sample = create_client({"provider": "openai", "model": "model-a"}, 10).run(
        "hello",
        {
            "retry": {
                "max_attempts": 2,
                "initial_delay_seconds": 0,
                "jitter": False,
            }
        },
    )

    assert sample["ok"] is True
    assert sample["response"] == "ok"
    assert sample["attempts"] == 2
    assert sample["retry_count"] == 1
    assert sample["retry_reasons"] == ["rate_limit"]


def test_client_retries_rate_limit_once_by_default(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter(
                [
                    b'data: {"choices":[{"delta":{"content":"ok"}}]}\n',
                    b"data: [DONE]\n",
                ]
            )

    calls = 0

    def flaky_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "rate limited",
                {},
                io.BytesIO(b'{"error":"rate limited"}'),
            )
        return FakeResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", flaky_urlopen)
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    sample = create_client({"provider": "openai", "model": "model-a"}, 10).run(
        "hello", {}
    )

    assert calls == 2
    assert sample["ok"] is True
    assert sample["retry_reasons"] == ["rate_limit"]


def test_client_does_not_retry_non_retryable_http_error(monkeypatch):
    calls = 0

    def bad_request(request, timeout):
        nonlocal calls
        calls += 1
        raise urllib.error.HTTPError(
            request.full_url,
            400,
            "bad request",
            {},
            io.BytesIO(b'{"error":"unsupported parameter"}'),
        )

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", bad_request)

    sample = create_client({"provider": "openai", "model": "model-a"}, 10).run(
        "hello", {"retry": {"max_attempts": 3, "initial_delay_seconds": 0}}
    )

    assert calls == 1
    assert sample["ok"] is False
    assert sample["attempts"] == 1
    assert sample["retry_count"] == 0
    assert sample["failure_category"] == "unsupported_parameter"


def test_client_rejects_an_oversized_streaming_response(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter([b"data: " + b"x" * MAX_RESPONSE_BYTES])

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request, timeout: FakeResponse()
    )

    sample = create_client({"provider": "openai", "model": "model-a"}, 10).run(
        "hello", {"retry": {"max_attempts": 1}}
    )

    assert sample["ok"] is False
    assert "8 MiB safety limit" in sample["error"]


def test_retry_delay_adds_bounded_jitter(monkeypatch):
    monkeypatch.setattr("llm_preflight.client.random.uniform", lambda low, high: 0.125)

    delay = _retry_delay(
        {
            "initial_delay_seconds": 0.5,
            "max_delay_seconds": 1,
            "backoff_multiplier": 2,
            "jitter_seconds": 0.2,
        },
        1,
    )

    assert delay == 0.625


def test_openai_compatible_provider_options_are_not_sent_as_a_bogus_field():
    client = create_client(
        {
            "provider": "openai_compatible",
            "model": "local",
            "base_url": "https://example.test/v1",
        },
        10,
    )

    body = client.body(
        "hello", {"provider_options": {"openai_compatible": {"seed": 7}}}
    )

    assert body["seed"] == 7
    assert "openai_compatible" not in body


def test_gemini_honors_explicit_temperature_capability_override():
    client = create_client(
        {"provider": "gemini", "model": "gemini-test", "supports_temperature": False},
        10,
    )

    assert (
        "temperature"
        not in client.body("hello", {"temperature": 0.2})["generationConfig"]
    )


def test_statusless_malformed_stream_is_not_retried(monkeypatch):
    calls = 0

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter([b"data: not-json\n"])

    def bad_stream(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return FakeResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", bad_stream)
    sample = create_client({"provider": "openai", "model": "model-a"}, 10).run(
        "hello", {"retry": {"max_attempts": 3, "initial_delay_seconds": 0}}
    )

    assert calls == 1
    assert sample["failure_category"] == "provider_error"


def test_openai_responses_honors_retry_configuration(monkeypatch):
    calls = 0

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, *_args):
            return b'{"output_text":"ok","usage":{}}'

    def flaky(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(
                request.full_url, 429, "rate", {}, io.BytesIO(b"rate limited")
            )
        return FakeResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", flaky)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    sample = create_client(
        {"provider": "openai", "model": "model-a", "adapter": "openai_responses"}, 10
    ).run("hello", {"retry": {"max_attempts": 2, "initial_delay_seconds": 0}})

    assert calls == 2
    assert sample["retry_reasons"] == ["rate_limit"]


def test_success_latency_excludes_previous_retry_and_backoff(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter(
                [
                    b'data: {"choices":[{"delta":{"content":"ok"}}]}\n',
                    b"data: [DONE]\n",
                ]
            )

    calls = 0

    def flaky(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(
                request.full_url, 429, "rate", {}, io.BytesIO()
            )
        return FakeResponse()

    timestamps = iter([0.0, 1.0, 10.0, 12.0, 15.0])
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", flaky)
    monkeypatch.setattr(
        "llm_preflight.client.time.perf_counter", lambda: next(timestamps)
    )
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    sample = create_client({"provider": "openai", "model": "model-a"}, 10).run(
        "hello", {"retry": {"max_attempts": 2, "initial_delay_seconds": 1}}
    )

    assert sample["latency_seconds"] == 5.0
    assert sample["ttft_seconds"] == 2.0


def test_transient_socket_errors_are_retried_by_exception_type(monkeypatch):
    calls = 0

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter([b'data: {"choices":[{"delta":{"content":"ok"}}]}\n'])

    def flaky(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionRefusedError("Connection refused")
        return FakeResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", flaky)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    sample = create_client({"provider": "openai", "model": "model-a"}, 10).run(
        "hello", {"retry": {"max_attempts": 2, "initial_delay_seconds": 0}}
    )

    assert calls == 2
    assert sample["retry_reasons"] == ["network"]


@pytest.mark.parametrize("model", ["gemini-3.8-flash", "gemini-4-argon"])
def test_gemini_provider_options_cannot_bypass_the_planned_output_budget(model):
    client = create_client({"provider": "gemini", "model": model}, 10)
    with pytest.raises(ValueError, match="request.max_output_tokens"):
        client.body(
            "hello",
            {
                "max_output_tokens": 42,
                "provider_options": {
                    "gemini": {"generationConfig": {"maxOutputTokens": 32768}}
                },
            },
        )
    assert (
        client.body(
            "hello",
            {
                "max_output_tokens": 42,
                "provider_options": {
                    "gemini": {"generationConfig": {"maxOutputTokens": 42}}
                },
            },
        )["generationConfig"]["maxOutputTokens"]
        == 42
    )


@pytest.mark.parametrize("limit", [256, 32768, 65536])
def test_gemini_4_preserves_explicit_limits_and_omits_ignored_sampling(limit):
    client = create_client(
        {
            "provider": "gemini",
            "model": "gemini-4-argon",
            "capabilities": {"temperature": True},
        },
        10,
    )
    body = client.body(
        "hello",
        {
            "temperature": 0,
            "max_output_tokens": limit,
            "provider_options": {
                "gemini": {
                    "generationConfig": {
                        "temperature": 0.5,
                        "topP": 0.8,
                        "topK": 8,
                        "thinkingConfig": {"thinkingLevel": "LOW"},
                    }
                }
            },
        },
    )
    assert body["generationConfig"] == {
        "maxOutputTokens": limit,
        "thinkingConfig": {"thinkingLevel": "LOW"},
    }
    assert client.body("hello", {})["generationConfig"] == {"maxOutputTokens": 256}


@pytest.mark.parametrize(
    "provider_options,limit,message",
    [
        ({"cachedContent": "cachedContents/example"}, 32768, "implicit caching"),
        ({}, 65537, "65536"),
        (
            {"generationConfig": {"thinkingConfig": {"thinkingLevel": "MINIMAL"}}},
            32768,
            "LOW, MEDIUM, HIGH",
        ),
    ],
)
def test_gemini_4_unsupported_options_fail_before_transport(
    monkeypatch, provider_options, limit, message
):
    def unexpected_transport(*args, **kwargs):
        pytest.fail("unsupported request must fail before network transport")

    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", unexpected_transport)
    sample = create_client({"provider": "gemini", "model": "gemini-4-argon"}, 10).run(
        "hello",
        {
            "max_output_tokens": limit,
            "provider_options": {"gemini": provider_options},
            "retry": {"max_attempts": 1},
        },
    )
    assert sample["ok"] is False
    assert message in sample["error"]


@pytest.mark.parametrize("level", ["LOW", "MEDIUM", "HIGH"])
def test_gemini_4_generate_content_protocol_and_cost(
    monkeypatch, snapshot_review_day, level
):
    from llm_preflight.pricing import apply_public_pricing, estimate_sample_cost

    captured = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            event = {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "private thought", "thought": True},
                                {"text": "ready"},
                            ]
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 1000,
                    "cachedContentTokenCount": 800,
                    "candidatesTokenCount": 20,
                    "thoughtsTokenCount": 80,
                },
            }
            return iter([f"data: {json.dumps(event)}\n".encode()])

    def transport(request, timeout):
        captured.append((request.full_url, json.loads(request.data)))
        return Response()

    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", transport)
    model = apply_public_pricing({"provider": "gemini", "model": "gemini-4-argon"})
    sample = create_client(model, 10).run(
        "Reply with ready.",
        {
            "system_prompt": "Return only the requested label.",
            "temperature": 0,
            "max_output_tokens": 32768,
            "retry": {"max_attempts": 1},
            "provider_options": {
                "gemini": {
                    "generationConfig": {"thinkingConfig": {"thinkingLevel": level}}
                }
            },
        },
    )
    assert sample["ok"] is True
    assert sample["response"] == "ready"
    assert sample["input_tokens"] == 1000
    assert sample["cached_input_tokens"] == 800
    assert sample["output_tokens"] == 100
    assert estimate_sample_cost(sample, model) == pytest.approx(0.00148)
    assert captured == [
        (
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-4-argon:streamGenerateContent?alt=sse",
            {
                "contents": [
                    {"role": "user", "parts": [{"text": "Reply with ready."}]}
                ],
                "systemInstruction": {
                    "parts": [{"text": "Return only the requested label."}]
                },
                "generationConfig": {
                    "maxOutputTokens": 32768,
                    "thinkingConfig": {"thinkingLevel": level},
                },
            },
        )
    ]


@pytest.mark.parametrize("thinking", [None, [], "LOW"])
def test_gemini_4_malformed_thinking_config_is_a_normal_pretransport_failure(
    monkeypatch, thinking
):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    sample = create_client({"provider": "gemini", "model": "gemini-4-argon"}, 10).run(
        "hello",
        {
            "max_output_tokens": 32768,
            "retry": {"max_attempts": 1},
            "provider_options": {
                "gemini": {"generationConfig": {"thinkingConfig": thinking}}
            },
        },
    )
    assert sample["ok"] is False
    assert "thinkingConfig must be an object" in sample["error"]


def test_gemini_4_http_error_remains_a_provider_failure(monkeypatch):
    def transport(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            400,
            "invalid request",
            {},
            io.BytesIO(b'{"error":{"message":"unsupported option"}}'),
        )

    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", transport)
    sample = create_client({"provider": "gemini", "model": "gemini-4-argon"}, 10).run(
        "hello", {"max_output_tokens": 32768, "retry": {"max_attempts": 1}}
    )
    assert sample["ok"] is False
    assert sample["failure_category"] == "provider_error"
    assert sample["output_tokens"] is None
    assert "HTTP 400" in sample["error"]


def test_gemini_4_thinking_only_truncation_cannot_pass_the_contract(monkeypatch):
    from llm_preflight.profiles import evaluate_response

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            event = {
                "candidates": [
                    {
                        "finishReason": "MAX_TOKENS",
                        "content": {"parts": [{"text": "ready", "thought": True}]},
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 0,
                    "thoughtsTokenCount": 256,
                },
            }
            return iter([f"data: {json.dumps(event)}\n".encode()])

    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    sample = create_client({"provider": "gemini", "model": "gemini-4-argon"}, 10).run(
        "Reply with ready", {}
    )
    assert sample["response"] == ""
    assert sample["output_tokens"] == 256
    assert (
        evaluate_response(sample["response"], {"type": "exact", "expected": "ready"})[
            "valid"
        ]
        is False
    )


class _StreamResponse:
    """A provider's server-sent events, as `urllib.request.urlopen` yields them."""

    def __init__(self, events):
        self.events = events

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def __iter__(self):
        return iter(
            [f"data: {json.dumps(event)}\n".encode() for event in self.events]
            + [b"data: [DONE]\n"]
        )


def _chat_chunk(model, text=None, usage=None):
    chunk = {
        "id": "chatcmpl-fixture",
        "object": "chat.completion.chunk",
        "created": 1_791_000_000,
        "choices": [{"index": 0, "delta": {"content": text}}] if text else [],
    }
    if model is not None:
        chunk["model"] = model
    if usage is not None:
        chunk["usage"] = usage
    return chunk


def _chat_stream(model):
    return [
        _chat_chunk(model, "bill"),
        _chat_chunk(model, "ing"),
        _chat_chunk(model, usage={"prompt_tokens": 9, "completion_tokens": 2}),
    ]


@pytest.mark.parametrize(
    ("configured", "key", "events", "observed"),
    [
        (
            {"provider": "openai", "model": "gpt-4.1-mini"},
            "OPENAI_API_KEY",
            _chat_stream("gpt-4.1-mini-2025-04-14"),
            "gpt-4.1-mini-2025-04-14",
        ),
        (
            {"provider": "openrouter", "model": "z-ai/glm-5.3"},
            "OPENROUTER_API_KEY",
            _chat_stream("z-ai/glm-5.3-20260901"),
            "z-ai/glm-5.3-20260901",
        ),
        (
            {"provider": "deepseek", "model": "deepseek-flash"},
            "DEEPSEEK_API_KEY",
            _chat_stream("deepseek-v4.1-flash"),
            "deepseek-v4.1-flash",
        ),
        (
            {"provider": "qwen", "model": "qwen3.8-max"},
            "DASHSCOPE_API_KEY",
            _chat_stream("qwen3.8-max-0902"),
            "qwen3.8-max-0902",
        ),
        (
            {"provider": "zai", "model": "glm-5.3"},
            "ZAI_API_KEY",
            _chat_stream("glm-5.3"),
            "glm-5.3",
        ),
        (
            {"provider": "anthropic", "model": "claude-sonnet-5-5"},
            "ANTHROPIC_API_KEY",
            [
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_fixture",
                        "type": "message",
                        "role": "assistant",
                        "model": "claude-sonnet-5-5-20260901",
                        "content": [],
                        "usage": {"input_tokens": 9, "output_tokens": 1},
                    },
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "billing"},
                },
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn"},
                    "usage": {"output_tokens": 2},
                },
                {"type": "message_stop"},
            ],
            "claude-sonnet-5-5-20260901",
        ),
        (
            {"provider": "gemini", "model": "gemini-4-argon"},
            "GEMINI_API_KEY",
            [
                {
                    "candidates": [{"content": {"parts": [{"text": "bill"}]}}],
                    "modelVersion": "gemini-4-argon-001",
                    "responseId": "fixture",
                },
                {
                    "candidates": [{"content": {"parts": [{"text": "ing"}]}}],
                    "usageMetadata": {
                        "promptTokenCount": 9,
                        "candidatesTokenCount": 2,
                    },
                    "modelVersion": "gemini-4-argon-001",
                    "responseId": "fixture",
                },
            ],
            "gemini-4-argon-001",
        ),
    ],
    ids=["openai", "openrouter", "deepseek", "qwen", "zai", "anthropic", "gemini"],
)
def test_stream_records_the_model_the_provider_reported(
    monkeypatch, configured, key, events, observed
):
    monkeypatch.setenv(key, "test")
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request, timeout: _StreamResponse(events)
    )

    sample = create_client(configured, 10).run(
        "Charged twice", {"max_output_tokens": 64, "retry": {"max_attempts": 1}}
    )

    assert sample["ok"] is True
    assert sample["response"] == "billing"
    assert sample["observed_model"] == observed


def test_responses_api_records_the_model_the_provider_reported(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, *args):
            return json.dumps(
                {
                    "id": "resp_fixture",
                    "object": "response",
                    "status": "completed",
                    "model": "gpt-6.1-sol-2026-09-30",
                    "output_text": "billing",
                    "usage": {"input_tokens": 9, "output_tokens": 2},
                }
            ).encode()

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: Response())

    sample = create_client(
        {"provider": "openai", "model": "gpt-6.1-sol", "adapter": "openai_responses"},
        10,
    ).run("Charged twice", {"retry": {"max_attempts": 1}})

    assert sample["observed_model"] == "gpt-6.1-sol-2026-09-30"


@pytest.mark.parametrize(
    ("models", "observed"),
    [
        (
            ["gpt-4.1-mini-b", "gpt-4.1-mini-a", "gpt-4.1-mini-b"],
            ["gpt-4.1-mini-a", "gpt-4.1-mini-b"],
        ),
        ([None, None, None], None),
        (["", 7, "gpt\x1b[31m"], None),
        ([None, "x" * 257, "gpt-4.1-mini-a"], "gpt-4.1-mini-a"),
    ],
    ids=["disagreeing", "absent", "malformed", "oversized"],
)
def test_stream_records_every_distinct_reported_model_and_never_guesses(
    monkeypatch, models, observed
):
    events = [
        _chat_chunk(models[0], "bill"),
        _chat_chunk(models[1], "ing"),
        _chat_chunk(models[2], usage={"prompt_tokens": 9, "completion_tokens": 2}),
    ]
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request, timeout: _StreamResponse(events)
    )

    sample = create_client({"provider": "openai", "model": "gpt-4.1-mini"}, 10).run(
        "Charged twice", {"retry": {"max_attempts": 1}}
    )

    assert sample["observed_model"] == observed


def test_a_failed_request_reports_no_observed_model(monkeypatch):
    def refuse(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 400, "bad", {}, io.BytesIO(b"bad request")
        )

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", refuse)

    sample = create_client({"provider": "openai", "model": "gpt-4.1-mini"}, 10).run(
        "Charged twice", {"retry": {"max_attempts": 1}}
    )

    assert sample["ok"] is False
    assert sample["observed_model"] is None
