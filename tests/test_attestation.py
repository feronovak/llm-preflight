import copy
import hashlib
import json
import shutil
import socket
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from llm_preflight import attestation, cli, runner
from llm_preflight.catalog import resolve_models
from llm_preflight.contracts import _fingerprint, provenance, selection_fingerprint
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
# The repository every gate in this module expects, unless a test says otherwise.
REPO = ("--repository", "acme/app")
GITHUB = {
    "GITHUB_REPOSITORY": "acme/app",
    "GITHUB_WORKFLOW": "preflight",
    "GITHUB_RUN_ID": "4425592351",
    "GITHUB_RUN_ATTEMPT": "1",
    "GITHUB_SHA": "d20ace7968ba43c0219f62d71334c1095bab1602",
    "GITHUB_SERVER_URL": "https://github.com",
}
# The identity a run under GITHUB writes into its result.
RUN_IDENTITY = {
    "repository": "acme/app",
    "workflow": "preflight",
    "runId": "4425592351",
    "runAttempt": "1",
    "commit": "d20ace7968ba43c0219f62d71334c1095bab1602",
    "serverUrl": "https://github.com",
}


@pytest.fixture(autouse=True)
def local_clock_and_environment(monkeypatch):
    """No GitHub identity unless a test sets one, and a pinned verifier clock.

    The run stamp uses that same day. A later wall clock must not make attest
    reject a run this suite just produced.
    """
    for name in GITHUB:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cli, "today_utc", lambda: TODAY)
    wall_now = datetime.now

    class Pinned(datetime):
        @classmethod
        def now(cls, tz=None):
            wall = wall_now(timezone.utc)
            pinned = wall.replace(year=TODAY.year, month=TODAY.month, day=TODAY.day)
            if tz is None:
                return pinned.replace(tzinfo=None)
            return pinned.astimezone(tz)

    monkeypatch.setattr(runner, "datetime", Pinned)


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
    ci=None,
):
    """A billable single-model result whose decision comes from decision.py.

    `observed=UNRECORDED` or `selection=UNRECORDED` writes a result from before
    that field existed; a default run's selection is the default. `ci` is the
    run-time GitHub Actions identity the run recorded, None outside CI.
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
        "ci": ci,
    }
    if selection is not UNRECORDED:
        recorded = selection or {
            "prompt": None,
            "tests": None,
            "environment": None,
            "migration_check": False,
            "smoke": False,
            "repetitions": 5,
        }
        result["selection"] = recorded
        # The same digest run_benchmark stores before redaction.
        result["selection_sha256"] = selection_fingerprint(
            {
                "prompt": recorded["prompt"],
                "tests": recorded["tests"],
                "environment": recorded["environment"],
                "migrationCheck": recorded["migration_check"],
                "smoke": recorded["smoke"],
                "repetitions": recorded["repetitions"],
            }
        )
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
    for name in ("contract", "routes", "pricing"):
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
    sealed = evidence["provenance"]
    assert _descriptor(record, "evidence")["digest"] == {
        "sha256": sealed["evidence_sha256"]
    }
    for key, value in saved["provenance"].items():
        if key != "evidence_sha256":
            assert sealed[key] == value
    # The record seals the selection hash and the verdict. The result file
    # keeps the run's provenance, so its evidence digest differs.
    assert sealed["selection_sha256"] == saved.get("selection_sha256")
    assert sealed["decision_state"] == saved["decision"]["state"]
    assert sealed["blocking_warnings"] == saved["decision"]["blocking_warnings"]
    assert sealed["cost_confidence"] == saved["cost_confidence"]
    assert sealed["evidence_sha256"] == _fingerprint(
        {key: value for key, value in sealed.items() if key != "evidence_sha256"}
    )
    assert sealed["evidence_sha256"] != saved["provenance"]["evidence_sha256"]
    assert evidence["checkedAt"] == CHECKED
    assert evidence["runId"] == saved["run_id"]
    assert evidence["requests"] == 3
    assert evidence["costConfidence"] == saved["cost_confidence"]
    assert evidence["costUsd"] == saved["total_estimated_cost_usd"]
    assert evidence["retirementSnapshot"] == "2026-10-26"
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
    _result(tmp_path, _config(tmp_path), ci=RUN_IDENTITY)
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
    """Attest one result in tmp_path, the working directory, and return the record path.

    With `ci`, the result was run and is attested in the same GitHub Actions run.
    """
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
        ci=RUN_IDENTITY if ci else None,
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
    assert "Snapshot:  retirement snapshot 2026-10-26 (this verifier)" in out
    assert "Signature: not checked here — use gh attestation verify" in out
    assert out.rstrip().endswith("Exit 0.")
    code, out, _ = _run(monkeypatch, capsys, "verify", record, "--json")
    report = json.loads(out)
    assert code == 0
    assert report["integrity"]["ok"] is True
    assert report["freshness"]["state"] == "fresh"
    assert report["freshness"]["age_days"] == 7
    assert report["retirement_snapshot"] == "2026-10-26"
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


def _gate(monkeypatch, capsys, *arguments, repository=REPO):
    code, out, err = _run(
        monkeypatch, capsys, "gate", *repository, *arguments, "--json"
    )
    assert out, err
    return code, json.loads(out)


def test_gate_passes_on_a_fresh_passing_ci_record(monkeypatch, capsys, tmp_path):
    _attest(monkeypatch, capsys, tmp_path)

    code, out, _ = _run(monkeypatch, capsys, "gate", *REPO, "--records", "results")

    assert code == 0
    assert out == (
        "Gate: pass — a fresh passing preflight matches this contract.\n"
        "Why:  Run 4425592351 on acme/app passed this contract, its prompts and its routes on "
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


@pytest.mark.parametrize(
    ("flag", "environment", "reason_code"),
    [
        (("--repository", "acme/app"), {}, "fresh_pass"),
        (("--repository", "ACME/App"), {}, "fresh_pass"),
        (("--repository", "acme/other"), {}, "foreign_record"),
        (("--repository", "other/app"), {}, "foreign_record"),
        ((), {"GITHUB_REPOSITORY": "acme/app"}, "fresh_pass"),
        (
            (),
            {
                "GITHUB_REPOSITORY": "Acme/APP",
                "GITHUB_SERVER_URL": "https://GitHub.com",
            },
            "fresh_pass",
        ),
        ((), {"GITHUB_REPOSITORY": "fork/app"}, "foreign_record"),
        (
            (),
            {
                "GITHUB_REPOSITORY": "acme/app",
                "GITHUB_SERVER_URL": "https://ghe.example.com",
            },
            "foreign_record",
        ),
        (("--repository", "ACME/App"), {"GITHUB_REPOSITORY": "acme/app"}, "fresh_pass"),
    ],
    ids=[
        "flag",
        "flag-case-insensitive",
        "flag-other-name",
        "flag-other-owner",
        "environment",
        "environment-case-insensitive",
        "environment-fork",
        "environment-other-server",
        "flag-agrees-with-environment",
    ],
)
def test_gate_counts_only_records_from_the_expected_repository(
    monkeypatch, capsys, tmp_path, flag, environment, reason_code
):
    _attest(monkeypatch, capsys, tmp_path)
    for variable, value in environment.items():
        monkeypatch.setenv(variable, value)

    code, report = _gate(monkeypatch, capsys, "--records", "results", repository=flag)

    assert report["reason_code"] == reason_code
    assert code == (0 if reason_code == "fresh_pass" else 1)
    if reason_code == "foreign_record":
        assert report["records"][0]["verdict"] == "foreign_record"
        assert "comes from acme/app on https://github.com, not " in report["why"]
        assert report["next"][0] == "run the bounded check in this repository's CI"


def test_gate_cannot_decide_without_the_expected_repository(
    monkeypatch, capsys, tmp_path
):
    _attest(monkeypatch, capsys, tmp_path)

    code, out, _ = _run(monkeypatch, capsys, "gate", "--records", "results")
    _, report = _gate(monkeypatch, capsys, "--records", "results", repository=())

    assert (code, report["decision"], report["reason_code"]) == (
        3,
        "undecided",
        "repository_unknown",
    )
    assert out.startswith("Gate: cannot decide")
    assert "GITHUB_REPOSITORY" in report["why"]
    assert report["next"] == [
        (
            "llm-preflight gate benchmark.json --repository OWNER/NAME --records "
            "results   (the repository this tree belongs to)"
        )
    ]
    assert report["repository"] is None


@pytest.mark.parametrize("value", ["acme", "acme/app/extra", "acme/app\n", "../app"])
def test_gate_refuses_a_malformed_expected_repository(
    monkeypatch, capsys, tmp_path, value
):
    _attest(monkeypatch, capsys, tmp_path)

    code, _, err = _run(
        monkeypatch, capsys, "gate", "--repository", value, "--records", "results"
    )

    assert code == 2
    assert "OWNER/NAME" in err


def test_verify_shows_the_record_repository(monkeypatch, capsys, tmp_path):
    record = _attest(monkeypatch, capsys, tmp_path)
    local = _attest(monkeypatch, capsys, tmp_path, ci=False, name="local.json")

    _, out, _ = _run(monkeypatch, capsys, "verify", record)
    _, report, _ = _run(monkeypatch, capsys, "verify", record, "--json")
    _, local_out, _ = _run(monkeypatch, capsys, "verify", local)

    assert "Repository: acme/app on https://github.com\n" in out
    assert json.loads(report)["repository"] == "acme/app"
    assert "Repository: none — a local record\n" in local_out


def test_gate_blocks_a_changed_contract_why_first_then_next_steps(
    monkeypatch, capsys, tmp_path
):
    record = _attest(monkeypatch, capsys, tmp_path)
    recorded = _descriptor(json.loads(record.read_text()), "contract")["digest"]
    (tmp_path / "benchmark.json").write_text(
        json.dumps({**CONFIG, "validation": {"json_array": True}})
    )

    code, out, _ = _run(monkeypatch, capsys, "gate", *REPO, "--records", "results")
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
    assert "2026-10-26" in report["why"]


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

    code, out, _ = _run(monkeypatch, capsys, "gate", *REPO, "--records", "results")
    assert code == 3
    assert out.startswith(
        "Gate: cannot decide — an input is missing or could not be read.\n"
    )
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

    _, out, _ = _run(monkeypatch, capsys, "gate", *REPO, "--records", "results")
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
    for variable, value in GITHUB.items():
        monkeypatch.setenv(variable, value)
    code, _, err = _run(
        monkeypatch, capsys, "benchmark.json", "--output-dir", "results"
    )
    assert code == 3, err
    (result,) = (tmp_path / "results").glob("*-mock-*.json")
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
    "smoke": False,
}


def test_a_run_is_stamped_on_the_verifier_day_not_a_later_wall_clock(
    monkeypatch, capsys, tmp_path
):
    """The suite's verifier is TODAY. A later wall clock must not date the run
    after that day, or attest rejects the run the suite just produced."""
    monkeypatch.chdir(tmp_path)
    _config(tmp_path, SELECTION_CONFIG)
    code, _, err = _run(
        monkeypatch, capsys, "benchmark.json", "--output-dir", "results"
    )
    assert code in {1, 3}, err
    (result,) = (tmp_path / "results").glob("*-selection*.json")
    stamped = json.loads(result.read_text())["timestamp"]
    assert stamped[:10] == TODAY.isoformat(), stamped
    assert _run(monkeypatch, capsys, "attest", result)[0] == 0


def _selected_run(monkeypatch, capsys, tmp_path, *flags):
    """Run SELECTION_CONFIG, or the benchmark.json already there, on the mock
    provider under flags, and attest it in the same GitHub Actions run."""
    monkeypatch.chdir(tmp_path)
    if not (tmp_path / "benchmark.json").exists():
        _config(tmp_path, SELECTION_CONFIG)
    with monkeypatch.context() as scoped:
        for variable, value in GITHUB.items():
            scoped.setenv(variable, value)
        code, _, err = _run(
            monkeypatch, capsys, "benchmark.json", *flags, "--output-dir", "results"
        )
        assert code in {1, 3}, err
        (result,) = (tmp_path / "results").glob("*-selection*.json")
        assert _run(monkeypatch, capsys, "attest", result)[0] == 0
    # The verifier's clock is the run's own date, so freshness never depends on
    # when the suite runs.
    ran = date.fromisoformat(json.loads(result.read_text())["timestamp"][:10])
    monkeypatch.setattr(cli, "today_utc", lambda: ran)
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
        (("--smoke",), ("--smoke",), {"smoke": True}),
        (
            ("--smoke", "--tests", "json"),
            ("--tests", "json", "--smoke"),
            {"smoke": True, "tests": "json"},
        ),
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
        "smoke",
        "smoke-and-tests",
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
    # SELECTION_CONFIG runs one repetition per prompt, as does every test suite.
    expected = {**DEFAULT_SELECTION, **selection, "repetitions": 1}
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


def test_gate_explains_a_record_without_the_hash_of_its_raw_selection(
    monkeypatch, capsys, tmp_path
):
    """A record with the same flags but no selection hash ran no other
    selection: the why names the missing hash and the version that records it."""
    monkeypatch.chdir(tmp_path)
    config = _config(tmp_path)
    result = _result(tmp_path, config, ci=RUN_IDENTITY)
    data = json.loads(result.read_text())
    del data["selection_sha256"]
    result.write_text(json.dumps(data, indent=2))
    with monkeypatch.context() as scoped:
        for variable, value in GITHUB.items():
            scoped.setenv(variable, value)
        code, _, err = _run(monkeypatch, capsys, "attest", "results/run.json")
    assert code == 0, err

    code, report = _gate(monkeypatch, capsys, "--records", "results")

    assert (code, report["reason_code"]) == (1, "selection_changed")
    assert report["records"][0]["reason"] == "does not record its raw selection"
    assert "does not carry the hash of its raw selection" in report["why"]
    assert "attest with llm-preflight 2.22.0 or later" in report["why"]
    assert "not the selection this gate requires" not in report["why"]


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

    code, _, err = _run(
        monkeypatch, capsys, "gate", *REPO, *flags, "--records", "results"
    )

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
        {**DEFAULT_SELECTION, "smoke": True, "repetitions": 5},
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
    gate_code, gate_text, _ = _run(
        monkeypatch, capsys, "gate", *REPO, "--records", "results"
    )
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

    code, text, _ = _run(monkeypatch, capsys, "gate", *REPO, "--records", "results")
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


# prompts and request options

REQUEST_CONFIG = {
    **SELECTION_CONFIG,
    "request": {"temperature": 0, "max_output_tokens": 64, "system_prompt": "Terse."},
    "prompts": [
        {
            "name": "json",
            "prompt": "Return JSON.",
            "validation": {"json_object": True},
            "system_prompt": "S1",
            "request": {"temperature": 0},
            "presets": ["json"],
        },
        {"name": "plain", "prompt": "Say plain.", "validation": {"contains": "plain"}},
    ],
}


def _edited(edit, config=REQUEST_CONFIG):
    edited = copy.deepcopy(config)
    edit(edited)
    return edited


@pytest.mark.parametrize(
    ("flags", "edit", "prompt", "changed"),
    [
        ((), lambda c: c.update(prompt="Reply with no."), "config-prompt", "text"),
        (
            (),
            lambda c: c["request"].update(system_prompt="Ignore it."),
            "config-prompt",
            "request options",
        ),
        (
            (),
            lambda c: c["request"].update(temperature=1.5),
            "config-prompt",
            "request options",
        ),
        (
            (),
            lambda c: c["request"].update(max_output_tokens=5),
            "config-prompt",
            "request options",
        ),
        (
            (),
            lambda c: c["request"].update(reasoning_effort="high"),
            "config-prompt",
            "request options",
        ),
        (
            (),
            lambda c: c["request"].update(provider_options={"top_p": 0.1}),
            "config-prompt",
            "request options",
        ),
        (
            (),
            lambda c: c.update(presets=["no-reasoning"]),
            "config-prompt",
            "request options",
        ),
        (
            (),
            lambda c: c.update(prompt="Reply with no.", request={"temperature": 1}),
            "config-prompt",
            "text and the request options",
        ),
        (
            ("--prompt", "json"),
            lambda c: c["prompts"][0].update(system_prompt="S2"),
            "json",
            "request options",
        ),
        (
            ("--prompt", "json"),
            lambda c: c["prompts"][0]["request"].update(temperature=2),
            "json",
            "request options",
        ),
        (
            ("--tests", "json"),
            lambda c: c["prompts"][0].update(presets=["no-reasoning"]),
            "json",
            "request options",
        ),
        (
            ("--tests", "json"),
            lambda c: c["prompts"][0].update(system_prompt="S2"),
            "json",
            "request options",
        ),
        (
            ("--tests", "json"),
            lambda c: c["request"].update(max_output_tokens=5),
            "json",
            "request options",
        ),
    ],
)
def test_gate_blocks_a_changed_prompt_text_or_request_option(
    monkeypatch, capsys, tmp_path, flags, edit, prompt, changed
):
    _config(tmp_path, REQUEST_CONFIG)
    record = _selected_run(monkeypatch, capsys, tmp_path, *flags)
    assert _gate(monkeypatch, capsys, *flags, "--records", "results")[1][
        "reason_code"
    ] in {"failed_record", "inconclusive_record"}
    _config(tmp_path, _edited(edit))

    code, report = _gate(monkeypatch, capsys, *flags, "--records", "results")

    assert (code, report["reason_code"]) == (1, "prompt_changed")
    assert report["records"][0]["verdict"] == "prompt_changed"
    assert f"The {changed} of prompt {prompt} changed" in report["why"]
    assert "run 4425592351" in report["why"]
    assert report["next"][0].startswith(
        " ".join(["llm-preflight benchmark.json", *flags, "--dry-run"])
    )
    assert record.exists()


@pytest.mark.parametrize(
    ("edit", "why"),
    [
        (
            lambda prompts: prompts.append(
                {**prompts[0], "name": "extra", "sha256": "0" * 64}
            ),
            (
                "The latest record (run 4425592351, checked today) checked "
                "prompt extra, which is no longer sent."
            ),
        ),
        (
            lambda prompts: prompts[0].update(name="other"),
            (
                "benchmark.json now sends prompt json, which the latest record "
                "(run 4425592351, checked today) did not check."
            ),
        ),
    ],
    ids=["no-longer-sent", "not-checked"],
)
def test_gate_blocks_a_prompt_the_record_did_not_check_or_no_longer_sends(
    monkeypatch, capsys, tmp_path, edit, why
):
    _config(tmp_path, REQUEST_CONFIG)
    record = _selected_run(monkeypatch, capsys, tmp_path, "--tests", "json")
    _edit_record(record, lambda data: edit(_evidence(data)["provenance"]["prompts"]))
    reseal(record)

    code, report = _gate(monkeypatch, capsys, "--tests", "json", "--records", "results")

    assert (code, report["reason_code"], report["why"]) == (1, "prompt_changed", why)


def reseal(record):
    """Re-hash an edited record's provenance, as a writer that meant it would."""

    def seal(data):
        evidence = _evidence(data)["provenance"]
        unsealed = {k: v for k, v in evidence.items() if k != "evidence_sha256"}
        evidence["evidence_sha256"] = _fingerprint(unsealed)
        _descriptor(data, "evidence")["digest"]["sha256"] = evidence["evidence_sha256"]

    _edit_record(record, seal)


