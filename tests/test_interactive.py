"""Interactive choices must describe the workload that is actually executed."""

import json
import sys
from datetime import date

import pytest

from llm_preflight import cli, mcp


def mock_config(**overrides):
    return {
        "prompt": "Reply with ok.",
        "models": [{"provider": "mock", "model": "local", "response": "ok"}],
        "repetitions": 1,
        "warmups": 0,
        "request": {"retry": {"max_attempts": 1}},
        **overrides,
    }


def select(config, answers, **kwargs):
    responses = iter(answers)
    output = []
    result = cli.interactive_selection(
        config,
        input_fn=lambda prompt: next(responses),
        output_fn=output.append,
        **kwargs,
    )
    return result, output


def test_never_stop_removes_the_saved_stop_rule():
    original = mock_config(stop_on="any-fail")
    result, output = select(original, ["all", "", "1", "4", "y"])
    config, _profiles = result

    assert "Stop on: never" in "\n".join(output)
    assert "stop_on" not in config
    assert original["stop_on"] == "any-fail"


def test_never_stop_also_clears_the_legacy_fail_fast_alias():
    original = mock_config(
        fail_fast=True,
        validation={"exact": "ok"},
        models=[
            {"provider": "mock", "model": "bad", "response": "wrong"},
            {"provider": "mock", "model": "good", "response": "ok"},
        ],
    )
    selected, _output = select(original, ["all", "", "1", "4", "y"])
    config, profiles = selected
    result = cli.run_benchmark(config, profile_selector=profiles)
    assert [model["model"] for model in result["models"]] == ["bad", "good"]
    assert original["fail_fast"] is True


def test_config_prompt_selection_removes_saved_profiles():
    original = mock_config(profiles="quick-migration-check")
    result, _output = select(original, ["all", "", "1", "1", "y"])
    config, profiles = result

    assert profiles is None
    assert cli.dry_run_plan(config, profiles)["tests"] == ["config prompt"]
    assert "profiles" not in config
    assert original["profiles"] == "quick-migration-check"


def test_preview_uses_the_shared_plan_and_shows_retirement_evidence(monkeypatch):
    plans = []
    original_plan = cli.dry_run_plan

    def plan(config, profiles):
        result = original_plan(config, profiles, today=date(2026, 10, 12))
        plans.append(result)
        return result

    monkeypatch.setattr(cli, "dry_run_plan", plan)
    result, output = select(
        mock_config(
            models=[{"provider": "anthropic", "model": "claude-3-haiku-20240307"}]
        ),
        ["all", "", "1", "1", "n"],
    )

    assert result is None
    assert len(plans) == 1
    assert plans[0]["retirements"]["decision"] == "fail"
    text = "\n".join(output)
    for line in cli._format_dry_run_plan(plans[0]).splitlines()[1:]:
        assert line in text
    assert "retired" in text
    assert "Smoke eligibility:" in text
    assert "Pricing coverage:" in text


def test_failed_fixtures_stop_before_execution_confirmation():
    prompts = []
    answers = iter(["all", "", "1", "1"])
    output = []

    def answer(prompt):
        prompts.append(prompt)
        return next(answers)

    config = mock_config(
        validation={"contains": "ing"},
        validation_fixtures=[
            {"name": "right", "response": "billing", "expect": "pass"},
            {"name": "wrong", "response": "shipping", "expect": "fail"},
        ],
    )
    with pytest.raises(ValueError, match="validation fixtures failed"):
        cli.interactive_selection(config, input_fn=answer, output_fn=output.append)
    assert any("wrong" in line and "FAIL" in line for line in output)
    assert not any("Run " in prompt for prompt in prompts)


def test_mock_confirmation_describes_a_local_run():
    prompts = []
    answers = iter(["all", "", "1", "1", "n"])

    def answer(prompt):
        prompts.append(prompt)
        return next(answers)

    assert (
        cli.interactive_selection(
            mock_config(), input_fn=answer, output_fn=lambda _: None
        )
        is None
    )
    assert prompts[-1] == "Run local mock benchmark? [y/N]: "


def test_shared_plan_formats_disabled_stop_as_never():
    plan = cli.dry_run_plan(mock_config())
    assert "Stop on: never" in cli._format_dry_run_plan(plan)


