"""CLI and MCP share native route, price and limit evidence without provider work."""

import json
import sys
from datetime import date
from pathlib import Path

import pytest

from llm_preflight import cli, mcp

NEW_EXAMPLES = [
    "gpt-6.1-terra",
    "glm-5.3-flash",
    "glm-5.3-flashx",
    "kimi-k3.1-pro",
    "kimi-k3.1-pro-highspeed",
    "minimax-m3.1-flash",
    "minimax-m3",
    "mistral-large-4",
    "cohere-command-a-plus",
    "mythos-5.1-restricted",
]


def rpc_plan(workspace):
    return mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "dry_run_plan",
                "arguments": {"config": "benchmark.json"},
            },
        },
        workspace,
    )


@pytest.mark.parametrize("name", NEW_EXAMPLES)
def test_cli_mcp_native_plan_price_and_retirement_evidence_agree(
    monkeypatch, tmp_path, capsys, snapshot_review_day, name
):
    config = json.loads((Path("examples") / f"{name}.json").read_text())
    path = tmp_path / "benchmark.json"
    path.write_text(json.dumps(config))
    monkeypatch.setattr(cli, "today_utc", lambda: date(2026, 10, 26))
    monkeypatch.setattr(mcp, "today_utc", lambda: date(2026, 10, 26))
    monkeypatch.setattr(
        "llm_preflight.client.open_public_url",
        lambda *args, **kwargs: pytest.fail("no-spend plan contacted a provider"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["llm-preflight", str(path), "--dry-run", "--json", "--no-env-file"],
    )
    cli.main()
    cli_plan = json.loads(capsys.readouterr().out)
    response = rpc_plan(tmp_path)
    assert response is not None
    assert response["result"]["isError"] is False
    mcp_plan = response["result"]["structuredContent"]
    assert mcp_plan["models"] == cli_plan["models"]
    for field in (
        "requests",
        "possible_requests",
        "estimated_cost_usd",
        "maximum_estimated_cost_usd",
        "pricing_coverage",
    ):
        assert mcp_plan[field] == cli_plan[field]
    assert mcp_plan["retirements"] == cli_plan["retirements"]
    assert mcp_plan["possible_requests"] == 1


@pytest.mark.parametrize(
    "provider,model,settings",
    [
        ("moonshot", "kimi-k3.1-pro", {"max_tokens": 100000}),
        ("minimax", "MiniMax-M3.1-Flash", {"thinking": {"type": "disabled"}}),
        ("mistral", "mistral-large-4", {"service_tier": "priority"}),
        ("cohere", "command-a-plus-05-2026", {"max_tokens": 100000}),
        ("zai", "glm-5.3-flash", {"thinking": {"type": "disabled"}}),
    ],
)
def test_mcp_and_cli_refuse_native_request_settings_before_work(
    monkeypatch, tmp_path, capsys, provider, model, settings
):
    config = {
        "prompt": "hi",
        "models": [{"provider": provider, "model": model}],
        "request": {"provider_options": {provider: settings}},
    }
    path = tmp_path / "benchmark.json"
    path.write_text(json.dumps(config))
    monkeypatch.setattr(
        "llm_preflight.client.open_public_url",
        lambda *args, **kwargs: pytest.fail("invalid plan contacted a provider"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["llm-preflight", str(path), "--dry-run", "--json", "--no-env-file"],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    capsys.readouterr()
    response = rpc_plan(tmp_path)
    assert response is not None
    assert "error" in response or response.get("result", {}).get("isError") is True
