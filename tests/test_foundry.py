"""Microsoft Foundry on the v1 OpenAI-compatible route, with mocked transports."""

import io
import json
import sys
import urllib.error
import urllib.request
from datetime import date

import pytest

from llm_preflight import cli, mcp
from llm_preflight.client import (
    FoundryClient,
    create_client,
    validate_native_request_options,
)
from llm_preflight.contracts import provenance
from llm_preflight.features import doctor_report, replay_config
from llm_preflight.retirements import retirement_report

BASE_URL = "https://res.services.ai.azure.com/openai/v1"
PROJECT_URL = "https://res.services.ai.azure.com/api/projects/p1/openai/v1"
MODEL = {"provider": "foundry", "model": "MAI-Thinking-1", "base_url": BASE_URL}


@pytest.fixture(autouse=True)
def _public_host_and_key(monkeypatch):
    monkeypatch.setattr(
        "llm_preflight.security.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("8.8.8.8", 443))],
    )
    monkeypatch.setattr(
        "llm_preflight.client.open_public_url",
        lambda request, timeout: urllib.request.urlopen(request, timeout),
    )
    monkeypatch.setenv("FOUNDRY_API_KEY", "foundry-test-key")


class _Stream:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def __iter__(self):
        return iter(
            [f"data: {json.dumps(e)}\n".encode() for e in self.events]
            + [b"data: [DONE]\n"]
        )


def _chunk(delta=None, finish=None, **extra):
    return {
        "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}],
        **extra,
    }


def _run(monkeypatch, events, model=None, options=None, calls=None):
    def fake(request, timeout):
        if calls is not None:
            calls.append(request)
        return _Stream(events)

    monkeypatch.setattr("urllib.request.urlopen", fake)
    return create_client(model or MODEL, 10).run(
        "hello",
        {"max_output_tokens": 8, "retry": {"max_attempts": 1}, **(options or {})},
    )


GOOD = [_chunk({"content": "ok"}), _chunk({}, "stop")]


def test_foundry_requires_base_url():
    with pytest.raises(ValueError, match="requires base_url"):
        create_client({"provider": "foundry", "model": "m"}, 10)


@pytest.mark.parametrize("url", [BASE_URL, BASE_URL + "/", PROJECT_URL])
def test_foundry_accepts_resource_and_project_v1_routes(url):
    client = create_client({**MODEL, "base_url": url}, 10)
    assert isinstance(client, FoundryClient)


@pytest.mark.parametrize(
    "url",
    [
        "http://res.services.ai.azure.com/openai/v1",
        "https://res.services.ai.azure.com/models",
        "https://res.services.ai.azure.com",
        "https://res.services.ai.azure.com/openai/v1?api-version=1",
        "https://res.services.ai.azure.com/openai/v1/chat/completions",
    ],
)
def test_foundry_base_url_must_end_with_openai_v1(url):
    with pytest.raises(ValueError, match="/openai/v1"):
        create_client({**MODEL, "base_url": url}, 10)


def test_foundry_posts_v1_chat_completions_with_bearer_key(monkeypatch):
    calls = []
    sample = _run(monkeypatch, GOOD, calls=calls)
    assert sample["ok"] is True and sample["response"] == "ok"
    assert calls[0].full_url == BASE_URL + "/chat/completions"
    assert "api-version" not in calls[0].full_url
    assert calls[0].get_header("Authorization") == "Bearer foundry-test-key"


def test_foundry_body_model_is_deployment(monkeypatch):
    calls = []
    _run(monkeypatch, GOOD, model={**MODEL, "deployment": "prod-mai"}, calls=calls)
    assert json.loads(calls[0].data)["model"] == "prod-mai"


def test_foundry_deployment_defaults_to_model(monkeypatch):
    calls = []
    _run(monkeypatch, GOOD, calls=calls)
    assert json.loads(calls[0].data)["model"] == "MAI-Thinking-1"