def test_gate_blocks_a_record_whose_prompts_carry_no_request_fingerprint(
    monkeypatch, capsys, tmp_path
):
    record = _attest(monkeypatch, capsys, tmp_path)
    _edit_record(
        record,
        lambda data: [
            entry.pop("request_sha256", None)
            for entry in _evidence(data)["provenance"]["prompts"]
        ],
    )
    reseal(record)

    code, report = _gate(monkeypatch, capsys, "--records", "results")

    assert (code, report["reason_code"]) == (1, "prompt_changed")
    assert (
        "does not record the request options its prompts were sent with"
        in (report["why"])
    )


PARITY_CONFIG = {
    **REQUEST_CONFIG,
    "environments": {
        "staging": {
            "models": [{"provider": "mock", "model": "staging", "response": "{}"}],
            "request": {"temperature": 0.5},
        }
    },
}


@pytest.mark.parametrize(
    ("config", "flags", "selection"),
    [
        (PARITY_CONFIG, (), {}),
        (PARITY_CONFIG, ("--prompt", "json"), {"prompt": "json"}),
        (PARITY_CONFIG, ("--tests", "json"), {"tests": "json"}),
        (
            PARITY_CONFIG,
            ("--tests", "plain,classification,json"),
            {"tests": "exact-routing-check,json,plain"},
        ),
        ({**PARITY_CONFIG, "profiles": ["plain", "json"]}, (), {}),
        (
            {**PARITY_CONFIG, "profiles": "json"},
            ("--prompt", "plain"),
            {"prompt": "plain"},
        ),
        (PARITY_CONFIG, ("--migration-check",), {"migrationCheck": True}),
        (PARITY_CONFIG, ("--env", "staging"), {"environment": "staging"}),
        (PARITY_CONFIG, ("--smoke",), {"smoke": True}),
        (
            PARITY_CONFIG,
            ("--env", "staging", "--smoke", "--prompt", "json"),
            {"environment": "staging", "smoke": True, "prompt": "json"},
        ),
    ],
    ids=[
        "default",
        "prompt",
        "tests",
        "tests-built-in-and-custom",
        "config-profiles",
        "config-profiles-with-prompt",
        "migration-check",
        "environment",
        "smoke",
        "environment-smoke-prompt",
    ],
)
def test_gate_fingerprints_every_prompt_and_request_exactly_as_the_run_sent_them(
    monkeypatch, capsys, tmp_path, config, flags, selection
):
    _config(tmp_path, config)
    record = _selected_run(monkeypatch, capsys, tmp_path, *flags)
    result = json.loads(
        record.with_name(record.name.replace(".preflight", "")).read_text()
    )

    current = attestation.current_fingerprints(tmp_path / "benchmark.json", selection)

    # Every entry, in any order: a recorded --tests selector is canonical, so
    # custom tests may run in another order, and the gate compares them so.
    assert sorted(current["prompts"], key=json.dumps) == sorted(
        result["provenance"]["prompts"], key=json.dumps
    )
    assert all(len(entry["request_sha256"]) == 64 for entry in current["prompts"])
    assert current["contract_sha256"] == result["provenance"]["contract_sha256"]
    assert current["routes_sha256"] == result["provenance"]["routes_sha256"]
    assert current["repetitions"] == result["selection"]["repetitions"]


