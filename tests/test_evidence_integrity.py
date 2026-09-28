"""Exercise cost evidence through real adapters and automation entry points."""

import io
import json
import sys

import pytest

from llm_preflight import cli, mcp
from llm_preflight.runner import run_benchmark


@pytest.mark.parametrize("entry", ["cli", "mcp"])
@pytest.mark.parametrize("named", [False, True])
@pytest.mark.parametrize(
    ("output", "state"),
    [
        ({"queue": "billing", "confidence": 0}, "pass"),
        ({"queue": "billing", "confidence": 1}, "pass"),
        ({"queue": "billing", "confidence": 2}, "fail"),
        ({"queue": "billing", "confidence": 0.95, "extra": "private value"}, "fail"),
    ],
)
def test_bounded_routing_contract_through_cli_and_mcp(
    monkeypatch, tmp_path, capsys, entry, named, output, state
):
    schema = {
        "type": "object",
        "required": ["queue", "confidence"],
        "additionalProperties": False,
        "properties": {
            "queue": {"type": "string", "enum": ["billing"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
    }
    contract = {
        "prompt": "I was charged twice",
        "validation": {"json_schema": schema},
        "validation_fixtures": [
            {
                "name": "valid",
                "response": '{"queue":"billing","confidence":0.95}',
                "expect": "pass",
            },
            {
                "name": "range",
                "response": '{"queue":"billing","confidence":2}',
                "expect": "fail",
            },
        ],
    }
    config = {
        "models": [
            {
                "provider": "openai",
                "model": "fixture-model",
                "api_key_env": None,
                "input_cost_per_million": 1,
                "output_cost_per_million": 2,
            }
        ],
        "repetitions": 1,
        "suite_repetitions": 1,
        "warmups": 0,
    }
    if named:
        config.update(prompts=[{"name": "routing", **contract}], profiles="routing")
    else:
        config.update(contract)
    event = {
        "choices": [{"delta": {"content": json.dumps(output)}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }
    body = ("data: " + json.dumps(event) + "\n\ndata: [DONE]\n").encode()
    calls = []

    def response(request, timeout):
        calls.append(json.loads(request.data))
        return io.BytesIO(body)

    monkeypatch.setattr("llm_preflight.client.open_public_url", response)
    monkeypatch.setattr(
        "llm_preflight.security.socket.getaddrinfo",
        lambda *args: [(2, 1, 6, "", ("8.8.8.8", 443))],
    )
    path = tmp_path / "benchmark.json"
    path.write_text(json.dumps(config))
    if entry == "cli":
        monkeypatch.setattr(
            sys,
            "argv",
            ["llm-preflight", str(path), "--json", "--no-save", "--no-env-file"],
        )
        if state == "pass":
            cli.main()
        else:
            with pytest.raises(SystemExit) as exc:
                cli.main()
            assert exc.value.code == 1
        result = json.loads(capsys.readouterr().out)
    else:
        response = mcp._response(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "run_preflight",
                    "arguments": {"config": path.name, "confirm_paid_run": True},
                },
            },
            tmp_path,
        )
        assert response["result"]["isError"] is False
        result = response["result"]["structuredContent"]
    assert len(calls) == 1
    assert result["decision"]["state"] == state
    assert result["total_estimated_cost_usd"] == pytest.approx(0.00014)
    assert result["cost_confidence"] == "complete"
    assert result["provenance"]["validator_version"] == "output-schema-3"
    if state == "fail":
        assert result["decision"]["reason_code"] == "contract_failure"


@pytest.mark.parametrize("entry", ["cli", "mcp"])
@pytest.mark.parametrize("named", [False, True])
@pytest.mark.parametrize("container", ["object", "array"])
@pytest.mark.parametrize("matches", [False, True])
def test_enum_boolean_identity_through_cli_and_mcp(
    monkeypatch, tmp_path, capsys, entry, named, container, matches
):
    expected = {"enabled": True} if container == "object" else [True]
    output = expected if matches else ({"enabled": 1} if container == "object" else [1])
    invalid = {"enabled": 1} if container == "object" else [1]
    contract = {
        "prompt": "Return the approved enum member.",
        "validation": {"json_schema": {"type": container, "enum": [expected]}},
        "validation_fixtures": [
            {"name": "accepted", "response": json.dumps(expected), "expect": "pass"},
            {
                "name": "numeric impostor",
                "response": json.dumps(invalid),
                "expect": "fail",
            },
        ],
    }
    config = {
        "models": [
            {
                "provider": "openai",
                "model": "fixture-model",
                "api_key_env": None,
                "input_cost_per_million": 1,
                "output_cost_per_million": 2,
            }
        ],
        "warmups": 0,
        "repetitions": 1,
        "suite_repetitions": 1,
    }
    if named:
        config.update(prompts=[{"name": "enum-case", **contract}], profiles="enum-case")
    else:
        config.update(contract)
    event = {
        "choices": [{"delta": {"content": json.dumps(output)}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }
    body = ("data: " + json.dumps(event) + "\n\ndata: [DONE]\n").encode()
    calls = []

    def response(request, timeout):
        calls.append(request)
        return io.BytesIO(body)

    monkeypatch.setattr("llm_preflight.client.open_public_url", response)
    monkeypatch.setattr(
        "llm_preflight.security.socket.getaddrinfo",
        lambda *args: [(2, 1, 6, "", ("8.8.8.8", 443))],
    )
    path = tmp_path / "benchmark.json"
    path.write_text(json.dumps(config))
    if entry == "cli":
        monkeypatch.setattr(
            sys,
            "argv",
            ["llm-preflight", str(path), "--json", "--no-save", "--no-env-file"],
        )
        if matches:
            cli.main()
        else:
            with pytest.raises(SystemExit) as exc:
                cli.main()
            assert exc.value.code == 1
        result = json.loads(capsys.readouterr().out)
    else:
        reply = mcp._response(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "run_preflight",
                    "arguments": {"config": path.name, "confirm_paid_run": True},
                },
            },
            tmp_path,
        )
        assert reply["result"]["isError"] is False
        result = reply["result"]["structuredContent"]
    assert len(calls) == 1
    assert result["decision"]["state"] == ("pass" if matches else "fail")
    assert result["provenance"]["validator_version"] == "output-schema-3"
    assert result["total_estimated_cost_usd"] == pytest.approx(0.00014)
    if not matches:
        assert result["decision"]["reason_code"] == "contract_failure"


@pytest.mark.parametrize("retry", [False, True])
def test_protocol_cache_tier_cost_and_retry_completeness(monkeypatch, retry):
    from llm_preflight.runner import console_report, report

    calls = []
    body = b'data: {"choices":[{"delta":{"content":"billing"}}],"usage":{"prompt_tokens":201,"completion_tokens":10,"prompt_tokens_details":{"cached_tokens":80}}}\n\ndata: [DONE]\n'

    def response(request, timeout):
        calls.append(request)
        if retry and len(calls) == 1:
            raise TimeoutError("fixture timeout")
        return io.BytesIO(body)

    monkeypatch.setattr("llm_preflight.client.open_public_url", response)
    monkeypatch.setattr(
        "llm_preflight.security.socket.getaddrinfo",
        lambda *args: [(2, 1, 6, "", ("8.8.8.8", 443))],
    )
    monkeypatch.setattr("llm_preflight.client.time.sleep", lambda seconds: None)
    model = {
        "provider": "openai",
        "model": "fixture-model",
        "api_key_env": None,
        "input_cost_per_million": 1,
        "output_cost_per_million": 2,
        "pricing_tiers": [
            {
                "up_to_input_tokens": 200,
                "input_cost_per_million": 1,
                "output_cost_per_million": 2,
            },
            {
                "input_cost_per_million": 4,
                "output_cost_per_million": 8,
                "cached_input_cost_per_million": 1,
            },
        ],
    }
    events = []
    result = run_benchmark(
        {
            "prompt": "billing",
            "validation": {"exact": "billing"},
            "models": [model],
            "warmups": 0,
            "repetitions": 1,
            "request": {"retry": {"max_attempts": 2}},
        },
        progress=events.append,
    )
    assert len(calls) == (2 if retry else 1)
    assert result["priced_cost_usd"] == pytest.approx(0.000644)
    assert result["cost_coverage"]["unobserved_retry_requests"] == int(retry)
    assert result["cost_confidence"] == ("partial" if retry else "complete")
    assert result["decision"]["state"] == ("inconclusive" if retry else "pass")
    event = next(e for e in events if e["type"] == "request_complete")
    if retry:
        assert result["total_estimated_cost_usd"] is None
        assert event["estimated_cost_usd"] is None
        assert "Recommended: unavailable" in console_report(result)
    else:
        assert result["total_estimated_cost_usd"] == pytest.approx(0.000644)
        assert event["estimated_cost_usd"] == pytest.approx(0.000644)
    legacy = {k: v for k, v in result.items() if k != "cost_coverage"}
    assert "Recommended: unavailable" in report(legacy)
    assert "Recommended: unavailable" in console_report(legacy)
    assert "legacy cost completeness is unverified" in report(legacy)


@pytest.mark.parametrize("entry", ["cli", "mcp"])
@pytest.mark.parametrize("stage", ["run", "plan"])
@pytest.mark.parametrize("defect", ["schema", "pricing"])
def test_invalid_contract_or_strict_price_never_starts_generation(
    monkeypatch, tmp_path, capsys, entry, stage, defect
):
    calls = []
    monkeypatch.setattr(
        "llm_preflight.runner.create_client", lambda *args: calls.append(args)
    )
    config = {
        "prompt": "billing",
        "require_current_pricing": True,
        "models": [
            {
                "provider": "openai",
                "model": "fixture-model",
                "input_cost_per_million": 1,
                "output_cost_per_million": 2,
                "pricing_metadata": {
                    "source": "official provider pricing",
                    "as_of": "2020-01-01",
                },
            }
        ],
    }
    if defect == "schema":
        config["validation"] = {
            "json_schema": {"type": "number", "exclusiveMinimum": 0}
        }
    path = tmp_path / "benchmark.json"
    path.write_text(json.dumps(config))
    inspect_plan = defect == "pricing" and stage == "plan"
    if entry == "cli":
        arguments = ["llm-preflight", str(path), "--json", "--no-save", "--no-env-file"]
        if stage == "plan":
            arguments.append("--dry-run")
        monkeypatch.setattr(sys, "argv", arguments)
        if inspect_plan:
            cli.main()
            result = json.loads(capsys.readouterr().out)
            assert result["pricing_coverage"]["enforcement_ok"] is False
        else:
            with pytest.raises(SystemExit) as exc:
                cli.main()
            assert exc.value.code == 2
    else:
        response = mcp._response(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "dry_run_plan" if stage == "plan" else "run_preflight",
                    "arguments": {
                        "config": path.name,
                        **({"confirm_paid_run": True} if stage == "run" else {}),
                    },
                },
            },
            tmp_path,
        )
        assert response["result"]["isError"] is not inspect_plan
        if inspect_plan:
            assert (
                response["result"]["structuredContent"]["pricing_coverage"][
                    "enforcement_ok"
                ]
                is False
            )
    assert calls == []


@pytest.mark.parametrize("entry", ["runner", "cli", "mcp"])
@pytest.mark.parametrize("adapter", ["chat", "responses", "anthropic", "gemini"])
@pytest.mark.parametrize("reported", [False, True])
def test_usage_evidence_survives_protocol_and_automation(
    monkeypatch, tmp_path, capsys, entry, adapter, reported
):
    if adapter == "responses":
        payload = {"output_text": "billing"}
        if reported:
            payload["usage"] = {"input_tokens": 100, "output_tokens": 20}
        body = json.dumps(payload).encode()
    else:
        if adapter == "chat":
            event = {"choices": [{"delta": {"content": "billing"}}]}
            if reported:
                event["usage"] = {"prompt_tokens": 100, "completion_tokens": 20}
        elif adapter == "anthropic":
            event = {"type": "content_block_delta", "delta": {"text": "billing"}}
            if reported:
                event["usage"] = {"input_tokens": 100, "output_tokens": 20}
        else:
            event = {"candidates": [{"content": {"parts": [{"text": "billing"}]}}]}
            if reported:
                event["usageMetadata"] = {
                    "promptTokenCount": 100,
                    "candidatesTokenCount": 20,
                }
        # A later event without usage must not replace known counts with zero.
        body = (
            "data: " + json.dumps(event) + "\n\ndata: {}\n\ndata: [DONE]\n\n"
        ).encode()

    requests = []

    def response(request, timeout):
        requests.append(json.loads(request.data))
        return io.BytesIO(body)

    monkeypatch.setattr("llm_preflight.client.open_public_url", response)
    monkeypatch.setattr(
        "llm_preflight.security.socket.getaddrinfo",
        lambda *args: [(2, 1, 6, "", ("8.8.8.8", 443))],
    )
    model = {
        "provider": adapter if adapter in {"anthropic", "gemini"} else "openai",
        "model": "fixture-model",
        "api_key_env": None,
        "input_cost_per_million": 1,
        "output_cost_per_million": 2,
    }
    if adapter == "responses":
        model["adapter"] = "openai_responses"
    config = {
        "prompt": "I was charged twice",
        "validation": {"exact": "billing"},
        "models": [model],
        "warmups": 0,
        "repetitions": 1,
    }
    path = tmp_path / "benchmark.json"
    path.write_text(json.dumps(config))
    if entry == "runner":
        result = run_benchmark(config)
    elif entry == "cli":
        monkeypatch.setattr(
            sys,
            "argv",
            ["llm-preflight", str(path), "--json", "--no-save", "--no-env-file"],
        )
        if reported:
            cli.main()
        else:
            with pytest.raises(SystemExit) as exc:
                cli.main()
            assert exc.value.code == 3
        result = json.loads(capsys.readouterr().out)
    else:
        response = mcp._response(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "run_preflight",
                    "arguments": {"config": path.name, "confirm_paid_run": True},
                },
            },
            tmp_path,
        )
        assert response["result"]["isError"] is False
        result = response["result"]["structuredContent"]
    assert len(requests) == 1
    assert result["models"][0]["summary"]["valid_output_rate"] == 1
    assert result["unpriced_models"] == []
    assert result["cost_confidence"] == ("complete" if reported else "unknown")
    assert result["decision"]["state"] == ("pass" if reported else "inconclusive")
    if reported:
        assert result["total_estimated_cost_usd"] == pytest.approx(0.00014)
    else:
        assert result["total_estimated_cost_usd"] is None
        assert result["priced_cost_usd"] is None