def test_prepare_only_never_asks_for_retry_acceptance_or_execution():
    result, _output = select(
        mock_config(max_requests=1, request={"retry": {"max_attempts": 3}}),
        ["all", "", "1", "4"],
        prepare_only=True,
    )
    config, profiles = result
    assert config["_interactive_action"] == "preview"
    assert config["max_requests"] == 1
    assert cli.dry_run_plan(config, profiles)["possible_requests"] == 3


def test_workflow_defaults_to_preview():
    result, output = select(mock_config(), ["all", "", "1", "4", ""], workflow=True)
    assert result[0]["_interactive_action"] == "preview"
    assert "preview" in "\n".join(output).lower()


def test_paid_work_requires_action_and_separate_confirmation():
    prompts = []
    answers = iter(["all", "", "1", "1", "r", "n"])
    result = cli.interactive_selection(
        mock_config(models=[{"provider": "openai", "model": "gpt-5.5"}]),
        input_fn=lambda prompt: (prompts.append(prompt), next(answers))[1],
        output_fn=lambda _: None,
        workflow=True,
    )
    assert result is None
    assert prompts[-1] == "Run paid benchmark? [y/N]: "
    assert "Next action" in prompts[-2]


def test_export_plan_preserves_retry_bounds_without_authorizing_a_run(tmp_path):
    target = tmp_path / "plan.json"
    result, _output = select(
        mock_config(max_requests=1, request={"retry": {"max_attempts": 3}}),
        ["all", "", "1", "4", "x", str(target), "p"],
        workflow=True,
    )
    plan = json.loads(target.read_text())
    assert plan["requests"] == 1
    assert plan["possible_requests"] == 3
    assert plan["retry_max_attempts"] == 3
    assert result[0]["max_requests"] == 1
    assert result[0]["_interactive_action"] == "preview"