# what a gate judges a record by


def test_gate_judges_a_record_by_its_own_consistency_never_by_files_in_the_tree(
    monkeypatch, capsys, tmp_path
):
    _attest(monkeypatch, capsys, tmp_path, timestamp="2026-10-05T08:00:00+00:00")
    newer = _attest(monkeypatch, capsys, tmp_path, state="fail", name="newer.json")
    # A pull request plants other bytes where the newer record's result was.
    (tmp_path / "results/newer.json").write_text("{}")
    (tmp_path / "benchmark.json").write_text(json.dumps(CONFIG, indent=1))

    code, report = _gate(monkeypatch, capsys, "--records", "results")
    verify_code, verify_out, _ = _run(monkeypatch, capsys, "verify", newer, "--json")

    assert (code, report["reason_code"]) == (1, "failed_record")
    # verify, asked about this record and its files, still reports the change.
    assert verify_code == 1
    assert (
        "the result file results/newer.json does not match its subject digest"
        in (json.loads(verify_out)["integrity"]["problems"])
    )


@pytest.mark.parametrize(
    ("broken", "edit", "outcome"),
    [
        (
            "2026-10-12T08:00:00+00:00",
            lambda data: _evidence(data).update(costConfidence="partial"),
            (3, "undecided", "record_error"),
        ),
        (
            "2026-10-05T08:00:00+00:00",
            lambda data: _evidence(data).update(checkedAt="not a time"),
            (3, "undecided", "record_error"),
        ),
        (
            "2026-10-05T08:00:00+00:00",
            lambda data: _evidence(data).update(costConfidence="partial"),
            (0, "pass", "fresh_pass"),
        ),
    ],
    ids=["broken-and-newer", "broken-without-a-date", "broken-and-older"],
)
def test_gate_cannot_decide_while_a_broken_record_might_be_the_newest(
    monkeypatch, capsys, tmp_path, broken, edit, outcome
):
    _attest(monkeypatch, capsys, tmp_path)
    record = _attest(monkeypatch, capsys, tmp_path, timestamp=broken, name="b.json")
    _edit_record(record, edit)

    code, report = _gate(monkeypatch, capsys, "--records", "results")

    assert (code, report["decision"], report["reason_code"]) == outcome
    if outcome[0] == 3:
        assert report["why"].startswith(
            "results/b.preflight.json fails its integrity check"
        )
        assert "might be newer than run 4425592351" in report["why"]
        assert report["next"][0] == (
            "llm-preflight verify results/b.preflight.json   "
            "(free: every integrity problem)"
        )


