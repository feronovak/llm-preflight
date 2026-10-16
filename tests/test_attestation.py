import copy
import hashlib
import json
import shutil
import socket
import subprocess
import sys
from datetime import date

import pytest

from llm_preflight import cli
from llm_preflight.catalog import resolve_models
from llm_preflight.contracts import provenance
from llm_preflight.decision import build_decision
from llm_preflight.pricing import resolve_pricing
from llm_preflight.runner import load_config

STATEMENT = "https://in-toto.io/Statement/v1"
TEST_RESULT = "https://in-toto.io/attestation/test-result/v0.1"
CHECKED = "2026-10-10T08:00:00+00:00"
OBSERVED = "gpt-4.1-mini-2025-04-14"
UNRECORDED = object()
TODAY = date(2026, 10, 17)
CONFIG = {
    "name": "demo",
    "prompt": "Return a JSON object.",
    "validation": {"json_object": True},
    "models": [{"provider": "openai", "model": "gpt-4.1-mini"}],
}
GITHUB = {
    "GITHUB_REPOSITORY": "acme/app",
    "GITHUB_WORKFLOW": "preflight",
    "GITHUB_RUN_ID": "4425592351",
    "GITHUB_RUN_ATTEMPT": "1",
    "GITHUB_SHA": "d20ace7968ba43c0219f62d71334c1095bab1602",
    "GITHUB_SERVER_URL": "https://github.com",
}


@pytest.fixture(autouse=True)
def local_clock_and_environment(monkeypatch):
    """No GitHub identity unless a test sets one, and a pinned verifier clock."""
    for name in GITHUB:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cli, "today_utc", lambda: TODAY)


def _run(monkeypatch, capsys, *arguments):
    monkeypatch.setattr(sys, "argv", ["llm-preflight", *map(str, arguments)])
    try:
        cli.main()
    except SystemExit as exc:
        code = exc.code
    else:
        code = 0
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _config(tmp_path, config=CONFIG):
    path = tmp_path / "benchmark.json"
    path.write_text(json.dumps(config))
    return path


def _result(
    tmp_path,
    config_path,
    *,
    state="pass",
    timestamp=CHECKED,
    name="run.json",
    observed=OBSERVED,
    selection=None,
):
    """A billable single-model result whose decision comes from decision.py.

    `observed=UNRECORDED` or `selection=UNRECORDED` writes a result from before
    that field existed; a default run's selection is the default.
    """
    config = load_config(config_path)
    routes = resolve_pricing(resolve_models(config))["models"]
    model = {
        "name": "gpt-4.1-mini",
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "samples": [{"valid_output": True}, {"valid_output": True}],
        "summary": {
            "requests": 2,
            "successful": 2,
            "failed": 0,
            "valid_output_rate": 1.0,
        },
        "warmup_summary": {"requests": 1, "successful": 1, "failed": 0},
    }
    if observed is not UNRECORDED:
        model["observed_model"] = observed
    result = {
        "schema_version": 1,
        "run_id": "6f1c2d4e-0000-4000-8000-000000000001",
        "timestamp": timestamp,
        "benchmark": "demo",
        "models": [model],
        "pricing_ledger": [
            {"provider": "openai", "model": "gpt-4.1-mini", "as_of": "2026-10-16"}
        ],
        "pricing_coverage": {"summary": {"billable": 1}, "models": []},
        "cost_confidence": "complete",
        "total_estimated_cost_usd": 0.0012,
        "cost_coverage": {
            "known_requests": 3,
            "missing_usage_requests": 0,
            "missing_price_requests": 0,
            "unobserved_retry_requests": 0,
        },
        "provenance": provenance(config, routes, "f" * 64),
        "source_config_path": str(config_path.resolve()),
    }
    if selection is not UNRECORDED:
        result["selection"] = selection or {
            "prompt": None,
            "tests": None,
            "environment": None,
            "migration_check": False,
        }
    if state == "fail":
        model["summary"]["valid_output_rate"] = 0.5
        model["samples"][1]["valid_output"] = False
    if state == "inconclusive":
        result["cost_confidence"] = "partial"
        result["total_estimated_cost_usd"] = None
    result["decision"] = build_decision(result)
    assert result["decision"]["state"] == state
    directory = tmp_path / "results"
    directory.mkdir(exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(result, indent=2))
    return path


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _descriptor(record, name):
    return next(
        item
        for item in record["predicate"]["configuration"]
        if item["name"] == f"llm-preflight/{name}"
    )


# attest


@pytest.mark.parametrize(
    ("state", "verdict", "tests"),
    [
        ("pass", "PASSED", "passedTests"),
        ("inconclusive", "WARNED", "warnedTests"),
        ("fail", "FAILED", "failedTests"),
    ],
)
def test_attest_maps_the_saved_decision_onto_the_test_result_predicate(
    monkeypatch, capsys, tmp_path, state, verdict, tests
):
    monkeypatch.chdir(tmp_path)
    config = _config(tmp_path)
    result = _result(tmp_path, config, state=state)
    saved = json.loads(result.read_text())

    code, out, _ = _run(monkeypatch, capsys, "attest", "results/run.json")

    assert code == 0
    output = tmp_path / "results/run.preflight.json"
    assert "Saved preflight record to results/run.preflight.json" in out
    record = json.loads(output.read_text())
    assert record["_type"] == STATEMENT
    assert record["predicateType"] == TEST_RESULT
    assert record["subject"] == [
        {
            "name": "benchmark.json",
            "digest": {"sha256": _sha256(config)},
            "annotations": {"role": "config"},
        },
        {
            "name": "results/run.json",
            "digest": {"sha256": _sha256(result)},
            "annotations": {"role": "result"},
        },
    ]
    predicate = record["predicate"]
    assert predicate["result"] == verdict
    case = "openai:gpt-4.1-mini/config-prompt"
    for field in ("passedTests", "warnedTests", "failedTests"):
        assert predicate[field] == ([case] if field == tests else [])
    assert [item["name"] for item in predicate["configuration"]] == [
        "llm-preflight/contract",
        "llm-preflight/routes",
        "llm-preflight/pricing",
        "llm-preflight/evidence",
    ]
    for name in ("contract", "routes", "pricing", "evidence"):
        assert _descriptor(record, name)["digest"] == {
            "sha256": saved["provenance"][f"{name}_sha256"]
        }
    assert _descriptor(record, "routes")["annotations"]["routes"] == [
        {
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "pricingAsOf": "2026-10-16",
            "observedModel": OBSERVED,
        }
    ]
    evidence = _descriptor(record, "evidence")["annotations"]
    # Verbatim, except the safe next command that names a local path.
    assert "safe_next_command" in saved["decision"]
    assert evidence["decision"] == {
        key: value
        for key, value in saved["decision"].items()
        if key != "safe_next_command"
    }
    assert evidence["provenance"] == saved["provenance"]
    assert evidence["checkedAt"] == CHECKED
    assert evidence["runId"] == saved["run_id"]
    assert evidence["requests"] == 3
    assert evidence["costConfidence"] == saved["cost_confidence"]
    assert evidence["costUsd"] == saved["total_estimated_cost_usd"]
    assert evidence["retirementSnapshot"] == "2026-10-16"
    assert evidence["claimsNotMade"] == [
        "production behaviour",
        "accuracy beyond the declared validators",
        "safety",
        "other accounts or regions",
    ]
    assert evidence["origin"] == "local"
    assert evidence["ci"] is None
    assert "url" not in predicate


