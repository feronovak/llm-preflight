import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from llm_preflight import mcp, retirements
from llm_preflight.retirements import retirement_report

META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}


@pytest.mark.parametrize(
    ("method", "payload_key"),
    [
        ("server/discover", "supportedVersions"),
        ("tools/list", "tools"),
        ("resources/list", "resources"),
        ("resources/read", "contents"),
    ],
)
def test_modern_cacheable_results_have_private_zero_ttl(tmp_path, method, payload_key):
    params = {"_meta": META}
    if method == "resources/read":
        params["uri"] = mcp.SAFE_WORKFLOW_URI
    response = mcp._response(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, tmp_path
    )

    result = response["result"]
    assert payload_key in result
    assert type(result["ttlMs"]) is int
    assert result["ttlMs"] == 0
    assert result["cacheScope"] == "private"
    assert result["resultType"] == "complete"


@pytest.mark.parametrize("method", ["tools/list", "resources/list", "resources/read"])
def test_standard_cacheable_results_keep_legacy_shape(tmp_path, method):
    params = {"uri": mcp.SAFE_WORKFLOW_URI} if method == "resources/read" else {}
    response = mcp._response(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, tmp_path
    )

    assert "result" in response
    assert {"ttlMs", "cacheScope", "resultType"}.isdisjoint(response["result"])


def test_mcp_live_run_uses_a_workspace_contained_config_env_reference(tmp_path):
    config_path = tmp_path / "benchmark.json"
    config = {
        "env_file": "credentials/team.env",
        "prompt": "Reply with ok.",
        "models": [{"provider": "mock", "model": "local", "response": "ok"}],
    }
    config_path.write_text(json.dumps(config))

    assert mcp._env_path({}, config_path, tmp_path, config) == (
        tmp_path / "credentials/team.env"
    )


def test_standard_mcp_clients_negotiate_any_initialize_version_and_discover_tools(
    tmp_path,
):
    (tmp_path / "benchmark.json").write_text(
        json.dumps(
            {
                "prompt": "Reply with ok.",
                "validation": {"exact": "ok"},
                "models": [{"provider": "mock", "model": "local", "response": "ok"}],
            }
        )
    )
    initialized = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "agent", "version": "1.0"},
            },
        },
        tmp_path,
    )
    initialized_with_2026_metadata = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "initialize",
            "params": {
                "protocolVersion": "2099-01-01",
                "_meta": {"io.modelcontextprotocol/protocolVersion": "2099-01-01"},
            },
        },
        tmp_path,
    )
    listed = mcp._response(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
        tmp_path,
    )
    plan = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "dry_run_plan",
                "arguments": {"config": "benchmark.json"},
            },
        },
        tmp_path,
    )

    assert initialized["result"]["protocolVersion"] == "2025-06-18"
    assert initialized_with_2026_metadata["result"]["protocolVersion"] == "2025-06-18"
    instructions = initialized["result"]["instructions"]
    assert "report the dry_run_plan `retirements` decision" in instructions
    assert "`fail` for a retired model" in instructions
    assert "`inconclusive` for a retiring model or a stale snapshot row" in instructions
    assert [tool["name"] for tool in listed["result"]["tools"]] == [
        "audit_source",
        "validate_config",
        "dry_run_plan",
        "run_preflight",
        "diff_baseline",
        "verify",
        "gate",
    ]
    assert "resultType" not in listed["result"]
    assert plan["result"]["isError"] is False
    assert "resultType" not in plan["result"]


def test_standard_mcp_ping_returns_an_empty_result(tmp_path):
    response = mcp._response(
        {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}, tmp_path
    )

    assert response["result"] == {}