# run-time identity


def test_a_run_records_the_github_actions_identity_it_ran_in(
    monkeypatch, capsys, tmp_path
):
    monkeypatch.chdir(tmp_path)
    _config(tmp_path, SELECTION_CONFIG)
    with monkeypatch.context() as scoped:
        for variable, value in GITHUB.items():
            scoped.setenv(variable, value)
        _run(monkeypatch, capsys, "benchmark.json", "--output-dir", "ci")
    _run(monkeypatch, capsys, "benchmark.json", "--output-dir", "local")

    (ci,) = (tmp_path / "ci").glob("*.json")
    (local,) = (tmp_path / "local").glob("*.json")

    assert json.loads(ci.read_text())["ci"] == RUN_IDENTITY
    assert json.loads(local.read_text())["ci"] is None


def test_a_repository_name_that_looks_like_a_key_keeps_its_ci_identity(
    monkeypatch, capsys, tmp_path
):
    """`sk-…` in a repository name is a name: the result keeps it verbatim, so
    attest names the run and the gate of that repository decides on it."""
    monkeypatch.chdir(tmp_path)
    _config(tmp_path, SELECTION_CONFIG)
    repository = "ringier/aktuality-sk-web"
    with monkeypatch.context() as scoped:
        for variable, value in {**GITHUB, "GITHUB_REPOSITORY": repository}.items():
            scoped.setenv(variable, value)
        _run(monkeypatch, capsys, "benchmark.json", "--output-dir", "results")
        (result,) = (tmp_path / "results").glob("*-selection-*.json")
        code, out, err = _run(monkeypatch, capsys, "attest", result, "--json")
    ran = date.fromisoformat(json.loads(result.read_text())["timestamp"][:10])
    monkeypatch.setattr(cli, "today_utc", lambda: ran)

    assert json.loads(result.read_text())["ci"]["repository"] == repository
    assert (code, json.loads(out)["origin_reason"]) == (0, None), err
    code, report = _gate(
        monkeypatch,
        capsys,
        "--records",
        "results",
        repository=("--repository", repository),
    )
    # The mock answers {} to "Reply with ok.", so the run failed; what
    # matters is that the record counts.
    assert (code, report["reason_code"]) == (1, "failed_record")
    assert report["records"][0]["repository"] == repository