@pytest.mark.parametrize(
    ("observed", "recorded", "shown"),
    [
        (UNRECORDED, None, "did not report the model that answered"),
        (None, None, "did not report the model that answered"),
        (
            ["gpt-4.1-mini-a", "gpt-4.1-mini-b"],
            ["gpt-4.1-mini-a", "gpt-4.1-mini-b"],
            "answered as gpt-4.1-mini-a, gpt-4.1-mini-b (responses disagreed)",
        ),
    ],
    ids=["result-before-the-field", "not-reported", "disagreeing"],
)
def test_attest_and_verify_carry_the_observed_model_and_never_guess_one(
    monkeypatch, capsys, tmp_path, observed, recorded, shown
):
    monkeypatch.chdir(tmp_path)
    _result(tmp_path, _config(tmp_path), observed=observed)

    assert _run(monkeypatch, capsys, "attest", "results/run.json")[0] == 0
    record = tmp_path / "results/run.preflight.json"
    routes = _descriptor(json.loads(record.read_text()), "routes")["annotations"]
    _, out, _ = _run(monkeypatch, capsys, "verify", record)
    _, report, _ = _run(monkeypatch, capsys, "verify", record, "--json")

    assert routes["routes"][0]["observedModel"] == recorded
    assert f"Route:     openai:gpt-4.1-mini {shown}\n" in out
    assert json.loads(report)["routes"] == [
        {"provider": "openai", "model": "gpt-4.1-mini", "observed_model": recorded}
    ]


def test_attest_refuses_a_result_without_schema_version_1_provenance(
    monkeypatch, capsys, tmp_path
):
    monkeypatch.chdir(tmp_path)
    result = _result(tmp_path, _config(tmp_path))
    payload = json.loads(result.read_text())
    del payload["provenance"]
    result.write_text(json.dumps(payload))

    code, _, err = _run(monkeypatch, capsys, "attest", result)

    assert code == 2
    assert "schema-version-1 provenance" in err
    assert not (tmp_path / "results/run.preflight.json").exists()


def test_attest_refuses_provenance_that_does_not_match_its_evidence_hash(
    monkeypatch, capsys, tmp_path
):
    monkeypatch.chdir(tmp_path)
    result = _result(tmp_path, _config(tmp_path))
    payload = json.loads(result.read_text())
    payload["provenance"]["contract_sha256"] = "0" * 64
    result.write_text(json.dumps(payload))

    code, _, err = _run(monkeypatch, capsys, "attest", result)

    assert code == 2
    assert "evidence_sha256" in err
    assert not (tmp_path / "results/run.preflight.json").exists()


def test_attest_never_upgrades_an_edited_pass_with_incomplete_cost_evidence(
    monkeypatch, capsys, tmp_path
):
    monkeypatch.chdir(tmp_path)
    result = _result(tmp_path, _config(tmp_path), state="inconclusive")
    payload = json.loads(result.read_text())
    payload["decision"] = {**payload["decision"], "state": "pass"}
    payload["decision"]["blocking_warnings"] = []
    result.write_text(json.dumps(payload))

    code, _, err = _run(monkeypatch, capsys, "attest", result)

    assert code == 2
    assert "cost confidence" in err
    assert not (tmp_path / "results/run.preflight.json").exists()


def test_attest_records_github_actions_identity_and_run_url(
    monkeypatch, capsys, tmp_path
):
    monkeypatch.chdir(tmp_path)
    _result(tmp_path, _config(tmp_path))
    for name, value in GITHUB.items():
        monkeypatch.setenv(name, value)

    code, _, _ = _run(monkeypatch, capsys, "attest", "results/run.json")

    assert code == 0
    record = json.loads((tmp_path / "results/run.preflight.json").read_text())
    assert record["predicate"]["url"] == (
        "https://github.com/acme/app/actions/runs/4425592351/attempts/1"
    )
    evidence = _descriptor(record, "evidence")["annotations"]
    assert evidence["origin"] == "github-actions"
    assert evidence["ci"] == {
        "repository": "acme/app",
        "workflow": "preflight",
        "runId": "4425592351",
        "runAttempt": "1",
        "commit": "d20ace7968ba43c0219f62d71334c1095bab1602",
        "serverUrl": "https://github.com",
    }


def test_attest_refuses_an_incomplete_github_actions_identity(
    monkeypatch, capsys, tmp_path
):
    monkeypatch.chdir(tmp_path)
    _result(tmp_path, _config(tmp_path))
    monkeypatch.setenv("GITHUB_RUN_ID", "4425592351")

    code, _, err = _run(monkeypatch, capsys, "attest", "results/run.json")

    assert code == 2
    assert "GITHUB_REPOSITORY" in err
    assert not (tmp_path / "results/run.preflight.json").exists()