def test_standard_mcp_describes_safe_tools_and_exposes_the_safe_workflow(tmp_path):
    initialized = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
        tmp_path,
    )
    tools = mcp._response(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        tmp_path,
    )
    resources = mcp._response(
        {"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}},
        tmp_path,
    )
    workflow = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "resources/read",
            "params": {"uri": "llm-preflight://guides/safe-workflow"},
        },
        tmp_path,
    )

    assert initialized["result"]["capabilities"] == {"tools": {}, "resources": {}}
    by_name = {tool["name"]: tool for tool in tools["result"]["tools"]}
    for name in ("validate_config", "dry_run_plan", "diff_baseline"):
        assert by_name[name]["annotations"] == {
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": False,
        }
        schema = by_name[name]["outputSchema"]
        assert schema["oneOf"][0] == {
            "type": "object",
            "properties": {"error": {"type": "string"}},
            "required": ["error"],
            "additionalProperties": False,
        }
        assert schema["oneOf"][1]["type"] == "object"
    assert by_name["audit_source"]["annotations"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    assert by_name["audit_source"]["inputSchema"] == {
        "type": "object",
        "properties": {"path": {"type": "string", "minLength": 1}},
        "additionalProperties": False,
    }
    assert by_name["run_preflight"]["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": True,
    }
    assert by_name["validate_config"]["outputSchema"]["oneOf"][1]["required"] == [
        "ok",
        "name",
        "models",
    ]
    assert by_name["dry_run_plan"]["outputSchema"]["oneOf"][1]["required"] == [
        "ok",
        "models",
        "requests",
        "possible_requests",
        "retry_max_attempts",
        "estimated_cost_usd",
        "maximum_estimated_cost_usd",
        "pricing_ledger",
        "pricing_fingerprint",
        "pricing_warnings",
        "pricing_coverage",
        "smoke_eligibility",
        "retirements",
        "benchmark",
        "tests",
        "test_breakdown",
        "configuration_warnings",
        "presets",
        "request",
        "save_responses",
        "stop_on",
    ]
    assert by_name["run_preflight"]["outputSchema"]["oneOf"][1]["required"] == [
        "decision",
        "models",
    ]
    assert resources["result"]["resources"] == [
        {
            "uri": "llm-preflight://guides/safe-workflow",
            "name": "safe-workflow",
            "title": "Safe LLM Preflight Workflow",
            "description": "No-spend-first workflow and explicit paid-run boundary.",
            "mimeType": "text/markdown",
        }
    ]
    content = workflow["result"]["contents"][0]
    assert content["uri"] == "llm-preflight://guides/safe-workflow"
    assert "dry_run_plan" in content["text"]
    assert "confirm_paid_run: true" in content["text"]
    assert "application's prompt and response contract" in " ".join(
        content["text"].split()
    )
    assert "llm-preflight report" in content["text"]


def test_mcp_config_applies_model_aliases_and_provider_presets(tmp_path):
    path = tmp_path / "benchmark.json"
    path.write_text(
        json.dumps(
            {
                "prompt": "Reply with ok.",
                "aliases": {
                    "local": {
                        "provider": "mock",
                        "model": "local",
                        "response": "ok",
                    }
                },
                "models": ["local"],
                "presets": ["low-latency"],
            }
        )
    )

    config = mcp._config(path)

    assert config["models"][0]["provider"] == "mock"
    assert config["request"]["temperature"] == 0
    assert config["request"]["max_output_tokens"] == 256


def test_discover_and_mock_tools_are_modern_and_read_only(tmp_path):
    config = tmp_path / "benchmark.json"
    config.write_text(
        json.dumps(
            {
                "prompt": "Reply with ok.",
                "validation": {"exact": "ok"},
                "models": [{"provider": "mock", "model": "local", "response": "ok"}],
            }
        )
    )
    discover = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "server/discover",
            "params": {"_meta": META},
        },
        tmp_path,
    )
    listed = mcp._response(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {"_meta": META}},
        tmp_path,
    )
    plan = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "_meta": META,
                "name": "dry_run_plan",
                "arguments": {"config": "benchmark.json"},
            },
        },
        tmp_path,
    )
    assert discover["result"]["supportedVersions"] == ["2026-07-28"]
    assert [tool["name"] for tool in listed["result"]["tools"]] == [
        "audit_source",
        "validate_config",
        "dry_run_plan",
        "run_preflight",
        "diff_baseline",
        "verify",
        "gate",
    ]
    assert plan["result"]["isError"] is False
    assert plan["result"]["structuredContent"]["pricing_coverage"]["summary"] == {
        "selected": 1,
        "billable": 0,
        "exempt": 1,
        "priced": 0,
        "undated": 0,
        "stale": 0,
        "unknown": 0,
    }
    assert plan["result"]["structuredContent"]["smoke_eligibility"]["summary"] == {
        "discovered": 1,
        "eligible": 0,
        "needs_review": 1,
    }


def test_dry_run_plan_carries_the_same_retirement_report_as_the_cli(
    tmp_path, monkeypatch
):
    url = "https://example.test/deprecations"
    monkeypatch.setattr(
        retirements,
        "PUBLIC_RETIREMENTS",
        {
            ("openai", "gpt-gone"): {
                "status": "deprecated",
                "retirement_date": "2026-10-01",
                "replacement": "gpt-new",
                "as_of": "2026-10-01",
                "source_url": url,
            },
            ("openai", "gpt-new"): {
                "status": "active",
                "as_of": "2026-10-01",
                "source_url": url,
            },
        },
    )
    monkeypatch.setattr(mcp, "today_utc", lambda: date(2026, 10, 9))
    (tmp_path / "benchmark.json").write_text(
        json.dumps(
            {"prompt": "hi", "models": [{"provider": "openai", "model": "gpt-gone"}]}
        )
    )

    plan = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "dry_run_plan",
                "arguments": {"config": "benchmark.json"},
            },
        },
        tmp_path,
    )

    content = plan["result"]["structuredContent"]
    assert plan["result"]["isError"] is False
    assert content["ok"] is True
    assert content["retirements"] == retirement_report(
        [{"provider": "openai", "model": "gpt-gone"}], date(2026, 10, 9)
    )
    assert content["retirements"]["decision"] == "fail"
    assert content["retirements"]["next_commands"] == [
        'llm-preflight --quick "<your prompt>" --models openai:gpt-gone,openai:gpt-new --dry-run'
    ]


def test_dry_run_plan_omits_a_next_command_whose_replacement_is_already_selected(
    tmp_path, monkeypatch
):
    url = "https://example.test/deprecations"
    monkeypatch.setattr(
        retirements,
        "PUBLIC_RETIREMENTS",
        {
            ("openai", "gpt-gone"): {
                "status": "deprecated",
                "retirement_date": "2026-10-01",
                "replacement": "gpt-new",
                "as_of": "2026-10-01",
                "source_url": url,
            },
            ("openai", "gpt-new"): {
                "status": "active",
                "as_of": "2026-10-01",
                "source_url": url,
            },
        },
    )
    monkeypatch.setattr(mcp, "today_utc", lambda: date(2026, 10, 9))
    (tmp_path / "benchmark.json").write_text(
        json.dumps(
            {
                "prompt": "hi",
                "models": [
                    {"provider": "openai", "model": "gpt-gone"},
                    {"provider": "openai", "model": "gpt-new"},
                ],
            }
        )
    )

    plan = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "dry_run_plan",
                "arguments": {"config": "benchmark.json"},
            },
        },
        tmp_path,
    )

    content = plan["result"]["structuredContent"]
    assert content["retirements"]["decision"] == "fail"
    gone = content["retirements"]["models"][0]
    assert gone["next_step"] == (
        f"provider names gpt-new as the replacement; it is already in this plan ({url})"
    )
    assert "next_command" not in gone
    assert content["retirements"]["next_commands"] == []