def _forge_selection(record, prompt):
    """Point the evidence annotation at another selection, leaving the seal."""
    required = {
        "prompt": prompt,
        "tests": None,
        "environment": None,
        "migrationCheck": False,
        "smoke": False,
        "repetitions": 1,
    }

    def swap(data):
        _evidence(data)["selectionSha256"] = selection_fingerprint(required)

    _edit_record(record, swap)


def test_gate_rejects_a_selection_hash_swapped_outside_the_seal(
    monkeypatch, capsys, tmp_path
):
    """An edited selectionSha256 is not the selection the run sealed."""
    _config(
        tmp_path,
        {
            **SELECTION_CONFIG,
            "prompts": [
                {**SELECTION_CONFIG["prompts"][0], "name": "sk-alpha"},
                {**SELECTION_CONFIG["prompts"][0], "name": "sk-beta"},
            ],
        },
    )
    record = _selected_run(monkeypatch, capsys, tmp_path, "--prompt", "sk-alpha")
    _forge_selection(record, "sk-beta")

    code, out, _ = _run(monkeypatch, capsys, "verify", record, "--json")
    problems = json.loads(out)["integrity"]["problems"]
    gate_code, report = _gate(
        monkeypatch, capsys, "--records", "results", "--prompt", "sk-beta"
    )

    assert code == 1
    assert "selectionSha256 does not match the sealed selection" in problems
    assert (gate_code, report["decision"], report["reason_code"]) == (
        1,
        "blocked",
        "inconsistent_record",
    )


