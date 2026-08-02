import json
import subprocess
import sys

from llm_preflight import mcp

META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}


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


def test_stdio_server_survives_an_invalid_request_then_handles_discovery(tmp_path):
    process = subprocess.Popen(
        [sys.executable, "-m", "llm_preflight.mcp", "--workspace", str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write('{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}\n')
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
    assert first["error"]["code"] == -32022
    assert first["error"]["data"]["supported"] == ["2026-07-28"]
    assert second["result"]["supportedVersions"] == ["2026-07-28"]