def test_live_run_requires_paid_confirmation(tmp_path):
    config = tmp_path / "benchmark.json"
    config.write_text(
        '{"prompt":"ok","models":[{"provider":"openai","model":"gpt-test"}]}'
    )
    response = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "_meta": {
                    **META,
                    "io.modelcontextprotocol/clientCapabilities": {"elicitation": {}},
                },
                "name": "run_preflight",
                "arguments": {"config": "benchmark.json"},
            },
        },
        tmp_path,
    )
    assert response["result"]["resultType"] == "input_required"


def test_elicitation_request_state_preserves_env_file_for_paid_retry(tmp_path):
    (tmp_path / "benchmark.json").write_text(
        '{"prompt":"ok","models":[{"provider":"openai","model":"gpt-test"}]}'
    )

    response = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "_meta": {
                    **META,
                    "io.modelcontextprotocol/clientCapabilities": {"elicitation": {}},
                },
                "name": "run_preflight",
                "arguments": {
                    "config": "benchmark.json",
                    "env_file": "credentials/approved.env",
                },
            },
        },
        tmp_path,
    )

    assert response["result"] == {
        "resultType": "input_required",
        "inputRequests": {
            "paid_run": {
                "method": "elicitation/create",
                "params": {
                    "mode": "form",
                    "message": "This preflight can make paid provider requests. Continue?",
                    "requestedSchema": {
                        "type": "object",
                        "properties": {"confirm": {"type": "boolean"}},
                        "required": ["confirm"],
                    },
                },
            }
        },
        "requestState": (
            '{"config": "benchmark.json", "env_file": "credentials/approved.env"}'
        ),
    }


def test_live_run_without_elicitation_returns_a_protocol_capability_error(tmp_path):
    (tmp_path / "benchmark.json").write_text(
        '{"prompt":"ok","models":[{"provider":"openai","model":"gpt-test"}]}'
    )
    response = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "_meta": META,
                "name": "run_preflight",
                "arguments": {"config": "benchmark.json"},
            },
        },
        tmp_path,
    )
    assert response["error"]["code"] == -32021


def test_standard_live_run_without_confirmation_returns_a_remedy(tmp_path):
    (tmp_path / "benchmark.json").write_text(
        '{"prompt":"ok","models":[{"provider":"openai","model":"gpt-test"}]}'
    )
    response = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "run_preflight",
                "arguments": {"config": "benchmark.json"},
            },
        },
        tmp_path,
    )

    assert response["result"]["isError"] is True
    assert "confirm_paid_run" in response["result"]["content"][0]["text"]


def test_unconfirmed_live_run_never_loads_the_env_file(monkeypatch, tmp_path):
    (tmp_path / "benchmark.json").write_text(
        '{"prompt":"ok","models":[{"provider":"openai","model":"gpt-test"}]}'
    )
    (tmp_path / ".env.production").write_text("TEST_MCP_SECRET=must-not-load\n")
    monkeypatch.delenv("TEST_MCP_SECRET", raising=False)

    response = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "_meta": {
                    **META,
                    "io.modelcontextprotocol/clientCapabilities": {"elicitation": {}},
                },
                "name": "run_preflight",
                "arguments": {"config": "benchmark.json"},
            },
        },
        tmp_path,
    )

    assert response["result"]["resultType"] == "input_required"
    assert "TEST_MCP_SECRET" not in os.environ


def test_default_live_env_symlink_must_stay_in_the_mcp_workspace(monkeypatch, tmp_path):
    (tmp_path / "benchmark.json").write_text(
        '{"prompt":"ok","models":[{"provider":"openai","model":"gpt-test"}]}'
    )
    outside = tmp_path.parent / "outside.env"
    outside.write_text("TEST_MCP_SECRET=must-not-load\n")
    (tmp_path / ".env.production").symlink_to(outside)
    monkeypatch.delenv("TEST_MCP_SECRET", raising=False)
    monkeypatch.setattr(mcp, "run_benchmark", lambda config: {"unexpected": config})

    response = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "run_preflight",
                "arguments": {
                    "config": "benchmark.json",
                    "confirm_paid_run": True,
                },
            },
        },
        tmp_path,
    )

    assert response["result"]["isError"] is True
    assert (
        "path must stay within the MCP workspace"
        in response["result"]["content"][0]["text"]
    )
    assert "TEST_MCP_SECRET" not in os.environ


def test_explicit_live_env_symlink_must_stay_in_the_mcp_workspace(
    monkeypatch, tmp_path
):
    (tmp_path / "benchmark.json").write_text(
        '{"prompt":"ok","models":[{"provider":"openai","model":"gpt-test"}]}'
    )
    outside = tmp_path.parent / "outside.env"
    outside.write_text("TEST_MCP_SECRET=must-not-load\n")
    (tmp_path / "credentials.env").symlink_to(outside)
    monkeypatch.delenv("TEST_MCP_SECRET", raising=False)
    monkeypatch.setattr(mcp, "run_benchmark", lambda config: {"unexpected": config})

    response = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "run_preflight",
                "arguments": {
                    "config": "benchmark.json",
                    "env_file": "credentials.env",
                    "confirm_paid_run": True,
                },
            },
        },
        tmp_path,
    )

    assert response["result"]["isError"] is True
    assert (
        "path must stay within the MCP workspace"
        in response["result"]["content"][0]["text"]
    )
    assert "TEST_MCP_SECRET" not in os.environ