@pytest.mark.parametrize(
    "name", ["", "a/b", "é-deploy", "x" * 65, "-lead", ".lead", 7, None]
)
def test_foundry_rejects_invalid_deployment_name(name):
    with pytest.raises(ValueError, match="deployment"):
        create_client({**MODEL, "deployment": name}, 10)


def test_foundry_accepts_a_64_character_deployment():
    create_client({**MODEL, "deployment": "a" + "b" * 63}, 10)


def test_foundry_refuses_api_version():
    with pytest.raises(ValueError, match="api_version"):
        create_client({**MODEL, "api_version": "2025-01-01"}, 10)


def test_foundry_refuses_responses_adapter():
    with pytest.raises(ValueError, match="adapter=openai_compatible_chat"):
        create_client({**MODEL, "adapter": "openai_responses"}, 10)


def test_foundry_refuses_input_images(monkeypatch):
    sample = _run(
        monkeypatch,
        GOOD,
        options={
            "input_images": [{"mime_type": "image/png", "data": "AAAA", "name": "a"}]
        },
    )
    assert sample["ok"] is False and "text only" in sample["error"]


@pytest.mark.parametrize(
    "option", ["tools", "documents", "connectors", "web_search", "data_sources"]
)
def test_foundry_refuses_tools_and_data_sources(option):
    with pytest.raises(ValueError, match="does not execute tools"):
        validate_native_request_options(
            MODEL, {"provider_options": {"foundry": {option: []}}}
        )


def test_foundry_refuses_non_standard_service_tier():
    with pytest.raises(ValueError, match="standard pricing"):
        validate_native_request_options(
            MODEL, {"provider_options": {"foundry": {"service_tier": "priority"}}}
        )


@pytest.mark.parametrize(
    "key", ["model", "messages", "stream", "max_tokens", "max_completion_tokens"]
)
def test_foundry_provider_options_cannot_override_model_or_limits(key):
    with pytest.raises(ValueError, match="cannot override"):
        validate_native_request_options(
            MODEL, {"provider_options": {"foundry": {key: 1}}}
        )


def test_foundry_max_completion_tokens_default_and_explicit_max_tokens(monkeypatch):
    calls = []
    _run(monkeypatch, GOOD, calls=calls)
    body = json.loads(calls[0].data)
    assert body["max_completion_tokens"] == 8 and "max_tokens" not in body
    calls.clear()
    _run(
        monkeypatch,
        GOOD,
        model={**MODEL, "max_tokens_parameter": "max_tokens"},
        calls=calls,
    )
    body = json.loads(calls[0].data)
    assert body["max_tokens"] == 8 and "max_completion_tokens" not in body
    with pytest.raises(ValueError, match="max_tokens_parameter"):
        create_client({**MODEL, "max_tokens_parameter": "max_output_tokens"}, 10)


@pytest.mark.parametrize(
    ("events", "message"),
    [
        ([_chunk({"content": "ok"})], "before a complete response"),
        ([_chunk({"content": "o"}, "length")], "did not finish"),
        ([_chunk({}, "content_filter")], "content filter"),
    ],
    ids=["truncated", "length", "content_filter"],
)
def test_foundry_stream_fails_on_truncation_length_and_content_filter(
    monkeypatch, events, message
):
    sample = _run(monkeypatch, events)
    assert sample["ok"] is False
    assert message in sample["error"]


def test_foundry_accepts_prompt_filter_chunk_with_empty_choices(monkeypatch):
    events = [
        {"choices": [], "prompt_filter_results": [{"prompt_index": 0}], "model": ""},
        *GOOD,
    ]
    sample = _run(monkeypatch, events)
    assert sample["ok"] is True and sample["response"] == "ok"


def test_foundry_usage_from_final_chunk_with_cached_tokens(monkeypatch):
    usage = {
        "choices": [],
        "model": "mai-thinking-1",
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 30,
            "prompt_tokens_details": {"cached_tokens": 4},
        },
    }
    sample = _run(monkeypatch, [*GOOD, usage])
    assert sample["input_tokens"] == 12
    assert sample["output_tokens"] == 30
    assert sample["cached_input_tokens"] == 4
    assert sample["observed_model"] == "mai-thinking-1"


