import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from llm_preflight import mcp, retirements
from llm_preflight.retirements import retirement_report

META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}


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
    assert [tool["name"] for tool in listed["result"]["tools"]] == [
        "validate_config",
        "dry_run_plan",
        "run_preflight",
        "diff_baseline",
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
        "validate_config",
        "dry_run_plan",
        "run_preflight",
        "diff_baseline",
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