def test_mock_run_never_loads_the_env_file(monkeypatch, tmp_path):
    (tmp_path / "benchmark.json").write_text(
        '{"prompt":"ok","validation":{"exact":"ok"},'
        '"models":[{"provider":"mock","model":"local","response":"ok"}]}'
    )
    (tmp_path / ".env.production").write_text("TEST_MCP_SECRET=must-not-load\n")
    monkeypatch.delenv("TEST_MCP_SECRET", raising=False)

    response = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "run_preflight",
                "arguments": {"config": "benchmark.json"},
            },
        },
        tmp_path,
    )

    assert response["result"]["isError"] is False
    assert "TEST_MCP_SECRET" not in os.environ
    assert response["result"]["structuredContent"]["decision"] == {
        "schema_version": 1,
        "state": "inconclusive",
        "reason_code": "degraded_evidence",
        "reason": "Evidence is degraded; resolve blocking warnings before using this result.",
        "safe_next_command": f"llm-preflight {tmp_path / 'benchmark.json'} --doctor --json",
        "blocking_warnings": ["Mock-only runs do not provide live-provider evidence."],
    }


def test_mcp_returns_a_tool_error_for_current_pricing_gate_failures(tmp_path):
    (tmp_path / "benchmark.json").write_text(
        '{"prompt":"ok","require_current_pricing":true,'
        '"models":[{"provider":"openai_compatible","model":"unpriced"}]}'
    )

    response = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "run_preflight",
                "arguments": {
                    "config": "benchmark.json",
                    "confirm_paid_run": True,
                },
            },
        },
        tmp_path,
    )

    assert response["result"]["isError"] is True
    assert "pricing coverage is incomplete" in response["result"]["content"][0]["text"]


def test_confirmed_live_run_enforces_request_and_cost_caps(monkeypatch, tmp_path):
    (tmp_path / "benchmark.json").write_text(
        '{"prompt":"ok","max_requests":1,'
        '"models":[{"provider":"openai","model":"a"},'
        '{"provider":"openai","model":"b"}]}'
    )
    monkeypatch.setattr(
        mcp,
        "run_benchmark",
        lambda config: (_ for _ in ()).throw(AssertionError("budget gate skipped")),
    )

    response = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "run_preflight",
                "arguments": {
                    "config": "benchmark.json",
                    "confirm_paid_run": True,
                },
            },
        },
        tmp_path,
    )

    assert response["result"]["isError"] is True
    assert "max_requests" in response["result"]["content"][0]["text"]


def test_tool_schema_rejects_unknown_arguments(tmp_path):
    response = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "_meta": META,
                "name": "validate_config",
                "arguments": {"config": "benchmark.json", "unexpected": True},
            },
        },
        tmp_path,
    )
    assert response["error"]["code"] == -32602


def test_non_object_params_return_a_protocol_error(tmp_path):
    response = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": [],
        },
        tmp_path,
    )

    assert response["error"]["code"] == -32602


def test_stdio_server_negotiates_any_version_then_handles_discovery(tmp_path):
    process = subprocess.Popen(
        [sys.executable, "-m", "llm_preflight.mcp", "--workspace", str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":'
        '{"protocolVersion":"2024-11-05","capabilities":{},'
        '"clientInfo":{"name":"agent","version":"1.0"}}}\n'
    )
    process.stdin.write(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "server/discover",
                "params": {"_meta": META},
            }
        )
        + "\n"
    )
    process.stdin.close()
    first = json.loads(process.stdout.readline())
    second = json.loads(process.stdout.readline())
    process.wait(timeout=5)
    assert first["result"]["protocolVersion"] == "2025-06-18"
    assert second["result"]["supportedVersions"] == ["2026-07-28"]


def test_agent_guidance_reports_the_retirement_decision_that_ok_does_not_reflect():
    root = Path(__file__).parent.parent
    skill = (root / "plugins/llm-preflight/skills/llm-preflight/SKILL.md").read_text()
    guide = (root / "docs/automation/mcp.md").read_text()

    for text in (mcp.SAFE_WORKFLOW, skill, guide):
        step = " ".join(text.split())
        assert "`retirements` decision" in step
        assert "`fail` means a selected model is retired" in step
        assert (
            "`inconclusive` means one is retiring or its snapshot row is stale" in step
        )
    for text in (mcp.SAFE_WORKFLOW, skill):
        assert "`ok` does not reflect it." in " ".join(text.split())
    assert "`ok` stays `true` for a retired model" in " ".join(guide.split())


def test_dry_run_plan_returns_the_cli_dry_run_plan_for_the_same_config(
    tmp_path, monkeypatch, capsys
):
    from llm_preflight import cli

    monkeypatch.setattr(cli, "today_utc", lambda: date(2026, 10, 9))
    monkeypatch.setattr(mcp, "today_utc", lambda: date(2026, 10, 9))
    config = tmp_path / "benchmark.json"
    config.write_text(
        json.dumps(
            {
                "name": "parity",
                "prompt": "Reply with ok.",
                "presets": ["json"],
                "request": {"max_output_tokens": 64},
                "save_responses": "failures",
                "stop_on": "any-fail",
                "models": [
                    {"provider": "mock", "model": "local", "response": "ok"},
                    {"provider": "anthropic", "model": "claude-3-haiku-20240307"},
                    {
                        "provider": "openai_compatible",
                        "model": "router",
                        "base_url": "https://router.example.test/v1",
                        "headers": {"X-Title": "parity"},
                    },
                ],
            }
        )
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["llm-preflight", str(config), "--dry-run", "--json", "--no-env-file"],
    )
    cli.main()
    cli_plan = json.loads(capsys.readouterr().out)

    content = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "dry_run_plan",
                "arguments": {"config": "benchmark.json"},
            },
        },
        tmp_path,
    )["result"]["structuredContent"]

    mcp_only = {"ok", "pricing_ledger", "pricing_fingerprint"}
    assert set(content) - set(cli_plan) == mcp_only
    assert {key: content[key] for key in cli_plan} == cli_plan
    assert cli_plan["configuration_warnings"]
    assert cli_plan["retirements"]["decision"] == "fail"


