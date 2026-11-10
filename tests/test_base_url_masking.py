"""A `base_url` that carries a credential never reaches result output."""

import json
import sys

import pytest

from llm_preflight import cli, client, features, mcp
from llm_preflight.redaction import mask_base_url
from llm_preflight.runner import redact_result

RAW_ROUTES = {
    "userinfo": "https://user:TOK123@mock.local/v1",
    "api_key": "https://mock.local/v1?api_key=TOK123",
    "token": "https://mock.local/v1?token=TOK123",
    "key": "https://mock.local/v1?key=TOK123",
    "path": "https://mock.local/TOK123/v1",
    "parameter": "https://mock.local/v1;tok=TOK123",
}


def mock_config():
    return {
        "prompt": "Reply with ok.",
        "models": [{"provider": "mock", "model": "local", "response": "ok"}],
        "repetitions": 1,
        "warmups": 0,
        "request": {"retry": {"max_attempts": 1}},
    }


def select(config, answers, **kwargs):
    responses = iter(answers)
    return cli.interactive_selection(
        config,
        input_fn=lambda prompt: next(responses),
        output_fn=lambda line: None,
        **kwargs,
    )


ROUTES = pytest.mark.parametrize("raw", RAW_ROUTES.values(), ids=RAW_ROUTES.keys())


def write_config(tmp_path, raw):
    config = tmp_path / "benchmark.json"
    config.write_text(
        json.dumps(
            {
                "prompt": "hi",
                "models": [
                    {
                        "provider": "mock",
                        "model": "local",
                        "response": "ok",
                        "base_url": raw,
                    }
                ],
                "repetitions": 1,
                "warmups": 0,
            }
        )
    )
    return config


def run_cli(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["llm-preflight", *argv])
    try:
        cli.main()
    except SystemExit:
        pass


def tree_text(path):
    return "".join(
        item.read_text() for item in sorted(path.rglob("*")) if item.is_file()
    )


@ROUTES
def test_run_json_masks_credential_base_url(monkeypatch, tmp_path, capsys, raw):
    config = write_config(tmp_path, raw)
    run_cli(
        monkeypatch,
        str(config),
        "--json",
        "--no-env-file",
        "--output-dir",
        str(tmp_path / "out"),
    )
    out = capsys.readouterr().out

    assert "TOK123" not in out
    result = json.loads(out)
    assert result["models"][0]["base_url"] == mask_base_url(raw)
    assert result["source_config"]["models"][0]["base_url"] == mask_base_url(raw)


@ROUTES
def test_saved_result_masks_credential_base_url(monkeypatch, tmp_path, raw):
    config = write_config(tmp_path, raw)
    run_cli(
        monkeypatch,
        str(config),
        "--no-env-file",
        "--output-dir",
        str(tmp_path / "out"),
    )

    assert sorted(path.suffix for path in (tmp_path / "out").iterdir())
    assert "TOK123" not in tree_text(tmp_path / "out")


@ROUTES
def test_mcp_run_preflight_masks_credential_base_url(tmp_path, raw):
    write_config(tmp_path, raw)
    response = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"},
                "name": "run_preflight",
                "arguments": {"config": "benchmark.json"},
            },
        },
        tmp_path,
    )
    text = json.dumps(response)

    assert "TOK123" not in text
    assert mask_base_url(raw).replace('"', '\\"') in text or "[REDACTED]" in text


def test_catalog_stdout_masks_base_url_and_written_config_keeps_it(
    monkeypatch, tmp_path, capsys
):
    config = tmp_path / "benchmark.json"
    config.write_text('{"prompt":"hello","models":[{"model":"fake"}]}')
    row = {"model": "fake", "base_url": RAW_ROUTES["userinfo"]}
    monkeypatch.setattr(cli, "resolve_models", lambda value: [row])
    run_cli(monkeypatch, str(config), "--catalog")

    out = capsys.readouterr().out
    assert "TOK123" not in out
    assert json.loads(out)[0]["base_url"] == mask_base_url(RAW_ROUTES["userinfo"])
    assert cli.catalog_output([row])[0]["base_url"] == RAW_ROUTES["userinfo"]


def test_interactive_plan_export_masks_base_url_and_config_save_keeps_it(tmp_path):
    raw = RAW_ROUTES["userinfo"]
    config = mock_config()
    config["models"][0]["base_url"] = raw
    plan_target = tmp_path / "plan.json"
    select(config, ["all", "", "1", "4", "x", str(plan_target), "p"], workflow=True)
    config_target = tmp_path / "config.json"
    select(config, ["all", "", "1", "4", "s", str(config_target), "p"], workflow=True)

    assert "TOK123" not in plan_target.read_text()
    assert json.loads(config_target.read_text())["models"][0]["base_url"] == raw


def masked_result(raw, **extra):
    config = {"prompt": "hi", "models": [{"provider": "mock", "model": "local"}]}
    config["models"][0]["base_url"] = raw
    return redact_result(
        {
            "source_config": config,
            "models": [
                {"provider": "mock", "model": "local", "name": "local", "base_url": raw}
            ],
            "settings": {},
            **extra,
        }
    )


def test_redact_result_masking_is_idempotent_and_keeps_public_routes():
    once = masked_result(RAW_ROUTES["userinfo"])
    assert redact_result(once) == once
    public = masked_result("https://api.openai.com/v1")
    assert public["models"][0]["base_url"] == "https://api.openai.com/v1"