@pytest.mark.parametrize(
    ("code", "category"), [(401, "credentials"), (404, "not_found")]
)
def test_foundry_http_401_credentials_404_not_found(monkeypatch, code, category):
    def refuse(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, code, "no", {}, io.BytesIO(b'{"error":"x"}')
        )

    monkeypatch.setattr("urllib.request.urlopen", refuse)
    sample = create_client(MODEL, 10).run("hi", {"retry": {"max_attempts": 1}})
    assert sample["ok"] is False and sample["failure_category"] == category


def test_foundry_tool_call_is_a_failed_request(monkeypatch):
    call = {"tool_calls": [{"function": {"name": "t"}}]}
    sample = _run(monkeypatch, [_chunk(call)])
    assert sample["ok"] is False and "tool call" in sample["error"]


def _config(model=None, **extra):
    return {"prompt": "hi", "models": [model or dict(MODEL)], **extra}


def _cli(monkeypatch, tmp_path, capsys, config, *flags):
    path = tmp_path / "benchmark.json"
    path.write_text(json.dumps(config))
    monkeypatch.setattr(sys, "argv", ["llm-preflight", str(path), *flags])
    code = 0
    try:
        cli.main()
    except SystemExit as exc:
        code = exc.code or 0
    return code, capsys.readouterr().out


def test_foundry_unbundled_model_price_unknown(monkeypatch, tmp_path, capsys):
    code, out = _cli(monkeypatch, tmp_path, capsys, _config(), "--pricing-check")
    report = json.loads(out)
    assert code == 1 and report["ok"] is False
    assert report["summary"]["unknown"] == 1
    code, out = _cli(
        monkeypatch,
        tmp_path,
        capsys,
        _config(require_current_pricing=True),
        "--dry-run",
        "--json",
    )
    assert code != 0


def test_foundry_openai_model_does_not_reuse_openai_rows(monkeypatch, tmp_path, capsys):
    model = {**MODEL, "model": "gpt-6.1-sol"}
    code, out = _cli(monkeypatch, tmp_path, capsys, _config(model), "--pricing-check")
    report = json.loads(out)
    assert code == 1 and report["summary"]["priced"] == 0
    retirement = retirement_report([model], date(2026, 11, 19))
    assert retirement["decision"] != "pass"
    assert retirement["models"][0]["status"] == "unknown"
    # No GPT-6 gate applies: a non-standard tier is refused only by the Foundry rule.
    validate_native_request_options(model, {"provider_options": {"foundry": {"x": 1}}})


def test_foundry_retirement_without_row_is_inconclusive():
    report = retirement_report([MODEL], date(2026, 11, 19))
    assert report["decision"] != "pass"
    assert report["models"][0]["status"] == "unknown"


def _routes(model):
    return provenance(_config(model), [model], "pricing")["routes_sha256"]


def test_route_fingerprint_unchanged_without_deployment():
    # Hash of this config on the release before the `deployment` key existed.
    models = [
        {"provider": "mistral", "model": "mistral-large-4"},
        {
            "provider": "openai_compatible",
            "model": "x",
            "base_url": "https://x.test/v1",
        },
    ]
    hashed = provenance({"prompt": "hi", "models": models}, models, "p")
    expected = "e6bfe76404ec4ac49684b43646203feeb8579bc0a5648453393fad9f8adb6295"  # pragma: allowlist secret
    assert hashed["routes_sha256"] == expected


def test_route_fingerprint_changes_with_deployment():
    hashes = {
        _routes(dict(MODEL)),
        _routes({**MODEL, "deployment": "prod-mai"}),
        _routes({**MODEL, "deployment": "other"}),
    }
    assert len(hashes) == 3