@pytest.mark.parametrize(
    ("name", "json_type"),
    [
        ("review", "string"),
        (None, "null"),
        (7, "number"),
        (1.5, "number"),
        (False, "boolean"),
        ({"team": "review"}, "object"),
        (["review"], "array"),
    ],
)
def test_validate_config_name_schema_accepts_every_preserved_json_name(
    tmp_path, name, json_type
):
    config = {
        "name": name,
        "prompt": "Reply with ok.",
        "models": [{"provider": "mock", "model": "local", "response": "ok"}],
    }
    (tmp_path / "benchmark.json").write_text(json.dumps(config))
    tools = mcp._response({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, tmp_path)
    response = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "validate_config",
                "arguments": {"config": "benchmark.json"},
            },
        },
        tmp_path,
    )

    result = response["result"]
    assert result["isError"] is False
    assert result["structuredContent"] == {"ok": True, "name": name, "models": 1}
    schema = next(
        tool["outputSchema"]
        for tool in tools["result"]["tools"]
        if tool["name"] == "validate_config"
    )
    assert json_type in schema["oneOf"][1]["properties"]["name"]["type"]


AUDIT_URL = "https://example.test/deprecations"
AUDIT_TABLE = {
    ("openai", "gpt-gone"): {
        "status": "retired",
        "retirement_date": "2026-06-01",
        "replacement": "gpt-new",
        "as_of": "2026-10-01",
        "source_url": AUDIT_URL,
    },
    ("openai", "gpt-new"): {
        "status": "active",
        "as_of": "2026-10-01",
        "source_url": AUDIT_URL,
    },
}


def _audit(workspace, arguments, meta=None):
    params = {"name": "audit_source", "arguments": arguments}
    if meta is not None:
        params["_meta"] = meta
    return mcp._response(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params},
        workspace,
    )


@pytest.fixture
def audit_snapshot(monkeypatch):
    monkeypatch.setattr(retirements, "PUBLIC_RETIREMENTS", AUDIT_TABLE)
    monkeypatch.setattr(mcp, "today_utc", lambda: date(2026, 10, 9))


def test_audit_source_reports_a_retired_model_in_a_workspace_without_a_config(
    tmp_path, audit_snapshot
):
    (tmp_path / "app.py").write_text('model = "gpt-gone"\nnext = "gpt-new"\n')

    result = _audit(tmp_path, {})["result"]

    content = result["structuredContent"]
    assert result["isError"] is False
    assert content["decision"] == "fail"
    assert content["root"] == str(tmp_path)
    assert content["network_accessed"] is False
    assert content["files_scanned"] == 1
    assert [
        (item["path"], item["line"], item["model"]) for item in content["references"]
    ] == [("app.py", 1, "gpt-gone"), ("app.py", 2, "gpt-new")]
    assert content["references"][0]["retirement"]["status"] == "retired"
    assert content["next_commands"] == [
        'llm-preflight --quick "<your prompt>" --models openai:gpt-gone,openai:gpt-new --dry-run'
    ]
    assert [block["type"] for block in result["content"]] == ["text", "text"]
    assert result["content"][0]["text"] == (
        "Decision: fail — 1 file audited; 2 model references: "
        "1 retired, 0 retiring or stale, 0 unknown."
    )
    assert json.loads(result["content"][1]["text"]) == content


def test_audit_source_matches_the_cli_json_and_first_text_line(
    tmp_path, audit_snapshot, monkeypatch, capsys
):
    from llm_preflight import cli

    monkeypatch.setattr(cli, "today_utc", lambda: date(2026, 10, 9))
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text('a = "gpt-gone"\nb = "gpt-mystery"\n')
    (tmp_path / "models.yaml").write_text("model: gpt-new\n")
    (tmp_path / "blob.json").write_bytes('{"model": "gpt-gone"}'.encode("utf-16"))
    monkeypatch.setattr(
        sys, "argv", ["llm-preflight", "--audit-source", str(tmp_path), "--json"]
    )
    cli.main()
    cli_json = json.loads(capsys.readouterr().out)
    monkeypatch.setattr(sys, "argv", ["llm-preflight", "--audit-source", str(tmp_path)])
    cli.main()
    cli_first_line = capsys.readouterr().out.splitlines()[0]

    result = _audit(tmp_path, {})["result"]

    assert result["structuredContent"] == cli_json
    assert cli_json["files_unreadable"] == 1
    assert result["content"][0]["text"] == cli_first_line


@pytest.mark.parametrize(
    ("path", "decision"),
    [
        ("src", "fail"),
        ("src/app.py", "fail"),
        ("docs", "none"),
        ("empty", "inconclusive"),
    ],
)
def test_audit_source_audits_a_workspace_relative_directory_or_file(
    tmp_path, audit_snapshot, path, decision
):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text('a = "gpt-gone"\n')
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "models.json").write_text('{"model": "gpt-mystery"}\n')
    (tmp_path / "empty").mkdir()

    result = _audit(tmp_path, {"path": path})["result"]

    assert result["isError"] is False
    assert result["structuredContent"]["root"] == str(tmp_path / path)
    assert result["structuredContent"]["decision"] == decision