def test_save_config_redacts_secrets_preserves_references_and_prints_command(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(cli, "_display_command", lambda: "llm-preflight")
    target = tmp_path / "selected config.json"
    config = mock_config(
        env_file=".env.private", _source_config_path=str(tmp_path / "source.json")
    )
    config["models"][0].update(
        api_key="private-credential",
        api_key_env="MY_KEY",
        headers={"X-Trace": "private-header"},
    )
    result, output = select(
        config, ["all", "", "1", "4", "s", str(target), "p"], workflow=True
    )
    saved = json.loads(target.read_text())
    assert "private-credential" not in target.read_text()
    assert "private-header" not in target.read_text()
    assert saved["models"][0]["api_key_env"] == "MY_KEY"
    assert saved["env_file"] == ".env.private"
    assert not any(key.startswith("_") for key in saved)
    assert cli.dry_run_plan(saved)["tests"] == ["config prompt"]
    assert f"llm-preflight '{target}' --dry-run --no-env-file" in "\n".join(output)
    assert result[0]["models"][0]["api_key"] == "private-credential"


def test_export_refuses_overwrite_and_recovers_at_the_action_menu(tmp_path):
    target = tmp_path / "keep.json"
    target.write_text("keep")
    result, output = select(
        mock_config(), ["all", "", "1", "4", "x", str(target), "q"], workflow=True
    )
    assert result is None
    assert target.read_text() == "keep"
    assert "refusing to overwrite" in "\n".join(output)


@pytest.mark.parametrize("scope", ["top", "prompt", "tool"])
def test_saved_config_preserves_schema_property_names_and_constraints(tmp_path, scope):
    schema = {
        "type": "object",
        "properties": {
            "password": {"type": "string"},
            "_private": {"type": "integer", "minimum": 1},
        },
        "required": ["password", "_private"],
        "additionalProperties": False,
    }
    config = mock_config()
    if scope == "tool":
        schema["properties"]["_private"] = {"type": "integer"}
        config["tools"] = [
            {"name": "example", "description": "Synthetic input", "parameters": schema}
        ]
    else:
        contract = {
            "validation": {"json_schema": schema},
            "validation_fixtures": [
                {
                    "name": "positive",
                    "response": '{"password":"synthetic","_private":1}',
                    "expect": "pass",
                },
                {
                    "name": "negative",
                    "response": '{"password":"synthetic","_private":0}',
                    "expect": "fail",
                },
            ],
        }
        if scope == "prompt":
            config["prompts"] = [
                {"name": "custom", "prompt": "Synthetic input", **contract}
            ]
        else:
            config.update(contract)
    target = tmp_path / "saved.json"
    select(
        config,
        ["all", "custom" if scope == "prompt" else "", "1", "4", "s", str(target), "p"],
        workflow=True,
    )
    saved = json.loads(target.read_text())
    cli.validate_config_validations(saved)
    if scope == "tool":
        assert saved["tools"] == config["tools"]
    else:
        original_scope = config["prompts"][0] if scope == "prompt" else config
        saved_scope = saved["prompts"][0] if scope == "prompt" else saved
        assert saved_scope["validation"] == original_scope["validation"]
        assert (
            saved_scope["validation_fixtures"] == original_scope["validation_fixtures"]
        )
        assert cli.check_contract(saved)["ok"] is True


def test_config_export_refuses_to_change_secret_shaped_contract_values(tmp_path):
    target = tmp_path / "saved.json"
    _result, output = select(
        mock_config(validation={"exact": "sk-synthetic-secret"}),
        ["all", "", "1", "4", "s", str(target), "p"],
        workflow=True,
    )
    assert not target.exists()
    assert "redaction would change the contract" in "\n".join(output)
    assert "sk-synthetic-secret" not in "\n".join(output)


def test_failed_fixtures_allow_preview_but_refuse_the_run_action():
    config = mock_config(
        validation={"exact": "ok"},
        validation_fixtures=[
            {"name": "positive", "response": "ok", "expect": "pass"},
            {"name": "negative", "response": "ok", "expect": "fail"},
        ],
    )
    result, output = select(config, ["all", "", "1", "1", "r", "p"], workflow=True)
    assert result[0]["_interactive_action"] == "preview"
    assert "Cannot run: validation fixtures failed" in "\n".join(output)


def test_main_interactive_dry_run_is_plain_and_never_executes(
    monkeypatch, tmp_path, capsys
):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(mock_config()))
    answers = iter(["all", "", "1", "4"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(
        cli, "run_benchmark", lambda *a, **kw: pytest.fail("unexpected benchmark")
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["llm-preflight", str(path), "--interactive", "--dry-run", "--no-env-file"],
    )
    cli.main()
    output = capsys.readouterr().out
    assert "Requests: 1 nominal; up to 1 with 1 attempts" in output
    assert "\x1b[" not in output


@pytest.mark.parametrize(
    "answers, expected",
    [
        (["99", "all", "", "1", "4", "p"], "invalid selection"),
        (["unknown-provider", "all", "", "1", "4", "p"], "matched no models"),
        (["all", "missing-test", "", "1", "4", "p"], "unknown"),
        (["all", "", "bad", "0", "2", "4", "p"], "positive integer"),
        (["all", "", "1", "invalid", "4", "p"], "stop mode"),
    ],
)
def test_invalid_answers_are_corrected_in_place(answers, expected):
    result, output = select(mock_config(), answers, workflow=True)
    assert result[0]["_interactive_action"] == "preview"
    assert expected in "\n".join(output)


@pytest.mark.parametrize(
    "answers",
    [
        ["q"],
        ["all", "q"],
        ["all", "", "q"],
        ["all", "", "1", "q"],
        ["all", "", "1", "4", "q"],
        ["all", "", "1", "4", "r", "q"],
    ],
)
def test_cancel_at_each_stage_returns_without_execution(answers):
    result, output = select(mock_config(), answers, workflow=True)
    assert result is None
    assert "Cancelled." in "\n".join(output)


def test_back_edits_the_previous_choice_and_keeps_models():
    config = mock_config(
        models=[
            {"provider": "mock", "model": "one"},
            {"provider": "mock", "model": "two"},
        ]
    )
    result, _output = select(
        config, ["2", "agent-smoke", "back", "", "2", "4", "p"], workflow=True
    )
    selected, profiles = result
    assert [model["model"] for model in selected["models"]] == ["two"]
    assert profiles is None
    assert selected["repetitions"] == 2


def test_model_search_keeps_original_numbers_and_reports_selected_count():
    config = mock_config(
        models=[
            {"provider": "mock", "model": "one"},
            {"provider": "mock", "model": "two"},
        ]
    )
    result, output = select(
        config, ["search two", "2", "", "1", "4", "p"], workflow=True
    )
    assert [model["model"] for model in result[0]["models"]] == ["two"]
    assert "  2. mock: two" in output
    assert "Selected models: 1 of 2" in output


def test_save_elsewhere_preserves_source_directory_policy(tmp_path):
    target = tmp_path / "elsewhere" / "config.json"
    result, output = select(
        mock_config(
            _source_config_path=str(tmp_path / "source.json"), env_file=".env.private"
        ),
        ["all", "", "1", "4", "s", str(target), "q"],
        workflow=True,
    )
    assert result is None
    assert not target.exists()
    assert "preserve relative file references" in "\n".join(output)


def test_empty_comma_selection_cannot_prepare_an_empty_workload():
    result, output = select(
        mock_config(), [",,", "all", "", "1", "4", "p"], workflow=True
    )
    assert len(result[0]["models"]) == 1
    assert "choose at least one model" in "\n".join(output)


def test_interactive_output_redacts_secret_shaped_model_names():
    result, output = select(
        mock_config(models=[{"provider": "mock", "model": "sk-synthetic-secret"}]),
        ["all", "", "1", "4", "p"],
        workflow=True,
    )
    assert result[0]["models"][0]["model"] == "sk-synthetic-secret"
    assert "sk-synthetic-secret" not in "\n".join(output)
    assert "[REDACTED]" in "\n".join(output)


def test_interactive_json_preview_keeps_stdout_machine_readable(
    monkeypatch, tmp_path, capsys
):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(mock_config()))
    answers = iter(["all", "", "1", "4"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "llm-preflight",
            str(path),
            "--interactive",
            "--dry-run",
            "--json",
            "--no-env-file",
        ],
    )
    cli.main()
    captured = capsys.readouterr()
    plan = json.loads(captured.out)
    assert plan["tests"] == ["config prompt"]
    assert plan["stop_on"] == "none"
    assert "Select models" in captured.err
    assert "\x1b[" not in captured.err


@pytest.mark.parametrize(
    "answers, dry_run",
    [
        (["all", "", "1", "4"], True),
        (["all", "", "1", "4", "p"], False),
        (["q"], False),
        (["all", "", "1", "4", "r", "y"], False),
    ],
)
def test_configured_mock_preview_cancel_and_run_do_not_read_env_files(
    monkeypatch, tmp_path, answers, dry_run
):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(mock_config(env_file=".env.private")))
    responses = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    monkeypatch.setattr(
        cli, "load_env_file", lambda _: pytest.fail("unexpected env file read")
    )
    argv = ["llm-preflight", str(path), "--interactive", "--no-save"]
    if dry_run:
        argv.append("--dry-run")
    monkeypatch.setattr(sys, "argv", argv)
    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 3  # Mock evidence stays inconclusive.