def test_gate_rejects_a_rewritten_pass_whose_verdict_was_not_sealed(
    monkeypatch, capsys, tmp_path
):
    """A WARNED record rewritten to look like PASSED still fails the seal."""
    _config(
        tmp_path,
        {
            **SELECTION_CONFIG,
            "prompts": [
                {**SELECTION_CONFIG["prompts"][0], "name": "sk-alpha"},
                {**SELECTION_CONFIG["prompts"][0], "name": "sk-beta"},
            ],
        },
    )
    record = _selected_run(monkeypatch, capsys, tmp_path, "--prompt", "sk-alpha")
    _forge_selection(record, "sk-beta")

    def rewrite(data):
        evidence = _evidence(data)
        evidence["decision"]["state"] = "pass"
        evidence["decision"]["blocking_warnings"] = []
        evidence["decision"]["reason_code"] = "benchmark_passed"
        evidence["costConfidence"] = "complete"
        predicate = data["predicate"]
        predicate["result"] = "PASSED"
        predicate["passedTests"] = list(predicate.get("warnedTests") or [])
        predicate["warnedTests"] = []
        predicate["failedTests"] = []

    _edit_record(record, rewrite)
    code, out, _ = _run(monkeypatch, capsys, "verify", record, "--json")
    problems = json.loads(out)["integrity"]["problems"]
    gate_code, report = _gate(
        monkeypatch, capsys, "--records", "results", "--prompt", "sk-beta"
    )

    assert code == 1
    assert "the decision does not match the sealed decision" in problems
    assert "cost confidence does not match the sealed cost confidence" in problems
    assert "selectionSha256 does not match the sealed selection" in problems
    assert (gate_code, report["decision"], report["reason_code"]) == (
        1,
        "blocked",
        "inconsistent_record",
    )


def test_gate_rejects_a_prompt_whose_redacted_name_matches_another(
    monkeypatch, capsys, tmp_path
):
    _config(
        tmp_path,
        {
            **SELECTION_CONFIG,
            "prompts": [
                {**SELECTION_CONFIG["prompts"][0], "name": "sk-alpha"},
                {**SELECTION_CONFIG["prompts"][0], "name": "sk-beta"},
            ],
        },
    )

    _selected_run(monkeypatch, capsys, tmp_path, "--prompt", "sk-alpha")
    code, report = _gate(
        monkeypatch, capsys, "--records", "results", "--prompt", "sk-beta"
    )

    assert (code, report["reason_code"]) == (1, "selection_changed")
    assert "under the same selection" not in report["why"]
    assert "sk-beta" in report["why"]


@pytest.mark.parametrize("flag", ["--prompt", "--tests"])
def test_a_prompt_named_like_a_key_attests_and_matches_its_gate(
    monkeypatch, capsys, tmp_path, flag
):
    _config(
        tmp_path,
        {
            **SELECTION_CONFIG,
            "prompts": [{**SELECTION_CONFIG["prompts"][0], "name": "sk-greeting"}],
        },
    )

    record = _selected_run(monkeypatch, capsys, tmp_path, flag, "sk-greeting")
    code, report = _gate(
        monkeypatch, capsys, "--records", "results", flag, "sk-greeting"
    )

    assert record.exists()
    assert (code, report["reason_code"]) == (1, "inconclusive_record")


@pytest.mark.parametrize(
    ("recorded", "environment", "reason"),
    [
        (
            None,
            GITHUB,
            (
                "the result records no GitHub Actions run identity: it ran "
                "outside GitHub Actions or with llm-preflight before 2.22.0"
            ),
        ),
        (
            {**RUN_IDENTITY, "runId": "1"},
            GITHUB,
            "the result was made in another GitHub Actions run",
        ),
        (
            {**RUN_IDENTITY, "repository": "acme/other"},
            GITHUB,
            "the result was made in another GitHub Actions run",
        ),
        (
            {**RUN_IDENTITY, "commit": "0" * 40},
            GITHUB,
            "the result was made in another GitHub Actions run",
        ),
        (
            RUN_IDENTITY,
            {},
            "it was attested outside the GitHub Actions run that made the result",
        ),
        (
            {"repository": "acme/app"},
            GITHUB,
            "the result's GitHub Actions run identity is malformed",
        ),
    ],
    ids=["none", "other-run", "other-repository", "other-commit", "outside", "bad"],
)
def test_attest_records_local_unless_it_runs_in_the_run_that_made_the_result(
    monkeypatch, capsys, tmp_path, recorded, environment, reason
):
    monkeypatch.chdir(tmp_path)
    _result(tmp_path, _config(tmp_path), ci=recorded)
    with monkeypatch.context() as scoped:
        for variable, value in environment.items():
            scoped.setenv(variable, value)
        code, out, err = _run(monkeypatch, capsys, "attest", "results/run.json")
        _, payload, _ = _run(
            monkeypatch, capsys, "attest", "results/run.json", "--force", "--json"
        )

    assert code == 0, err
    record = json.loads((tmp_path / "results/run.preflight.json").read_text())
    evidence = _descriptor(record, "evidence")["annotations"]
    assert (evidence["origin"], evidence["ci"]) == ("local", None)
    assert "url" not in record["predicate"]
    assert f"origin: local — {reason}; the gate does not accept it" in out
    assert json.loads(payload)["origin_reason"] == reason


# untrusted record content


def _strict(text):
    """The parsed output re-encoded as strict UTF-8 JSON, which SDKs require."""
    return json.dumps(json.loads(text), ensure_ascii=False).encode("utf-8")