def test_attest_never_overwrites_without_force_and_honours_output(
    monkeypatch, capsys, tmp_path
):
    monkeypatch.chdir(tmp_path)
    _result(tmp_path, _config(tmp_path))
    assert _run(monkeypatch, capsys, "attest", "results/run.json")[0] == 0
    existing = tmp_path / "results/run.preflight.json"
    before = existing.read_text()

    code, _, err = _run(monkeypatch, capsys, "attest", "results/run.json")

    assert code == 2
    assert "already exists; refusing to overwrite it" in err
    assert existing.read_text() == before
    assert _run(monkeypatch, capsys, "attest", "results/run.json", "--force")[0] == 0
    code, out, _ = _run(
        monkeypatch, capsys, "attest", "results/run.json", "--output", "proof.json"
    )
    assert code == 0
    assert "Saved preflight record to proof.json" in out
    assert json.loads((tmp_path / "proof.json").read_text())["_type"] == STATEMENT


def test_attest_json_prints_the_path_and_the_record(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    _result(tmp_path, _config(tmp_path))

    code, out, _ = _run(monkeypatch, capsys, "attest", "results/run.json", "--json")

    assert code == 0
    payload = json.loads(out)
    assert payload["path"] == "results/run.preflight.json"
    assert payload["record"] == json.loads(
        (tmp_path / "results/run.preflight.json").read_text()
    )


def test_existing_commands_and_help_are_unchanged(monkeypatch, capsys, tmp_path):
    code, out, _ = _run(monkeypatch, capsys, "--help")
    assert code == 0
    assert "--audit-source" in out
    code, out, _ = _run(monkeypatch, capsys, "report", "--help")
    assert code == 0
    assert "--format" in out
    code, out, _ = _run(monkeypatch, capsys, "--version")
    assert code == 0
    assert out.startswith("llm-preflight ")
    monkeypatch.chdir(tmp_path)
    config = _config(
        tmp_path,
        {"prompt": "ok", "models": [{"provider": "mock", "model": "local"}]},
    )
    code, out, _ = _run(monkeypatch, capsys, config, "--dry-run", "--json")
    assert code == 0
    assert json.loads(out)["requests"] > 0


def _attest(
    monkeypatch,
    capsys,
    tmp_path,
    *,
    state="pass",
    ci=True,
    timestamp=CHECKED,
    name="run.json",
    selection=None,
):
    """Attest one result in tmp_path, the working directory, and return the record path."""
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "benchmark.json"
    if not config.exists():
        _config(tmp_path)
    _result(
        tmp_path,
        config,
        state=state,
        timestamp=timestamp,
        name=name,
        selection=selection,
    )
    with monkeypatch.context() as scoped:
        if ci:
            for variable, value in GITHUB.items():
                scoped.setenv(variable, value)
        code, _, err = _run(monkeypatch, capsys, "attest", f"results/{name}")
    assert code == 0, err
    return tmp_path / "results" / name.replace(".json", ".preflight.json")


def _edit_record(path, edit):
    record = json.loads(path.read_text())
    edit(record)
    path.write_text(json.dumps(record))


# verify


def test_verify_reports_intact_and_fresh_with_snapshot_and_signature_note(
    monkeypatch, capsys, tmp_path
):
    record = _attest(monkeypatch, capsys, tmp_path)

    code, out, _ = _run(monkeypatch, capsys, "verify", record)

    assert code == 0
    assert "Integrity: intact" in out
    assert (
        "Freshness: fresh — checked 2026-10-10, 7 days ago; "
        "fresh until 2026-11-09 (limit 30 days)"
    ) in out
    assert "Subject:   result results/run.json: matches" in out
    assert f"Route:     openai:gpt-4.1-mini answered as {OBSERVED}\n" in out
    assert (
        "Origin:    GitHub Actions "
        "https://github.com/acme/app/actions/runs/4425592351/attempts/1"
    ) in out
    assert "Snapshot:  retirement snapshot 2026-10-16 (this verifier)" in out
    assert "Signature: not checked here — use gh attestation verify" in out
    assert out.rstrip().endswith("Exit 0.")
    code, out, _ = _run(monkeypatch, capsys, "verify", record, "--json")
    report = json.loads(out)
    assert code == 0
    assert report["integrity"]["ok"] is True
    assert report["freshness"]["state"] == "fresh"
    assert report["freshness"]["age_days"] == 7
    assert report["retirement_snapshot"] == "2026-10-16"
    assert report["signature"] == "not checked here — use gh attestation verify"
    assert report["origin"] == "github-actions"


def test_verify_flags_a_tampered_result_file_but_keeps_freshness_separate(
    monkeypatch, capsys, tmp_path
):
    record = _attest(monkeypatch, capsys, tmp_path)
    result = tmp_path / "results/run.json"
    result.write_text(result.read_text().replace('"complete"', '"partial"'))

    code, out, _ = _run(monkeypatch, capsys, "verify", record, "--json")

    report = json.loads(out)
    assert code == 1
    assert report["integrity"]["ok"] is False
    assert report["integrity"]["problems"] == [
        "the result file results/run.json does not match its subject digest"
    ]
    assert report["freshness"]["state"] == "fresh"


def test_verify_reports_a_changed_config_without_failing_integrity(
    monkeypatch, capsys, tmp_path
):
    record = _attest(monkeypatch, capsys, tmp_path)
    (tmp_path / "benchmark.json").write_text(json.dumps({**CONFIG, "name": "renamed"}))

    code, out, _ = _run(monkeypatch, capsys, "verify", record)

    assert code == 0
    assert "Subject:   config benchmark.json: changed since the check" in out
    assert "Integrity: intact" in out


def _evidence(record):
    return _descriptor(record, "evidence")["annotations"]


@pytest.mark.parametrize(
    ("edit", "problem"),
    [
        (
            lambda record: _evidence(record).update(costConfidence="partial"),
            "a PASSED record needs complete cost confidence",
        ),
        (
            lambda record: _evidence(record)["decision"].update(
                blocking_warnings=["Cost confidence is partial."]
            ),
            "a PASSED record cannot carry blocking warnings",
        ),
        (
            lambda record: record.update(
                predicateType="https://slsa.dev/provenance/v1"
            ),
            "predicateType is not the in-toto test-result v0.1 predicate",
        ),
        (
            lambda record: _evidence(record)["decision"].update(state="inconclusive"),
            "PASSED does not match the inconclusive decision",
        ),
        (
            lambda record: _descriptor(record, "contract")["digest"].update(
                sha256="0" * 64
            ),
            "llm-preflight/contract digest does not match provenance.contract_sha256",
        ),
        (
            lambda record: record["predicate"].update(
                url="https://github.com/acme/other/actions/runs/1/attempts/1"
            ),
            "predicate.url does not match the GitHub Actions identity",
        ),
        *(
            (
                lambda record, value=value: _descriptor(record, "routes")[
                    "annotations"
                ]["routes"][0].update(observedModel=value),
                "llm-preflight/routes carries a malformed observedModel",
            )
            for value in (7, "", "gpt\x1b[31m", ["gpt-a"], ["gpt-a", "gpt-a"])
        ),
    ],
)
def test_verify_rejects_an_internally_inconsistent_record(
    monkeypatch, capsys, tmp_path, edit, problem
):
    record = _attest(monkeypatch, capsys, tmp_path)
    _edit_record(record, edit)

    code, out, _ = _run(monkeypatch, capsys, "verify", record, "--json")

    assert code == 1
    assert problem in json.loads(out)["integrity"]["problems"]


@pytest.mark.parametrize(
    ("today", "state", "exit_code"),
    [(date(2026, 11, 9), "fresh", 0), (date(2026, 11, 10), "stale", 3)],
)
def test_verify_freshness_boundary_is_inclusive_at_max_age_days(
    monkeypatch, capsys, tmp_path, today, state, exit_code
):
    record = _attest(monkeypatch, capsys, tmp_path)
    monkeypatch.setattr(cli, "today_utc", lambda: today)

    code, out, _ = _run(monkeypatch, capsys, "verify", record, "--json")

    report = json.loads(out)
    assert code == exit_code
    assert report["integrity"]["ok"] is True
    assert report["freshness"]["state"] == state
    assert report["freshness"]["valid_until"] == "2026-11-09"


def test_verify_marks_a_record_superseded_once_its_route_retires(
    monkeypatch, capsys, tmp_path
):
    monkeypatch.setattr(cli, "today_utc", lambda: date(2027, 1, 15))
    record = _attest(monkeypatch, capsys, tmp_path, timestamp="2027-01-10T08:00:00Z")

    code, out, _ = _run(monkeypatch, capsys, "verify", record)

    assert code == 3
    assert "Integrity: intact" in out
    assert "Freshness: superseded — checked 2027-01-10, 5 days ago" in out
    assert "- openai:gpt-4.1-mini retired on 2027-01-14" in out
    monkeypatch.setattr(cli, "today_utc", lambda: date(2027, 1, 14))
    assert _run(monkeypatch, capsys, "verify", record)[0] == 3
    monkeypatch.setattr(cli, "today_utc", lambda: date(2027, 1, 13))
    assert _run(monkeypatch, capsys, "verify", record)[0] == 0


def test_verify_rejects_unreadable_records_and_invalid_max_age(
    monkeypatch, capsys, tmp_path
):
    record = _attest(monkeypatch, capsys, tmp_path)
    code, _, err = _run(monkeypatch, capsys, "verify", record, "--max-age-days", "0")
    assert code == 2
    assert "1 to 3650" in err
    broken = tmp_path / "broken.preflight.json"
    broken.write_text("{not json")
    code, _, err = _run(monkeypatch, capsys, "verify", broken)
    assert code == 2
    assert "error:" in err


# gate


def _gate(monkeypatch, capsys, *arguments):
    code, out, err = _run(monkeypatch, capsys, "gate", *arguments, "--json")
    assert out, err
    return code, json.loads(out)


def test_gate_passes_on_a_fresh_passing_ci_record(monkeypatch, capsys, tmp_path):
    _attest(monkeypatch, capsys, tmp_path)

    code, out, _ = _run(monkeypatch, capsys, "gate", "--records", "results")

    assert code == 0
    assert out == (
        "Gate: pass — a fresh passing preflight matches this contract.\n"
        "Why:  Run 4425592351 on acme/app passed this contract and its routes on "
        "2026-10-10 (7 days old); it stays fresh until 2026-11-09. "
        f"openai:gpt-4.1-mini answered as {OBSERVED}. "
        "The signature is not checked here — use gh attestation verify.\n"
        "Exit 0.\n"
    )
    code, report = _gate(monkeypatch, capsys, "benchmark.json", "--records", "results")
    assert code == 0
    assert report["decision"] == "pass"
    assert report["reason_code"] == "fresh_pass"
    assert report["next"] == []
    assert report["network_accessed"] is False
    assert [(item["path"], item["verdict"]) for item in report["records"]] == [
        ("results/run.preflight.json", "pass")
    ]
    assert report["records"][0]["routes"] == [
        {"provider": "openai", "model": "gpt-4.1-mini", "observed_model": OBSERVED}
    ]


def test_gate_blocks_a_changed_contract_why_first_then_next_steps(
    monkeypatch, capsys, tmp_path
):
    record = _attest(monkeypatch, capsys, tmp_path)
    recorded = _descriptor(json.loads(record.read_text()), "contract")["digest"]
    (tmp_path / "benchmark.json").write_text(
        json.dumps({**CONFIG, "validation": {"json_array": True}})
    )

    code, out, _ = _run(monkeypatch, capsys, "gate", "--records", "results")
    _, report = _gate(monkeypatch, capsys, "--records", "results")

    assert code == 1
    assert report["reason_code"] == "contract_changed"
    assert report["why"] == (
        f"benchmark.json changed (contract {recorded['sha256'][:8]}… → "
        f"{report['contract_sha256'][:8]}…). The latest record "
        "(run 4425592351, 7 days old) checked a different contract."
    )
    assert out == (
        "Gate: blocked — no fresh passing preflight for this contract.\n"
        f"Why:  {report['why']}\n"
        "Next: 1. llm-preflight benchmark.json --dry-run   (free: plan and cost)\n"
        "      2. approve the plan, then run the bounded check\n"
        "      3. llm-preflight attest results/<new>.json   (CI does this for you)\n"
        "Exit 1.\n"
    )


def _change_route(tmp_path):
    (tmp_path / "benchmark.json").write_text(
        json.dumps({**CONFIG, "models": [{"provider": "openai", "model": "gpt-4.1"}]})
    )


def _commit(tmp_path, record):
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not installed")
    for arguments in (
        ["init", "-q"],
        ["add", str(record)],
        ["-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "r"],
    ):
        subprocess.run([git, *arguments], cwd=tmp_path, check=True)


@pytest.mark.parametrize(
    ("reason_code", "attest", "after"),
    [
        ("no_record", None, lambda tmp_path, record: record.unlink()),
        ("routes_changed", {}, lambda tmp_path, record: _change_route(tmp_path)),
        ("inconclusive_record", {"state": "inconclusive"}, None),
        ("failed_record", {"state": "fail"}, None),
        ("local_record", {"ci": False}, None),
        (
            "inconsistent_record",
            {},
            lambda tmp_path, record: _edit_record(
                record, lambda data: _evidence(data).update(costConfidence="partial")
            ),
        ),
        ("committed_record", {}, _commit),
    ],
)
def test_gate_blocks_with_each_reason_code(
    monkeypatch, capsys, tmp_path, reason_code, attest, after
):
    record = _attest(monkeypatch, capsys, tmp_path, **(attest or {}))
    if after is not None:
        after(tmp_path, record)

    code, report = _gate(monkeypatch, capsys, "--records", "results")

    assert code == 1
    assert report["decision"] == "blocked"
    assert report["reason_code"] == reason_code
    assert report["why"]
    assert report["next"]


def test_gate_accepts_an_untracked_record_inside_a_git_work_tree(
    monkeypatch, capsys, tmp_path
):
    record = _attest(monkeypatch, capsys, tmp_path)
    _commit(tmp_path, tmp_path / "benchmark.json")

    code, report = _gate(monkeypatch, capsys, "--records", record)

    assert code == 0
    assert report["reason_code"] == "fresh_pass"


@pytest.mark.parametrize(
    ("today", "reason_code", "exit_code"),
    [
        (date(2026, 11, 9), "fresh_pass", 0),
        (date(2026, 11, 10), "stale", 1),
    ],
)
def test_gate_freshness_boundary_under_a_shifted_clock(
    monkeypatch, capsys, tmp_path, today, reason_code, exit_code
):
    _attest(monkeypatch, capsys, tmp_path)
    monkeypatch.setattr(cli, "today_utc", lambda: today)

    code, report = _gate(monkeypatch, capsys, "--records", "results")

    assert (code, report["reason_code"]) == (exit_code, reason_code)


def test_gate_max_age_days_shortens_freshness(monkeypatch, capsys, tmp_path):
    _attest(monkeypatch, capsys, tmp_path)

    code, report = _gate(
        monkeypatch, capsys, "--records", "results", "--max-age-days", "6"
    )

    assert (code, report["reason_code"]) == (1, "stale")
    assert "older than the 6 days allowed" in report["why"]


def test_gate_blocks_a_record_superseded_by_the_verifier_snapshot(
    monkeypatch, capsys, tmp_path
):
    monkeypatch.setattr(cli, "today_utc", lambda: date(2027, 1, 13))
    _attest(monkeypatch, capsys, tmp_path, timestamp="2027-01-10T08:00:00Z")
    assert _gate(monkeypatch, capsys, "--records", "results")[0] == 0
    monkeypatch.setattr(cli, "today_utc", lambda: date(2027, 1, 14))

    code, report = _gate(monkeypatch, capsys, "--records", "results")

    assert (code, report["reason_code"]) == (1, "superseded")
    assert "openai:gpt-4.1-mini (retired on 2027-01-14)" in report["why"]
    assert "2026-10-16" in report["why"]


@pytest.mark.parametrize(
    ("older", "newer", "reason_code"),
    [("pass", "fail", "failed_record"), ("fail", "pass", "fresh_pass")],
)
def test_gate_decides_on_the_newest_matching_record(
    monkeypatch, capsys, tmp_path, older, newer, reason_code
):
    _attest(
        monkeypatch,
        capsys,
        tmp_path,
        state=older,
        timestamp="2026-10-05T08:00:00+00:00",
        name="older.json",
    )
    _attest(monkeypatch, capsys, tmp_path, state=newer, name="newer.json")

    _, report = _gate(monkeypatch, capsys, "--records", "results")

    assert report["reason_code"] == reason_code
    assert sorted(item["verdict"] for item in report["records"]) == sorted(
        ["pass", "failed_record"]
    )


def test_gate_ignores_a_newer_record_for_another_contract(
    monkeypatch, capsys, tmp_path
):
    _attest(monkeypatch, capsys, tmp_path, timestamp="2026-10-05T08:00:00+00:00")
    (tmp_path / "benchmark.json").write_text(
        json.dumps({**CONFIG, "validation": {"json_array": True}})
    )
    _attest(monkeypatch, capsys, tmp_path, state="fail", name="other.json")
    (tmp_path / "benchmark.json").write_text(json.dumps(CONFIG))

    code, report = _gate(monkeypatch, capsys, "--records", "results")

    assert (code, report["reason_code"]) == (0, "fresh_pass")


def test_gate_prefers_a_failure_over_a_pass_of_the_same_age(
    monkeypatch, capsys, tmp_path
):
    _attest(monkeypatch, capsys, tmp_path, name="a.json")
    _attest(monkeypatch, capsys, tmp_path, state="fail", name="b.json")

    assert _gate(monkeypatch, capsys, "--records", "results")[1]["reason_code"] == (
        "failed_record"
    )


def test_gate_cannot_decide_when_a_record_or_the_config_cannot_be_read(
    monkeypatch, capsys, tmp_path
):
    _attest(monkeypatch, capsys, tmp_path)
    broken = tmp_path / "results/broken.preflight.json"
    broken.write_text("{not json")

    code, out, _ = _run(monkeypatch, capsys, "gate", "--records", "results")
    assert code == 3
    assert out.startswith("Gate: cannot decide — an input could not be read.\n")
    assert out.rstrip().endswith("Exit 3.")
    _, report = _gate(monkeypatch, capsys, "--records", "results")
    assert (report["decision"], report["reason_code"]) == ("undecided", "record_error")
    assert "results/broken.preflight.json cannot be checked" in report["why"]
    broken.unlink()
    code, report = _gate(monkeypatch, capsys, "--records", "missing")
    assert (code, report["reason_code"]) == (3, "record_error")
    code, report = _gate(monkeypatch, capsys, "absent.json", "--records", "results")
    assert (code, report["reason_code"]) == (3, "config_error")
    assert "absent.json" in report["why"]


def test_gate_cannot_fingerprint_discovered_routes_offline(
    monkeypatch, capsys, tmp_path
):
    _attest(monkeypatch, capsys, tmp_path)
    (tmp_path / "benchmark.json").write_text(
        json.dumps(
            {"prompt": "ok", "discovery": [{"provider": "openrouter", "limit": 1}]}
        )
    )
    monkeypatch.setattr(
        "llm_preflight.catalog.discover_models",
        lambda _source: pytest.fail("network discovery"),
    )

    code, report = _gate(monkeypatch, capsys, "--records", "results")

    assert (code, report["reason_code"]) == (3, "config_error")
    assert "discovery" in report["why"]


def test_gate_text_and_json_carry_the_same_why_and_next(monkeypatch, capsys, tmp_path):
    _attest(monkeypatch, capsys, tmp_path, state="inconclusive")

    _, out, _ = _run(monkeypatch, capsys, "gate", "--records", "results")
    _, report = _gate(monkeypatch, capsys, "--records", "results")

    assert report["reason_code"] == "inconclusive_record"
    assert f"Why:  {report['why']}\n" in out
    for number, step in enumerate(report["next"], 1):
        assert f"{number}. {step}\n" in out


def test_gate_opens_no_network_connection(monkeypatch, capsys, tmp_path):
    _attest(monkeypatch, capsys, tmp_path)

    def refuse(*args, **kwargs):
        raise AssertionError("gate opened a network connection")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)

    assert _gate(monkeypatch, capsys, "--records", "results")[0] == 0


def test_gate_fingerprints_match_the_provenance_of_a_real_run(
    monkeypatch, capsys, tmp_path
):
    monkeypatch.chdir(tmp_path)
    _config(
        tmp_path,
        {
            "name": "mock",
            "prompts": [
                {
                    "name": "json",
                    "prompt": "Return JSON.",
                    "validation": {"json_object": True},
                }
            ],
            "profiles": "json",
            "aliases": {
                "local": {"provider": "mock", "model": "local", "response": "{}"}
            },
            "models": ["local"],
            "presets": ["json"],
            "repetitions": 1,
            "warmups": 0,
        },
    )
    code, _, err = _run(
        monkeypatch, capsys, "benchmark.json", "--output-dir", "results"
    )
    assert code == 3, err
    (result,) = (tmp_path / "results").glob("*-mock-*.json")
    for variable, value in GITHUB.items():
        monkeypatch.setenv(variable, value)
    assert _run(monkeypatch, capsys, "attest", result)[0] == 0

    code, report = _gate(monkeypatch, capsys, "--records", "results")

    assert (code, report["reason_code"]) == (1, "inconclusive_record")
    record = json.loads(result.with_suffix(".preflight.json").read_text())
    assert record["predicate"]["warnedTests"] == ["mock:local/json"]


SELECTION_CONFIG = {
    "name": "selection",
    "prompt": "Reply with ok.",
    "validation": {"exact": "ok"},
    "prompts": [
        {
            "name": "json",
            "prompt": "Return JSON.",
            "validation": {"json_object": True},
        }
    ],
    "environments": {
        "staging": {
            "models": [{"provider": "mock", "model": "staging", "response": "{}"}]
        }
    },
    "models": [{"provider": "mock", "model": "local", "response": "{}"}],
    "repetitions": 1,
    "warmups": 0,
}


DEFAULT_SELECTION = {
    "prompt": None,
    "tests": None,
    "environment": None,
    "migrationCheck": False,
}


def _selected_run(monkeypatch, capsys, tmp_path, *flags):
    """Run SELECTION_CONFIG on the mock provider under flags, attest it in CI."""
    monkeypatch.chdir(tmp_path)
    if not (tmp_path / "benchmark.json").exists():
        _config(tmp_path, SELECTION_CONFIG)
    code, _, err = _run(
        monkeypatch, capsys, "benchmark.json", *flags, "--output-dir", "results"
    )
    assert code in {1, 3}, err
    (result,) = (tmp_path / "results").glob("*-selection*.json")
    with monkeypatch.context() as scoped:
        for variable, value in GITHUB.items():
            scoped.setenv(variable, value)
        assert _run(monkeypatch, capsys, "attest", result)[0] == 0
    return result.with_suffix(".preflight.json")


@pytest.mark.parametrize(
    ("flags", "gate_flags", "selection"),
    [
        ((), (), {}),
        (("--prompt", "json"), ("--prompt", "json"), {"prompt": "json"}),
        (("--tests", "json"), ("--tests", "json"), {"tests": "json"}),
        (("--profiles", "json"), ("--tests", "json"), {"tests": "json"}),
        (
            ("--tests", "classification,json"),
            ("--profiles", "json,exact-routing-check"),
            {"tests": "exact-routing-check,json"},
        ),
        (("--migration-check",), ("--migration-check",), {"migrationCheck": True}),
        (("--env", "staging"), ("--env", "staging"), {"environment": "staging"}),
        (
            ("--env", "staging", "--prompt", "json"),
            ("--prompt", "json", "--env", "staging"),
            {"prompt": "json", "environment": "staging"},
        ),
        (("--env-file", "ci.env"), (), {}),
    ],
    ids=[
        "default",
        "prompt",
        "tests",
        "profiles",
        "tests-in-another-order",
        "migration-check",
        "environment",
        "environment-and-prompt",
        "env-file",
    ],
)
def test_gate_matches_a_real_run_under_the_same_selection(
    monkeypatch, capsys, tmp_path, flags, gate_flags, selection
):
    (tmp_path / "ci.env").write_text("PARITY_FIXTURE=sk-synthetic-secret\n")
    monkeypatch.setenv("PARITY_FIXTURE", "already-set")
    record = _selected_run(monkeypatch, capsys, tmp_path, *flags)

    code, report = _gate(monkeypatch, capsys, *gate_flags, "--records", "results")

    entry = report["records"][0]
    assert code == 1
    assert entry["verdict"] in {"failed_record", "inconclusive_record"}, entry
    expected = {**DEFAULT_SELECTION, **selection}
    recorded = _descriptor(json.loads(record.read_text()), "evidence")["annotations"]
    assert recorded["selection"] == expected
    assert entry["selection"] == expected
    assert report["selection"] == expected
    # The env file only supplies credentials: neither its path nor a value is kept.
    assert "sk-synthetic-secret" not in record.read_text()
    assert "ci.env" not in record.read_text()


@pytest.mark.parametrize(
    ("flags", "gate_flags", "ran", "requires"),
    [
        (("--tests", "json"), (), "--tests json", "a default run"),
        (("--prompt", "json"), (), "--prompt json", "a default run"),
        ((), ("--env", "staging"), "a default run", "--env staging"),
        (
            ("--migration-check",),
            ("--tests", "json"),
            "--migration-check",
            "--tests json",
        ),
    ],
)
def test_gate_blocks_a_record_made_under_another_selection(
    monkeypatch, capsys, tmp_path, flags, gate_flags, ran, requires
):
    _selected_run(monkeypatch, capsys, tmp_path, *flags)

    code, report = _gate(monkeypatch, capsys, *gate_flags, "--records", "results")

    assert (code, report["reason_code"]) == (1, "selection_changed")
    assert f"ran {ran}" in report["why"]
    assert f"this gate requires {requires}" in report["why"]
    assert report["next"][0].startswith(
        " ".join(["llm-preflight benchmark.json", *gate_flags, "--dry-run"])
    )
    assert report["next"][-1] == (
        f"if CI runs {ran} on purpose, give the gate the same selection"
    )


def test_gate_blocks_a_record_that_does_not_record_its_selection(
    monkeypatch, capsys, tmp_path
):
    record = _attest(monkeypatch, capsys, tmp_path, selection=UNRECORDED)

    code, report = _gate(monkeypatch, capsys, "--records", "results")

    assert (
        json.loads(record.read_text())["predicate"]["configuration"][3]["annotations"][
            "selection"
        ]
        is None
    )
    assert (code, report["reason_code"]) == (1, "selection_changed")
    assert "does not record which selection it ran" in report["why"]


def test_gate_under_a_selection_detects_a_change_to_the_selected_prompt(
    monkeypatch, capsys, tmp_path
):
    _selected_run(monkeypatch, capsys, tmp_path, "--prompt", "json")
    edited = copy.deepcopy(SELECTION_CONFIG)
    edited["prompts"][0]["validation"] = {"json_array": True}
    _config(tmp_path, edited)

    code, report = _gate(
        monkeypatch, capsys, "--prompt", "json", "--records", "results"
    )

    assert (code, report["reason_code"]) == (1, "contract_changed")
    assert report["next"][0].startswith(
        "llm-preflight benchmark.json --prompt json --dry-run"
    )
    _config(tmp_path, {**SELECTION_CONFIG, "prompts": []})

    code, report = _gate(
        monkeypatch, capsys, "--prompt", "json", "--records", "results"
    )

    assert (code, report["reason_code"]) == (3, "config_error")
    assert "unknown custom prompt 'json'" in report["why"]


@pytest.mark.parametrize(
    "flags",
    [
        ("--tests", "json", "--profiles", "json"),
        ("--prompt", "json", "--tests", "json"),
        ("--migration-check", "--prompt", "json"),
        ("--migration-check", "--tests", "json"),
    ],
)
def test_gate_refuses_the_selections_a_run_refuses(
    monkeypatch, capsys, tmp_path, flags
):
    _config(tmp_path, SELECTION_CONFIG)
    monkeypatch.chdir(tmp_path)

    code, _, err = _run(monkeypatch, capsys, "gate", *flags, "--records", "results")

    assert code == 2
    assert "cannot be combined" in err


@pytest.mark.parametrize(
    "selection",
    [
        "json",
        {"prompt": "json"},
        {**DEFAULT_SELECTION, "prompt": 7},
        {**DEFAULT_SELECTION, "prompt": ""},
        {**DEFAULT_SELECTION, "tests": ["json"]},
        {**DEFAULT_SELECTION, "migrationCheck": "yes"},
        {**DEFAULT_SELECTION, "prompt": "json", "migrationCheck": True},
        {**DEFAULT_SELECTION, "prompt": "json", "tests": "json"},
        {**DEFAULT_SELECTION, "prompt": "a\x1b[31m"},
        {**DEFAULT_SELECTION, "environment": "staging\n"},
        {**DEFAULT_SELECTION, "extra": None},
    ],
)
def test_verify_rejects_a_malformed_selection(monkeypatch, capsys, tmp_path, selection):
    record = _attest(monkeypatch, capsys, tmp_path)
    _edit_record(record, lambda record: _evidence(record).update(selection=selection))

    code, out, _ = _run(monkeypatch, capsys, "verify", record, "--json")

    assert code == 1
    assert (
        "llm-preflight/evidence carries a malformed selection"
        in (json.loads(out)["integrity"]["problems"])
    )


@pytest.mark.parametrize(
    "edit",
    [
        lambda record: record["subject"][0].update(name="bench\x00mark.json"),
        lambda record: record["subject"][0].update(name=""),
        lambda record: _evidence(record).update(checkedAt="9999-12-31T00:00:00+00:00"),
    ],
)
def test_gate_reports_a_hostile_record_as_inconsistent_without_crashing(
    monkeypatch, capsys, tmp_path, edit
):
    record = _attest(monkeypatch, capsys, tmp_path)
    _edit_record(record, edit)

    code, report = _gate(monkeypatch, capsys, "--records", "results")

    assert (code, report["reason_code"]) == (1, "inconsistent_record")


INJECTIONS = ["\x1b[31m", "\n", "\r"]
ESCAPED = {"\x1b[31m": "\\x1b[31m", "\n": "\\n", "\r": "\\r"}


def _injected(field, payload):
    """An edit that appends payload to one record string a report displays."""

    def route(record):
        return _descriptor(record, "routes")["annotations"]["routes"][0]

    edits = {
        "provider": lambda record: route(record).update(provider=f"openai{payload}"),
        "model": lambda record: route(record).update(
            model=f"gpt-4.1-mini{payload}fake"
        ),
        "observedModel": lambda record: route(record).update(
            observedModel=f"{OBSERVED}{payload}fake"
        ),
        "url": lambda record: record["predicate"].update(
            url=record["predicate"]["url"] + payload
        ),
        "workflow": lambda record: _evidence(record)["ci"].update(
            workflow=f"preflight{payload}fake"
        ),
    }
    return edits[field]


def _no_raw_control_characters(text):
    return all(char.isprintable() for line in text.split("\n") for char in line)


def _gate_lines(report):
    """Headline, why, one line per next step and the exit line: nothing injected."""
    return 2 + len(report["next"]) + 1


@pytest.mark.parametrize("payload", INJECTIONS, ids=["ansi", "newline", "return"])
@pytest.mark.parametrize(
    "field", ["provider", "model", "observedModel", "url", "workflow"]
)
def test_record_strings_never_reach_text_output_as_control_characters(
    monkeypatch, capsys, tmp_path, field, payload
):
    record = _attest(monkeypatch, capsys, tmp_path)
    _edit_record(record, _injected(field, payload))

    code, text, _ = _run(monkeypatch, capsys, "verify", record)
    _, report, _ = _run(monkeypatch, capsys, "verify", record, "--json")
    gate_code, gate_text, _ = _run(monkeypatch, capsys, "gate", "--records", "results")
    _, gate_report = _gate(monkeypatch, capsys, "--records", "results")

    assert code == 1
    assert json.loads(report)["integrity"]["ok"] is False
    assert _no_raw_control_characters(text), text
    if field in {"provider", "model", "url"}:
        assert ESCAPED[payload] in text, text
    assert (gate_code, gate_report["reason_code"]) == (1, "inconsistent_record")
    assert _no_raw_control_characters(gate_text), gate_text
    assert len(gate_text.splitlines()) == _gate_lines(gate_report), gate_text


@pytest.mark.parametrize(
    ("field", "problem"),
    [
        ("provider", "llm-preflight/routes carries a malformed provider or model"),
        ("model", "llm-preflight/routes carries a malformed provider or model"),
        ("observedModel", "llm-preflight/routes carries a malformed observedModel"),
    ],
)
def test_verify_requires_printable_bounded_route_names(
    monkeypatch, capsys, tmp_path, field, problem
):
    record = _attest(monkeypatch, capsys, tmp_path)
    for value in ["", "x" * 257, "gpt\x1b[31m", "gpt\nfake", "gpt\rfake"]:
        _edit_record(
            record,
            lambda record, value=value: _descriptor(record, "routes")["annotations"][
                "routes"
            ][0].update({field: value}),
        )

        code, out, _ = _run(monkeypatch, capsys, "verify", record, "--json")

        assert code == 1, value
        assert problem in json.loads(out)["integrity"]["problems"], value


@pytest.mark.parametrize("payload", INJECTIONS, ids=["ansi", "newline", "return"])
def test_gate_text_escapes_a_record_file_name_with_control_characters(
    monkeypatch, capsys, tmp_path, payload
):
    record = _attest(monkeypatch, capsys, tmp_path)
    _edit_record(record, lambda record: _evidence(record).update(costConfidence="?"))
    record.rename(record.with_name(f"evil{payload}x.preflight.json"))

    code, text, _ = _run(monkeypatch, capsys, "gate", "--records", "results")
    _, report = _gate(monkeypatch, capsys, "--records", "results")

    assert (code, report["reason_code"]) == (1, "inconsistent_record")
    assert _no_raw_control_characters(text), text
    assert len(text.splitlines()) == _gate_lines(report), text
    assert f"evil{ESCAPED[payload]}x.preflight.json" in text


def test_gate_cannot_decide_on_a_config_that_is_not_an_object(
    monkeypatch, capsys, tmp_path
):
    _attest(monkeypatch, capsys, tmp_path)
    (tmp_path / "benchmark.json").write_text("[]")

    code, report = _gate(monkeypatch, capsys, "--records", "results")

    assert (code, report["reason_code"]) == (3, "config_error")


def test_gate_records_share_one_shape_whatever_the_verdict(
    monkeypatch, capsys, tmp_path
):
    _attest(monkeypatch, capsys, tmp_path, name="a.json")
    _commit(tmp_path, tmp_path / "results/a.preflight.json")
    _attest(monkeypatch, capsys, tmp_path, name="b.json")

    _, report = _gate(monkeypatch, capsys, "--records", "results")

    shapes = {tuple(item) for item in report["records"]}
    assert len(shapes) == 1
    assert sorted(item["verdict"] for item in report["records"]) == [
        "committed_record",
        "pass",
    ]