@pytest.mark.parametrize("value", [None, 5, "", "ftp://host/x", "https://[::1]:8080/a"])
def test_redact_result_masks_odd_base_urls_like_dry_run(value):
    result = masked_result(value)
    assert result["models"][0]["base_url"] == mask_base_url(value)
    assert "TOK" not in json.dumps(result)


def test_replay_restores_masked_base_url_from_source_config():
    raw = RAW_ROUTES["userinfo"]
    result = masked_result(raw)
    source = {"models": [{"model": "local", "base_url": raw}]}

    config = features.replay_config(result, source)

    assert config["models"][0]["base_url"] == raw


def test_replay_refuses_masked_base_url_without_source_config():
    result = masked_result(RAW_ROUTES["userinfo"])
    for source in (None, {"models": []}):
        with pytest.raises(ValueError, match="needs the source config"):
            features.replay_config(result, source)


def test_replay_refuses_ambiguous_masked_base_url():
    result = masked_result(RAW_ROUTES["userinfo"])
    source = {
        "models": [
            {"base_url": "https://user:A@mock.local/v1"},
            {"base_url": "https://user:B@mock.local/v1"},
        ]
    }
    with pytest.raises(ValueError, match="several routes in the source config"):
        features.replay_config(result, source)


def test_replay_legacy_unmasked_result_is_unchanged():
    raw = RAW_ROUTES["userinfo"]
    legacy = {
        "source_config": {"prompt": "hi", "models": []},
        "models": [{"provider": "mock", "model": "local", "base_url": raw}],
    }
    assert features.replay_config(legacy)["models"][0]["base_url"] == raw


def test_cli_replay_sends_the_raw_route_from_the_recorded_source_config(
    monkeypatch, tmp_path
):
    raw = RAW_ROUTES["userinfo"]
    source = write_config(tmp_path, raw)
    result_path = tmp_path / "run.json"
    result = masked_result(raw, source_config_path=str(source))
    result["source_config"] = json.loads(source.read_text())
    result["source_config"]["models"][0]["base_url"] = mask_base_url(raw)
    result_path.write_text(json.dumps(result))
    seen = []

    def stop(config, **kwargs):
        seen.append(config)
        raise SystemExit(0)

    monkeypatch.setattr(cli, "run_benchmark", stop)
    run_cli(monkeypatch, "--replay", str(result_path), "--no-env-file")

    assert seen[0]["models"][0]["base_url"] == raw


def test_cli_replay_refuses_a_masked_route_it_cannot_restore(
    monkeypatch, tmp_path, capsys
):
    result_path = tmp_path / "run.json"
    result_path.write_text(json.dumps(masked_result(RAW_ROUTES["userinfo"])))
    monkeypatch.setattr(
        cli,
        "run_benchmark",
        lambda *args, **kwargs: pytest.fail("no run after a refused replay"),
    )
    monkeypatch.setattr(
        sys, "argv", ["llm-preflight", "--replay", str(result_path), "--no-env-file"]
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
    assert "needs the source config" in capsys.readouterr().err


def approve(monkeypatch, tmp_path, result):
    result_path = tmp_path / "candidate.json"
    result_path.write_text(json.dumps(result))
    approved = tmp_path / "approved.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "llm-preflight",
            "approve-model",
            "mock:local",
            "--from",
            str(result_path),
            "--approved",
            str(approved),
        ],
    )
    return approved


def passing(raw, **extra):
    result = masked_result(raw, **extra)
    result["models"][0]["summary"] = {"failed": 0}
    return result


def test_approve_restores_masked_base_url_from_source_config(monkeypatch, tmp_path):
    raw = RAW_ROUTES["userinfo"]
    source = write_config(tmp_path, raw)
    approved = approve(
        monkeypatch, tmp_path, passing(raw, source_config_path=str(source))
    )
    cli.main()

    assert json.loads(approved.read_text())["models"][0]["base_url"] == raw


def test_approve_refuses_unrestorable_masked_base_url(monkeypatch, tmp_path, capsys):
    approved = approve(monkeypatch, tmp_path, passing(RAW_ROUTES["userinfo"]))
    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
    assert "source config" in capsys.readouterr().err
    assert not approved.exists()


@pytest.mark.parametrize("raw", ["https://mock.local/[REDACTED]", "[REDACTED]"])
def test_client_refuses_masked_base_url_before_request(raw):
    with pytest.raises(ValueError, match="base_url is masked"):
        client.create_client(
            {"provider": "openai_compatible", "model": "m", "base_url": raw}, 5
        )


def test_routes_fingerprint_distinguishes_routes_that_mask_alike():
    from llm_preflight.runner import run_benchmark

    def run(path):
        config = {
            "prompt": "hi",
            "models": [
                {
                    "provider": "mock",
                    "model": "local",
                    "response": "ok",
                    "base_url": f"https://mock.local/{path}",
                }
            ],
            "repetitions": 1,
            "warmups": 0,
        }
        return run_benchmark(config)

    first, second = run("a"), run("b")

    assert first["models"][0]["base_url"] == second["models"][0]["base_url"]
    assert first["provenance"]["routes_sha256"] != second["provenance"]["routes_sha256"]
