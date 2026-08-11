import json
import subprocess
import sys

from llm_preflight import mcp

META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}


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
    assert "TEST_MCP_SECRET" not in __import__("os").environ


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
    assert "TEST_MCP_SECRET" not in __import__("os").environ


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