@pytest.mark.parametrize(
    "edit",
    [
        lambda data: data["predicate"].update(url="X\udcffY"),
        lambda data: _evidence(data)["ci"].update(repository="acme/a\udcff"),
        lambda data: _evidence(data)["ci"].update(serverUrl="https://\ud800"),
        lambda data: _descriptor(data, "routes")["annotations"]["routes"][0].update(
            provider="open\udcffai", model="gpt\ud800"
        ),
        lambda data: data["subject"][0].update(name="bench\udcffmark.json"),
    ],
    ids=["url", "repository", "server", "route", "subject"],
)
def test_record_strings_that_are_not_unicode_text_reach_every_output_escaped(
    monkeypatch, capsys, tmp_path, edit
):
    record = _attest(monkeypatch, capsys, tmp_path)
    _edit_record(record, edit)

    _, verify_json, _ = _run(monkeypatch, capsys, "verify", record, "--json")
    _, verify_text, _ = _run(monkeypatch, capsys, "verify", record)
    _, gate_json, _ = _run(
        monkeypatch, capsys, "gate", *REPO, "--records", "results", "--json"
    )
    _, gate_text, _ = _run(monkeypatch, capsys, "gate", *REPO, "--records", "results")

    for report in (verify_json, gate_json):
        _strict(report)
    for text in (verify_text, gate_text):
        text.encode("utf-8")
    assert json.loads(gate_json)["reason_code"] == "inconsistent_record"


def test_a_record_file_name_that_is_not_utf_8_reaches_every_output_escaped(
    monkeypatch, capsys, tmp_path
):
    import os

    record = _attest(monkeypatch, capsys, tmp_path)
    hostile = record.with_name(os.fsdecode(b"evil\xff.preflight.json"))
    record.rename(hostile)

    _, verify_json, _ = _run(monkeypatch, capsys, "verify", hostile, "--json")
    _, gate_json, _ = _run(
        monkeypatch, capsys, "gate", *REPO, "--records", "results", "--json"
    )
    code, card, err = _card(monkeypatch, capsys, "--record", hostile)

    assert json.loads(verify_json)["record"].endswith(
        "results/evil\\xff.preflight.json"
    )
    _strict(gate_json)
    assert code == 0, err
    card.encode("utf-8")


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("[" * 200_000, "nested more than"),
        ("[" * 900 + "]" * 900, "nested more than"),
        (json.dumps({"padding": "x" * (1 << 21)}), "larger than"),
    ],
    ids=["unbalanced", "deep", "large"],
)
def test_gate_cannot_decide_on_a_record_nested_too_deeply_or_too_large(
    monkeypatch, capsys, tmp_path, content, reason
):
    _attest(monkeypatch, capsys, tmp_path)
    hostile = tmp_path / "results/hostile.preflight.json"
    hostile.write_text(content)

    code, report = _gate(monkeypatch, capsys, "--records", "results")
    verify_code, _, err = _run(monkeypatch, capsys, "verify", hostile)

    assert (code, report["reason_code"]) == (3, "record_error")
    assert reason in report["why"]
    assert verify_code == 2
    assert f"error: {reason}" in err or reason in err
    assert "Traceback" not in err


@pytest.mark.parametrize(("levels", "refused"), [(64, False), (65, True)])
def test_a_record_may_nest_64_levels_deep_and_no_deeper(tmp_path, levels, refused):
    path = tmp_path / "nested.preflight.json"
    path.write_text("[" * levels + "]" * levels)

    if refused:
        with pytest.raises(ValueError, match="nested more than 64 levels deep"):
            attestation.load_record(path)
    else:
        assert attestation.load_record(path) is not None


# sampling depth


def test_a_smoke_record_satisfies_only_a_gate_that_expects_smoke(
    monkeypatch, capsys, tmp_path
):
    record = _selected_run(monkeypatch, capsys, tmp_path, "--smoke")

    code, report = _gate(monkeypatch, capsys, "--records", "results")
    _, smoke = _gate(monkeypatch, capsys, "--smoke", "--records", "results")

    assert _evidence(json.loads(record.read_text()))["selection"] == {
        **DEFAULT_SELECTION,
        "smoke": True,
        "repetitions": 1,
    }
    assert (code, report["reason_code"]) == (1, "selection_changed")
    assert "ran --smoke (1 repetition per prompt)" in report["why"]
    assert (
        "this gate requires a default run (1 repetition per prompt)" in (report["why"])
    )
    assert smoke["reason_code"] in {"failed_record", "inconclusive_record"}
    assert smoke["selection"] == {**DEFAULT_SELECTION, "smoke": True, "repetitions": 1}


def test_gate_blocks_a_record_that_ran_fewer_repetitions_than_the_config_asks(
    monkeypatch, capsys, tmp_path
):
    _selected_run(monkeypatch, capsys, tmp_path)
    _config(tmp_path, {**SELECTION_CONFIG, "repetitions": 3})

    code, report = _gate(monkeypatch, capsys, "--records", "results")

    assert (code, report["reason_code"]) == (1, "selection_changed")
    assert report["why"] == (
        "The latest record (run 4425592351, checked today) ran a default run "
        "with 1 repetition per prompt; benchmark.json now asks for 3 under "
        "the same selection."
    )


# repository


def test_gate_refuses_a_repository_flag_that_contradicts_github_repository(
    monkeypatch, capsys, tmp_path
):
    _attest(monkeypatch, capsys, tmp_path)
    monkeypatch.setenv("GITHUB_REPOSITORY", "fork/app")

    code, report = _gate(monkeypatch, capsys, "--records", "results")

    assert (code, report["decision"], report["reason_code"]) == (
        3,
        "undecided",
        "repository_unknown",
    )
    assert report["why"] == (
        "The gate cannot tell which repository this tree belongs to: "
        "--repository names acme/app, but GITHUB_REPOSITORY is fork/app."
    )
    assert report["repository"] is None
    assert report["next"] == [
        (
            "drop --repository in GitHub Actions, or give the repository "
            "GITHUB_REPOSITORY names"
        )
    ]