def test_interactive_saved_mock_result_prints_existing_report_paths_and_command(
    monkeypatch, tmp_path, capsys
):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(mock_config()))
    answers = iter(["all", "", "1", "4", "r", "y"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "llm-preflight",
            str(path),
            "--interactive",
            "--output-dir",
            str(tmp_path / "results"),
            "--no-env-file",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 3
    output = capsys.readouterr()
    saved = next((tmp_path / "results").glob("*.json"))
    assert saved.with_suffix(".md").exists()
    assert saved.with_suffix(".summary.md").exists()
    assert f"Saved report to {saved.with_suffix('.md')}" in output.err
    assert f"Saved decision summary to {saved.with_suffix('.summary.md')}" in output.err
    assert f"llm-preflight report {saved}" in output.err
    assert "inconclusive" in output.out.lower()


def test_edit_keeps_valid_choices_when_the_user_accepts_them_again():
    config = mock_config(
        models=[
            {"provider": "mock", "model": "one"},
            {"provider": "mock", "model": "two"},
        ]
    )
    result, _output = select(
        config,
        ["2", "agent-smoke", "2", "4", "e", "", "keep", "", "", "p"],
        workflow=True,
    )
    selected, profiles = result
    assert [model["model"] for model in selected["models"]] == ["two"]
    assert profiles == "agent-smoke"
    assert selected["suite_repetitions"] == 2
    assert "stop_on" not in selected


def test_interrupt_after_export_reports_that_saved_exports_are_kept(
    monkeypatch, tmp_path, capsys
):
    path = tmp_path / "config.json"
    target = tmp_path / "selected.json"
    path.write_text(json.dumps(mock_config()))
    answers = iter(["all", "", "1", "4", "s", str(target)])

    def answer(_prompt):
        try:
            return next(answers)
        except StopIteration:
            raise KeyboardInterrupt from None

    monkeypatch.setattr("builtins.input", answer)
    monkeypatch.setattr(sys, "argv", ["llm-preflight", str(path), "--interactive"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 130
    assert target.exists()
    assert "saved exports were kept" in capsys.readouterr().err


def test_exported_selection_has_identical_cli_and_mcp_plan(tmp_path):
    selected, _output = select(
        mock_config(
            profiles="agent-smoke",
            stop_on="any-fail",
            models=[
                {"provider": "mock", "model": "one", "response": "ok"},
                {"provider": "mock", "model": "two", "response": "ok"},
            ],
            request={"retry": {"max_attempts": 3}},
        ),
        ["2", "", "2", "4"],
        prepare_only=True,
    )
    config, profiles = selected
    target = tmp_path / "selected.json"
    cli._write_starter_config(
        target, {key: value for key, value in config.items() if not key.startswith("_")}
    )
    response = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "dry_run_plan", "arguments": {"config": target.name}},
        },
        tmp_path,
    )
    assert response["result"]["isError"] is False
    remote = response["result"]["structuredContent"]
    local = cli.dry_run_plan(config, profiles)
    for field, value in local.items():
        assert remote[field] == value, field
    assert local["tests"] == ["config prompt"]
    assert local["stop_on"] == "none"
    assert local["requests"] == 2
    assert local["possible_requests"] == 6


def test_strict_stale_pricing_is_visible_and_cannot_run():
    result, output = select(
        mock_config(
            require_current_pricing=True,
            models=[
                {
                    "provider": "openai_compatible",
                    "model": "synthetic-priced",
                    "base_url": "https://api.example.com/v1",
                    "input_cost_per_million": 1,
                    "output_cost_per_million": 2,
                    "pricing_metadata": {"source": "custom", "as_of": "2000-01-01"},
                }
            ],
        ),
        ["all", "", "1", "1", "r"],
        workflow=True,
    )
    assert result is None
    text = "\n".join(output)
    assert "stale" in text
    assert "Cannot run this plan" in text


def test_unknown_price_stays_unavailable_in_the_interactive_preview():
    _result, output = select(
        mock_config(
            models=[
                {
                    "provider": "openai_compatible",
                    "model": "synthetic-unpriced",
                    "base_url": "https://api.example.com/v1",
                }
            ]
        ),
        ["all", "", "1", "4"],
        prepare_only=True,
    )
    assert "Cost: unavailable" in output
    assert "unknown" in "\n".join(output)


def test_live_consent_precedes_environment_read_and_passes_exact_selection(
    monkeypatch, tmp_path
):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            mock_config(
                stop_on="any-fail",
                profiles="agent-smoke",
                models=[{"provider": "anthropic", "model": "claude-sonnet-5-5"}],
            )
        )
    )
    answers = iter(["all", "", "2", "4", "r", "y"])
    events = []

    def answer(prompt):
        value = next(answers)
        if prompt == "Run paid benchmark? [y/N]: ":
            events.append(("confirm", value))
        return value

    def run(config, **kwargs):
        events.append(("run", config, kwargs["profile_selector"]))
        raise ValueError("synthetic execution sentinel")

    monkeypatch.setattr("builtins.input", answer)
    monkeypatch.setattr(cli, "load_env_file", lambda _: events.append(("env",)))
    monkeypatch.setattr(cli, "run_benchmark", run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "llm-preflight",
            str(path),
            "--interactive",
            "--no-save",
            "--output-dir",
            str(tmp_path / "results"),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    assert [event[0] for event in events] == ["confirm", "env", "run"]
    assert events[-1][1]["repetitions"] == 2
    assert "stop_on" not in events[-1][1]
    assert "profiles" not in events[-1][1]
    assert events[-1][2] is None


def test_main_preview_action_cannot_reach_the_benchmark(monkeypatch, tmp_path, capsys):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(mock_config()))
    answers = iter(["all", "", "1", "4", "p"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(
        cli, "run_benchmark", lambda *a, **kw: pytest.fail("preview reached benchmark")
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["llm-preflight", str(path), "--interactive", "--json", "--no-env-file"],
    )
    cli.main()
    assert json.loads(capsys.readouterr().out)["tests"] == ["config prompt"]


def test_main_mock_json_contains_one_result_with_progress_on_stderr(
    monkeypatch, tmp_path, capsys
):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(mock_config()))
    answers = iter(["all", "", "1", "4", "r", "y"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "llm-preflight",
            str(path),
            "--interactive",
            "--json",
            "--no-env-file",
            "--no-save",
            "--output-dir",
            str(tmp_path / "results"),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 3
    output = capsys.readouterr()
    assert json.loads(output.out)["decision"]["state"] == "inconclusive"
    assert "Run local mock benchmark?" in output.err
    assert "API OK" in output.err


@pytest.mark.parametrize("dry_run", [True, False])
def test_watch_interactive_json_preview_is_one_document(
    monkeypatch, tmp_path, capsys, dry_run
):
    watch = tmp_path / "watch.json"
    approved = tmp_path / "approved.json"
    watch.write_text(json.dumps(mock_config()))
    approved.write_text('{"models": []}')
    answers = ["all", "", "", "n", "1", "4"] + ([] if dry_run else ["p"])
    responses = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    monkeypatch.setattr(
        cli, "run_benchmark", lambda *a, **kw: pytest.fail("preview executed")
    )
    argv = [
        str(watch),
        "--against",
        str(approved),
        "--interactive",
        "--json",
        "--no-env-file",
    ]
    if dry_run:
        argv.append("--dry-run")
    cli._watch_new_main(argv)
    captured = capsys.readouterr()
    plan = json.loads(captured.out)
    assert plan["tests"] == ["config prompt"]
    assert plan["possible_requests"] == 1
    assert "Choose models to try" in captured.err
    assert "Run Plan" in captured.err
    assert "\x1b[" not in captured.err


def test_watch_interactive_config_export_keeps_relative_file_directory(
    monkeypatch, tmp_path, capsys
):
    watch = tmp_path / "watch.json"
    approved = tmp_path / "approved.json"
    watch.write_text(json.dumps(mock_config(env_file=".env.private")))
    approved.write_text('{"models": []}')
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    target = elsewhere / "saved.json"
    responses = iter(["all", "", "", "n", "1", "4", "s", str(target), "q"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    cli._watch_new_main(
        [str(watch), "--against", str(approved), "--interactive", "--no-env-file"]
    )
    assert not target.exists()
    assert "preserve relative file references" in capsys.readouterr().out


@pytest.mark.parametrize("approve", [False, True])
def test_watch_interactive_json_keeps_approval_prompts_off_stdout(
    monkeypatch, tmp_path, capsys, approve
):
    watch = tmp_path / "watch.json"
    approved = tmp_path / "approved.json"
    watch.write_text(json.dumps(mock_config()))
    approved.write_text('{"models": []}')
    # Synthetic passing evidence exercises the approval UI without provider work.
    result = {
        "run_id": "synthetic",
        "decision": {"state": "pass"},
        "models": [{"provider": "mock", "model": "local", "summary": {"failed": 0}}],
    }
    monkeypatch.setattr(cli, "run_benchmark", lambda *a, **kw: result)
    saved = tmp_path / "result.json"

    def save(payload, _directory):
        saved.write_text(json.dumps(payload))
        return saved

    monkeypatch.setattr(cli, "save_result", save)
    approved_calls = []

    def approval(argv):
        approved_calls.append(argv)
        print("Synthetic approval completed")

    monkeypatch.setattr(cli, "_approve_model_main", approval)
    answers = ["all", "", "", "n", "1", "4", "r", "y"]
    answers.extend(["1", "y"] if approve else [""])
    responses = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    cli._watch_new_main(
        [
            str(watch),
            "--against",
            str(approved),
            "--interactive",
            "--json",
            "--no-env-file",
            "--output-dir",
            str(tmp_path / "results"),
        ]
    )
    captured = capsys.readouterr()
    assert json.loads(captured.out) == result
    assert "Passing candidates" in captured.err
    assert "Approve a candidate" in captured.err
    assert bool(approved_calls) is approve
    if approve:
        assert "Synthetic approval completed" in captured.err