def test_audit_source_that_reads_nothing_is_inconclusive(tmp_path, audit_snapshot):
    (tmp_path / "README.md").write_text('model = "gpt-gone"\n')

    result = _audit(tmp_path, {})["result"]

    content = result["structuredContent"]
    assert result["isError"] is False
    assert content["files_scanned"] == 0
    assert content["references"] == []
    assert content["decision"] == "inconclusive"
    assert result["content"][0]["text"].startswith(
        "Decision: inconclusive — nothing was audited: "
    )


@pytest.mark.parametrize("escape", ["..", "../outside", "absolute", "linked"])
def test_audit_source_never_reads_outside_the_workspace(
    tmp_path, audit_snapshot, escape
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "app.py").write_text('a = "gpt-gone"\n')
    (workspace / "linked").symlink_to(outside, target_is_directory=True)
    path = str(outside) if escape == "absolute" else escape

    response = _audit(workspace, {"path": path})

    result = response["result"]
    assert result["isError"] is True
    assert set(result["structuredContent"]) == {"error"}
    assert result["structuredContent"]["error"] in {
        "path must stay within the MCP workspace",
        "paths must be relative to the MCP workspace",
    }
    assert "gpt-gone" not in json.dumps(response)


def test_audit_source_of_a_missing_path_is_a_tool_error(tmp_path, audit_snapshot):
    result = _audit(tmp_path, {"path": "missing"}, META)["result"]

    assert result["isError"] is True
    assert result["resultType"] == "complete"
    assert "audit source path does not exist" in result["structuredContent"]["error"]


@pytest.mark.parametrize(
    "arguments", [{"path": ""}, {"path": 7}, {"all": True}, {"path": ".", "ci": True}]
)
def test_audit_source_rejects_arguments_outside_its_schema(tmp_path, arguments):
    assert _audit(tmp_path, arguments)["error"]["code"] == -32602


def test_audit_source_on_the_2026_path_is_complete(tmp_path, audit_snapshot):
    (tmp_path / "app.py").write_text('a = "gpt-new"\n')

    result = _audit(tmp_path, {"path": "."}, META)["result"]

    assert result["isError"] is False
    assert result["resultType"] == "complete"
    assert result["structuredContent"]["decision"] == "pass"


def test_audit_source_opens_no_network_connection(
    tmp_path, audit_snapshot, monkeypatch
):
    import socket

    def refuse(*args, **kwargs):
        raise AssertionError("audit_source opened a network connection")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    (tmp_path / "app.py").write_text('a = "gpt-gone"\n')

    result = _audit(tmp_path, {})["result"]

    assert result["isError"] is False
    assert result["structuredContent"]["network_accessed"] is False


def test_agent_guidance_starts_a_repository_without_a_config_with_audit_source(
    tmp_path,
):
    root = Path(__file__).parent.parent
    skill = (root / "plugins/llm-preflight/skills/llm-preflight/SKILL.md").read_text()
    guide = (root / "docs/automation/mcp.md").read_text()
    instructions = mcp._response(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, tmp_path
    )["result"]["instructions"]

    for text in (mcp.SAFE_WORKFLOW, skill, guide, instructions):
        step = " ".join(text.split())
        assert "audit_source" in step
        assert "no benchmark config" in step
        assert "`pass`" in step
        assert "only literal model IDs" in step
    assert "| `audit_source` |" in guide


def test_audit_source_result_is_utf8_text_for_a_name_that_is_not(
    tmp_path, audit_snapshot, non_utf8_file_names
):
    (tmp_path / os.fsdecode(b"bad\xff.py")).write_text('q = "gpt-gone"\n')

    response = _audit(tmp_path, {})

    result = response["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["decision"] == "fail"
    assert result["structuredContent"]["references"][0]["path"] == "bad\\xff.py"
    # A lone surrogate cannot be encoded, so this fails on any escaped byte.
    json.dumps(response, ensure_ascii=False).encode("utf-8")


def test_audit_source_redacts_secret_like_paths_that_the_cli_json_keeps(
    tmp_path, audit_snapshot, monkeypatch, capsys
):
    from llm_preflight import cli

    monkeypatch.setattr(cli, "today_utc", lambda: date(2026, 10, 9))
    (tmp_path / "sk-demo").mkdir()
    (tmp_path / "sk-demo" / "app.py").write_text('a = "gpt-gone"\n')
    monkeypatch.setattr(
        sys, "argv", ["llm-preflight", "--audit-source", str(tmp_path), "--json"]
    )
    cli.main()
    cli_json = json.loads(capsys.readouterr().out)

    content = _audit(tmp_path, {})["result"]["structuredContent"]

    assert cli_json["references"][0]["path"] == "sk-demo/app.py"
    assert content["references"][0]["path"] == "[REDACTED]/app.py"
    for text in (
        (Path(__file__).parent.parent / "docs/automation/mcp.md").read_text(),
        (Path(__file__).parent.parent / "CHANGELOG.md").read_text(),
    ):
        assert "with secret-like strings redacted" in " ".join(text.split())


# Proof-of-preflight tools

PROOF_GITHUB = {
    "GITHUB_REPOSITORY": "acme/app",
    "GITHUB_WORKFLOW": "preflight",
    "GITHUB_RUN_ID": "4425592351",
    "GITHUB_RUN_ATTEMPT": "1",
    "GITHUB_SHA": "d20ace7968ba43c0219f62d71334c1095bab1602",
    "GITHUB_SERVER_URL": "https://github.com",
}
PROOF_CONFIG = {
    "name": "proof",
    "prompt": "Reply with ok.",
    "validation": {"exact": "ok"},
    "prompts": [{"name": "json", "prompt": "Return JSON.", "validation": {}}],
    "models": [{"provider": "mock", "model": "local", "response": "ok"}],
    "repetitions": 1,
    "warmups": 0,
}


def _cli(monkeypatch, capsys, *arguments):
    from llm_preflight import cli

    monkeypatch.setattr(sys, "argv", ["llm-preflight", *map(str, arguments)])
    try:
        cli.main()
    except SystemExit as exc:
        code = exc.code
    else:
        code = 0
    return code, capsys.readouterr().out


@pytest.fixture
def proof_workspace(tmp_path, monkeypatch, capsys):
    """A workspace with a config and the CI record of a mock run of it."""
    from llm_preflight import cli

    for name in PROOF_GITHUB:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "benchmark.json").write_text(json.dumps(PROOF_CONFIG))
    code, _ = _cli(
        monkeypatch,
        capsys,
        "benchmark.json",
        "--prompt",
        "json",
        "--output-dir",
        "results",
    )
    assert code == 3
    (result,) = (tmp_path / "results").glob("*.json")
    # The verifier's clock is the run's own date, so freshness never depends on
    # when the suite runs.
    ran = date.fromisoformat(json.loads(result.read_text())["timestamp"][:10])
    monkeypatch.setattr(cli, "today_utc", lambda: ran)
    monkeypatch.setattr(mcp, "today_utc", lambda: ran)
    with monkeypatch.context() as scoped:
        for name, value in PROOF_GITHUB.items():
            scoped.setenv(name, value)
        assert _cli(monkeypatch, capsys, "attest", result)[0] == 0
    return tmp_path