# card


def _card(monkeypatch, capsys, *arguments):
    return _run(
        monkeypatch, capsys, "report", "results/run.json", "--format", "svg", *arguments
    )


def test_card_with_a_fresh_record_shows_valid_until_and_the_verify_command(
    monkeypatch, capsys, tmp_path
):
    _attest(monkeypatch, capsys, tmp_path)
    evidence = json.loads((tmp_path / "results/run.json").read_text())["provenance"]

    code, out, err = _card(
        monkeypatch, capsys, "--record", "results/run.preflight.json"
    )

    assert code == 0, err
    assert ">PASS<" in out and ">EXPIRED<" not in out
    assert "2026-11-09" in out and ">Valid until<" in out
    assert "llm-preflight verify run.preflight.json" in out
    # The result's digest, labelled so it is not read as the record's own
    # evidence digest, which also seals the selection hash and the verdict.
    assert f"result evidence {evidence['evidence_sha256'][:12]}" in out
    record = json.loads((tmp_path / "results/run.preflight.json").read_text())
    sealed = _descriptor(record, "evidence")["digest"]["sha256"]
    assert sealed != evidence["evidence_sha256"]
    assert "Not attested" not in out


def test_card_for_a_stale_record_is_expired_and_matches_its_golden_file(
    monkeypatch, capsys, tmp_path
):
    _attest(monkeypatch, capsys, tmp_path)
    monkeypatch.setattr(cli, "today_utc", lambda: date(2026, 11, 10))

    code, out, err = _card(
        monkeypatch, capsys, "--record", "results/run.preflight.json"
    )

    assert code == 0, err
    golden = Path(__file__).parent / "fixtures/cards/expired.svg"
    assert out == golden.read_text(encoding="utf-8")


def test_card_for_a_superseded_record_is_expired(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "today_utc", lambda: date(2027, 1, 15))
    _attest(monkeypatch, capsys, tmp_path, timestamp="2027-01-10T08:00:00Z")

    code, out, _ = _card(monkeypatch, capsys, "--record", "results/run.preflight.json")

    assert code == 0
    assert ">EXPIRED<" in out and "was PASS" in out
    assert "a checked route has since retired" in out
    assert "retired on 2027-01-14" in out


def test_card_refuses_a_record_of_another_result_or_a_broken_record(
    monkeypatch, capsys, tmp_path
):
    _attest(monkeypatch, capsys, tmp_path)
    other = _attest(
        monkeypatch,
        capsys,
        tmp_path,
        timestamp="2026-10-11T08:00:00+00:00",
        name="other.json",
    )

    code, out, err = _card(monkeypatch, capsys, "--record", other)

    assert (code, out) == (2, "")
    assert "does not attest results/run.json" in err

    record = tmp_path / "results/run.preflight.json"
    _edit_record(record, lambda r: r["predicate"].update(result="FAILED"))
    code, out, err = _card(monkeypatch, capsys, "--record", record)

    assert (code, out) == (2, "")
    assert "fails its integrity check" in err
    assert "llm-preflight verify" in err


def test_card_names_the_repository_that_recorded_it(monkeypatch, capsys, tmp_path):
    _attest(monkeypatch, capsys, tmp_path)
    _, ci, _ = _card(monkeypatch, capsys, "--record", "results/run.preflight.json")
    _attest(monkeypatch, capsys, tmp_path, ci=False, name="local.json")
    _, local, _ = _run(
        monkeypatch,
        capsys,
        "report",
        "results/local.json",
        "--format",
        "svg",
        "--record",
        "results/local.preflight.json",
    )
    _, unattested, _ = _card(monkeypatch, capsys)

    assert ">Repository<" in ci and "acme/app on https://github.com" in ci
    assert ">Repository<" in local
    assert "none — a local record, which the gate never accepts" in local
    assert ">Repository<" not in unattested


@pytest.mark.parametrize("payload", INJECTIONS, ids=["ansi", "newline", "return"])
def test_card_shows_record_strings_escaped_never_raw(
    monkeypatch, capsys, tmp_path, payload
):
    record = _attest(monkeypatch, capsys, tmp_path)
    hostile = tmp_path / f"results/evil{payload}x.preflight.json"
    hostile.write_text(record.read_text())

    code, out, err = _card(monkeypatch, capsys, "--record", hostile)

    assert code == 0, err
    assert f"llm-preflight verify evil{ESCAPED[payload]}x.preflight.json" in out
    assert f"evil{payload}x" not in out

    _edit_record(
        hostile,
        lambda r: r["subject"][1].update(name=f"results/run{payload}x.json"),
    )
    code, _, err = _card(monkeypatch, capsys, "--record", hostile)

    assert code == 2
    assert f"evil{ESCAPED[payload]}x.preflight.json fails its integrity" in err
    assert _no_raw_control_characters(err.rstrip("\n")), err


def test_card_record_needs_the_svg_format_and_output_writes_a_file(
    monkeypatch, capsys, tmp_path
):
    _attest(monkeypatch, capsys, tmp_path)

    code, _, err = _run(
        monkeypatch,
        capsys,
        "report",
        "results/run.json",
        "--record",
        "results/run.preflight.json",
    )
    assert code == 2
    assert "--record needs --format svg" in err

    code, out, _ = _card(monkeypatch, capsys, "--output", "card.svg")
    assert code == 0
    assert out == "Saved svg report to card.svg\n"
    assert (tmp_path / "card.svg").read_text(encoding="utf-8").startswith("<svg ")