def test_replay_and_approve_keep_deployment(monkeypatch, tmp_path, capsys):
    from llm_preflight.runner import run_benchmark

    config = _config({**MODEL, "deployment": "prod-mai"})
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request, timeout: _Stream(GOOD)
    )
    monkeypatch.setattr(
        "llm_preflight.runner.create_client",
        lambda model, timeout: create_client(model, timeout),
    )
    result = run_benchmark({**config, "repetitions": 1, "warmups": 0})
    assert result["models"][0]["deployment"] == "prod-mai"
    result["source_config"] = config
    assert replay_config(result, config)["models"][0]["deployment"] == "prod-mai"
    plain = _config()
    plain_result = run_benchmark({**plain, "repetitions": 1, "warmups": 0})
    assert "deployment" not in plain_result["models"][0]
    plain_result["source_config"] = plain
    assert "deployment" not in replay_config(plain_result, plain)["models"][0]

    source_path = tmp_path / "benchmark.json"
    source_path.write_text(json.dumps(config))
    result["source_config_path"] = str(source_path)
    result["decision"] = {"state": "pass"}
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(result))
    approved = tmp_path / "approved.json"
    cli._approve_model_main(
        [
            "foundry:MAI-Thinking-1",
            "--from",
            str(result_path),
            "--approved",
            str(approved),
        ]
    )
    assert json.loads(approved.read_text())["models"][0]["deployment"] == "prod-mai"


@pytest.mark.parametrize("args", [[], ["--interactive"]])
def test_init_provider_foundry_refuses_with_example_hint(
    monkeypatch, tmp_path, capsys, args
):
    target = tmp_path / "benchmark.json"
    argv = [
        "llm-preflight",
        "init",
        str(target),
        "--template",
        "provider",
        "--provider",
        "foundry",
        "--model",
        "MAI-Thinking-1",
        "--api-key-env",
        "FOUNDRY_API_KEY",
        *args,
    ]
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    with pytest.raises(SystemExit) as caught:
        cli.main()
    assert caught.value.code == 2
    assert "examples/foundry-mai-thinking-1.json" in capsys.readouterr().err
    assert not target.exists()


def test_catalog_init_refuses_foundry(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "llm-preflight",
            "catalog",
            "init",
            str(tmp_path / "w"),
            "--providers",
            "foundry",
        ],
    )
    with pytest.raises(SystemExit):
        cli.main()
    assert "unknown providers: foundry" in capsys.readouterr().err


def test_doctor_reports_missing_foundry_api_key(monkeypatch):
    monkeypatch.delenv("FOUNDRY_API_KEY", raising=False)
    report = doctor_report(_config())
    assert report["ok"] is False
    assert "FOUNDRY_API_KEY" in json.dumps(report["checks"])


def test_doctor_rejects_a_bad_foundry_route():
    report = doctor_report(_config({**MODEL, "base_url": "https://x.test/models"}))
    assert report["ok"] is False
    assert "/openai/v1" in json.dumps(report["checks"])


def test_mcp_contract_pricing_plan_accept_foundry_config(tmp_path):
    (tmp_path / "benchmark.json").write_text(
        json.dumps(_config(max_requests=1, max_estimated_cost_usd=1))
    )
    for name in ("validate_config", "dry_run_plan"):
        response = mcp._response(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": {"config": "benchmark.json"}},
            },
            tmp_path,
        )
        assert response["result"]["isError"] is False, name
    bad = _config({**MODEL, "api_version": "2025-01-01"})
    (tmp_path / "bad.json").write_text(json.dumps(bad))
    response = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "dry_run_plan", "arguments": {"config": "bad.json"}},
        },
        tmp_path,
    )
    assert response["result"]["isError"] is True
    assert "api_version" in json.dumps(response)


def test_interactive_run_lists_foundry_model():
    responses = iter(["all", "", "1", "1", "n"])
    output = []
    cli.interactive_selection(
        _config(),
        input_fn=lambda prompt: next(responses),
        output_fn=output.append,
    )
    assert "foundry" in "\n".join(output)
    assert "MAI-Thinking-1" in "\n".join(output)