def _tool(workspace, name, arguments, meta=None):
    params = {"name": name, "arguments": arguments}
    if meta is not None:
        params["_meta"] = meta
    return mcp._response(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params},
        workspace,
    )


def _record_name(workspace):
    (record,) = (workspace / "results").glob("*.preflight.json")
    return record.relative_to(workspace).as_posix()


@pytest.mark.parametrize("meta", [None, META], ids=["standard", "2026"])
def test_verify_returns_the_cli_json_and_first_text_line(
    proof_workspace, monkeypatch, capsys, meta
):
    record = _record_name(proof_workspace)
    _, cli_json = _cli(
        monkeypatch, capsys, "verify", proof_workspace / record, "--json"
    )
    _, cli_text = _cli(monkeypatch, capsys, "verify", proof_workspace / record)

    result = _tool(proof_workspace, "verify", {"record": record}, meta)["result"]

    assert result["isError"] is False
    assert result["structuredContent"] == json.loads(cli_json)
    assert result["content"][0]["text"] == cli_text.splitlines()[0]
    assert result["content"][0]["text"] == "Verify: integrity intact; freshness fresh."
    assert json.loads(result["content"][1]["text"]) == result["structuredContent"]
    assert ("resultType" in result) is (meta is not None)


@pytest.mark.parametrize("meta", [None, META], ids=["standard", "2026"])
def test_gate_returns_the_cli_json_and_first_text_line(
    proof_workspace, monkeypatch, capsys, meta
):
    flags = ("--prompt", "json", "--max-age-days", "10")
    config = proof_workspace / "benchmark.json"
    records = proof_workspace / "results"
    _, cli_json = _cli(
        monkeypatch,
        capsys,
        "gate",
        config,
        "--repository",
        "acme/app",
        "--records",
        records,
        *flags,
        "--json",
    )
    _, cli_text = _cli(
        monkeypatch,
        capsys,
        "gate",
        config,
        "--repository",
        "acme/app",
        "--records",
        records,
        *flags,
    )

    result = _tool(
        proof_workspace,
        "gate",
        {
            "repository": "acme/app",
            "records": ["results"],
            "prompt": "json",
            "max_age_days": 10,
        },
        meta,
    )["result"]

    content = result["structuredContent"]
    assert result["isError"] is False
    assert content == json.loads(cli_json)
    assert content["decision"] == "blocked"
    assert content["reason_code"] == "inconclusive_record"
    assert content["selection"]["prompt"] == "json"
    assert result["content"][0]["text"] == cli_text.splitlines()[0]
    assert result["content"][0]["text"].startswith("Gate: blocked")
    assert ("resultType" in result) is (meta is not None)


def test_gate_requires_the_selection_the_agent_names(proof_workspace):
    content = _tool(
        proof_workspace, "gate", {"repository": "acme/app", "records": ["results"]}
    )["result"]["structuredContent"]

    assert content["reason_code"] == "selection_changed"
    assert "this gate requires a default run" in content["why"]


def test_gate_defaults_to_the_workspace_benchmark_json(proof_workspace):
    content = _tool(
        proof_workspace, "gate", {"repository": "acme/app", "records": ["results"]}
    )["result"]["structuredContent"]

    assert content["config"] == str(proof_workspace / "benchmark.json")


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("verify", {"record": "../outside.preflight.json"}),
        ("verify", {"record": "/etc/hostname"}),
        ("verify", {"record": "linked/outside.preflight.json"}),
        ("gate", {"records": ["../outside"]}),
        ("gate", {"records": ["results", "/tmp"]}),
        ("gate", {"records": ["linked"]}),
        ("gate", {"config": "../benchmark.json", "records": ["results"]}),
    ],
)
def test_proof_tools_never_read_paths_outside_the_workspace(
    tmp_path, monkeypatch, name, arguments
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "outside.preflight.json").write_text('{"secret": "gpt-gone"}')
    (workspace / "linked").symlink_to(outside, target_is_directory=True)
    (workspace / "results").mkdir()

    response = _tool(workspace, name, arguments)

    result = response["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["error"] in {
        "path must stay within the MCP workspace",
        "paths must be relative to the MCP workspace",
    }
    assert "gpt-gone" not in json.dumps(response)


def test_gate_refuses_a_record_file_linked_from_outside_the_workspace(
    proof_workspace, tmp_path_factory
):
    outside = tmp_path_factory.mktemp("outside") / "stolen.preflight.json"
    outside.write_text('{"secret": "gpt-gone"}')
    (proof_workspace / "results" / "linked.preflight.json").symlink_to(outside)

    response = _tool(
        proof_workspace, "gate", {"repository": "acme/app", "records": ["results"]}
    )

    content = response["result"]["structuredContent"]
    assert content["decision"] == "undecided"
    assert content["reason_code"] == "record_error"
    assert "resolves outside the MCP workspace" in content["why"]
    assert "gpt-gone" not in json.dumps(response)


def test_verify_never_hashes_a_subject_linked_from_outside_the_workspace(
    proof_workspace, tmp_path_factory
):
    record = _record_name(proof_workspace)
    subject = json.loads((proof_workspace / record).read_text())["subject"][0]["name"]
    outside = tmp_path_factory.mktemp("outside") / "benchmark.json"
    outside.write_text(json.dumps(PROOF_CONFIG))
    (proof_workspace / subject).unlink()
    (proof_workspace / subject).symlink_to(outside)

    content = _tool(proof_workspace, "verify", {"record": record})["result"][
        "structuredContent"
    ]

    assert content["integrity"]["subjects"][0]["state"] == "absent"


def test_proof_tools_open_no_network_connection(proof_workspace, monkeypatch):
    import socket

    def refuse(*args, **kwargs):
        raise AssertionError("a proof tool opened a network connection")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)

    verify = _tool(proof_workspace, "verify", {"record": _record_name(proof_workspace)})
    gate = _tool(
        proof_workspace,
        "gate",
        {"repository": "acme/app", "records": ["results"], "prompt": "json"},
    )

    assert verify["result"]["isError"] is False
    assert gate["result"]["structuredContent"]["network_accessed"] is False


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("verify", {}),
        ("verify", {"record": ""}),
        ("verify", {"record": "a", "max_age_days": 0}),
        ("verify", {"record": "a", "max_age_days": 3651}),
        ("verify", {"record": "a", "max_age_days": True}),
        ("verify", {"record": "a", "max_age_days": "30"}),
        ("verify", {"record": "a", "json": True}),
        ("gate", {}),
        ("gate", {"records": []}),
        ("gate", {"records": "results"}),
        ("gate", {"records": [""]}),
        ("gate", {"records": [7]}),
        (
            "gate",
            {
                "repository": "acme/app",
                "records": ["results"],
                "migration_check": "yes",
            },
        ),
        ("gate", {"repository": "acme/app", "records": ["results"], "prompt": ""}),
        (
            "gate",
            {"repository": "acme/app", "records": ["results"], "profiles": "json"},
        ),
    ],
)
def test_proof_tools_reject_arguments_outside_their_schema(tmp_path, name, arguments):
    assert _tool(tmp_path, name, arguments)["error"]["code"] == -32602


@pytest.mark.parametrize(
    "arguments",
    [
        {
            "repository": "acme/app",
            "records": ["results"],
            "prompt": "json",
            "tests": "json",
        },
        {
            "repository": "acme/app",
            "records": ["results"],
            "migration_check": True,
            "tests": "json",
        },
        {
            "repository": "acme/app",
            "records": ["results"],
            "migration_check": True,
            "prompt": "json",
        },
    ],
)
def test_gate_refuses_the_selections_a_run_refuses(proof_workspace, arguments):
    result = _tool(proof_workspace, "gate", arguments)["result"]

    assert result["isError"] is True
    assert "cannot be combined" in result["structuredContent"]["error"]


def test_proof_tools_are_read_only_idempotent_and_closed_world(tmp_path):
    listed = mcp._response(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}, tmp_path
    )
    by_name = {tool["name"]: tool for tool in listed["result"]["tools"]}

    for name in ("verify", "gate"):
        assert by_name[name]["annotations"] == by_name["audit_source"]["annotations"]
        assert "not approval" in by_name[name]["description"]
    assert by_name["verify"]["inputSchema"]["required"] == ["record"]
    assert by_name["gate"]["inputSchema"]["required"] == ["records"]


def test_agent_guidance_never_presents_a_gate_pass_as_approval(tmp_path):
    root = Path(__file__).parent.parent
    skill = (root / "plugins/llm-preflight/skills/llm-preflight/SKILL.md").read_text()
    guide = (root / "docs/automation/mcp.md").read_text()
    readme = (root / "README.md").read_text()
    instructions = mcp._response(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, tmp_path
    )["result"]["instructions"]

    for text in (mcp.SAFE_WORKFLOW, skill, guide, instructions):
        flat = " ".join(text.split()).casefold()
        assert "a gate `pass` is not approval" in flat
    assert "| `verify` |" in guide
    assert "| `gate` |" in guide
    assert "seven tools" in " ".join(guide.split())
    assert "seven tools" in " ".join(readme.split())


def test_gate_without_a_repository_cannot_decide(proof_workspace):
    result = _tool(proof_workspace, "gate", {"records": ["results"]})["result"]

    assert result["isError"] is False
    assert result["structuredContent"]["reason_code"] == "repository_unknown"
    assert result["content"][0]["text"].startswith("Gate: cannot decide")


@pytest.mark.parametrize("repository", ["", "acme", "acme/app/x", "acme/app\n"])
def test_gate_rejects_a_malformed_repository(proof_workspace, repository):
    response = _tool(
        proof_workspace, "gate", {"repository": repository, "records": ["results"]}
    )

    if "error" in response:
        assert response["error"]["code"] == -32602
    else:
        assert response["result"]["isError"] is True
        assert "OWNER/NAME" in response["result"]["structuredContent"]["error"]
