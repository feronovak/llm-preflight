"""Proof-of-preflight records: attest a saved result, verify a record, gate a tree.

A record is an in-toto Statement v1 carrying the test-result v0.1 predicate;
its subjects and configuration entries are ResourceDescriptors:
https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md
https://github.com/in-toto/attestation/blob/main/spec/predicates/test-result.md
https://github.com/in-toto/attestation/blob/main/spec/v1/resource_descriptor.md

A record proves that a named check ran on a contract and its routes; it never
certifies production behaviour. Nothing here signs a record or checks a
signature: signing stays outside the package (actions/attest, verified with
gh attestation verify).
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shlex

# Only CalledProcessError is used; run_git starts Git.
import subprocess  # nosec B404
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .catalog import resolve_models
from .client import observed_model, reported_model
from .contracts import _fingerprint, provenance
from .features import (
    apply_environment,
    apply_migration_check,
    apply_model_aliases,
    apply_provider_presets,
)
from .git import run_git
from .pricing import resolve_pricing
from .redaction import redact_secrets
from .retirements import retirement_verdict, snapshot_summary
from .runner import (
    load_config,
    model_failed,
    select_custom_prompt,
    select_test_profiles,
    validate_config_validations,
)
from .source_audit import display_path

STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://in-toto.io/attestation/test-result/v0.1"
RECORD_SUFFIX = ".preflight.json"
DEFAULT_MAX_AGE_DAYS = 30
SIGNATURE_NOTE = "not checked here — use gh attestation verify"
CLAIMS_NOT_MADE = (
    "production behaviour",
    "accuracy beyond the declared validators",
    "safety",
    "other accounts or regions",
)
# The decision is copied, never recomputed: inconclusive stays WARNED. Bandit
# B105 misreads the "pass" key as a hard-coded password; without the
# suppression, `make audit` fails.
_RESULTS = {"pass": "PASSED", "inconclusive": "WARNED", "fail": "FAILED"}  # nosec B105
_FINGERPRINTS = ("contract", "routes", "pricing", "evidence")
_TEST_FIELDS = ("passedTests", "warnedTests", "failedTests")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GITHUB_VARIABLES = (
    ("GITHUB_REPOSITORY", "repository"),
    ("GITHUB_WORKFLOW", "workflow"),
    ("GITHUB_RUN_ID", "runId"),
    ("GITHUB_RUN_ATTEMPT", "runAttempt"),
    ("GITHUB_SHA", "commit"),
    ("GITHUB_SERVER_URL", "serverUrl"),
)
_CI_FIELDS = {
    "repository": re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"),
    "runId": re.compile(r"[1-9][0-9]{0,19}"),
    "runAttempt": re.compile(r"[1-9][0-9]{0,5}"),
    "commit": re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}"),
    "serverUrl": re.compile(r"https://[A-Za-z0-9.-]+(:[0-9]{1,5})?"),
}
_MAX_WORKFLOW_LENGTH = 200
# The run flags that shape the config a run fingerprints; names only, so a
# record never carries a credential or an env-file path.
DEFAULT_SELECTION: dict[str, Any] = {
    "prompt": None,
    "tests": None,
    "environment": None,
    "migrationCheck": False,
}
_MAX_SELECTION_LENGTH = 200
_MAX_ROUTE_NAME_LENGTH = 256
# A gate decides on the newest of these; every other verdict cannot count.
_CANDIDATE_VERDICTS = {
    "pass",
    "failed_record",
    "inconclusive_record",
    "superseded",
    "stale",
}
# With no candidate, the first verdict present here explains the block.
_BLOCKING_PRIORITY = (
    "committed_record",
    "local_record",
    "inconsistent_record",
    "selection_changed",
    "contract_changed",
    "routes_changed",
)
_ATTEST_NEXT = "llm-preflight attest results/<new>.json   (CI does this for you)"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def default_record_path(result_path: Path) -> Path:
    """`results/run.json` is attested to `results/run.preflight.json`."""
    return result_path.with_suffix(RECORD_SUFFIX)


def ci_identity(environ: Mapping[str, str]) -> dict[str, str] | None:
    """The GitHub Actions run identity, or None outside CI.

    A partial or malformed identity is refused rather than recorded as local,
    so a misconfigured workflow cannot silently produce a record the gate
    ignores.
    """
    values = {key: environ.get(name, "") for name, key in _GITHUB_VARIABLES}
    if not any(values.values()):
        return None
    missing = [name for name, key in _GITHUB_VARIABLES if not values[key]]
    if missing:
        raise ValueError(
            f"incomplete GitHub Actions identity: {', '.join(missing)} not set; "
            "unset every GITHUB_* run variable to attest a local record"
        )
    malformed = [
        name for name, key in _GITHUB_VARIABLES if not _valid_ci_field(key, values[key])
    ]
    if malformed:
        raise ValueError(f"malformed GitHub Actions identity: {', '.join(malformed)}")
    return values


def run_url(ci: Mapping[str, str]) -> str:
    return (
        f"{ci['serverUrl']}/{ci['repository']}/actions/runs/"
        f"{ci['runId']}/attempts/{ci['runAttempt']}"
    )


def attest_result(
    result_path: Path,
    *,
    config_path: Path | None,
    environ: Mapping[str, str],
    today: date,
) -> dict[str, Any]:
    """Read a saved result and its config, and return the record for them."""
    result_bytes = result_path.read_bytes()
    result = json.loads(result_bytes.decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError("result must be a JSON object")  # noqa: TRY004
    if config_path is None:
        source = result.get("source_config_path")
        if not isinstance(source, str) or not source:
            raise ValueError(
                "result does not record its config path; pass --config CONFIG"
            )
        config_path = Path(source)
    return build_record(
        result,
        result_name=_subject_name(result_path),
        result_digest=hashlib.sha256(result_bytes).hexdigest(),
        config_name=_subject_name(config_path),
        config_digest=_file_sha256(config_path),
        ci=ci_identity(environ),
        today=today,
    )


def build_record(
    result: dict[str, Any],
    *,
    result_name: str,
    result_digest: str,
    config_name: str,
    config_digest: str,
    ci: Mapping[str, str] | None,
    today: date,
) -> dict[str, Any]:
    """Map a saved result onto the test-result predicate without changing its decision."""
    evidence = result.get("provenance")
    if (
        result.get("schema_version") != 1
        or not isinstance(evidence, dict)
        or evidence.get("schema_version") != 1
    ):
        raise ValueError(
            "result has no schema-version-1 provenance; "
            "run the check with a current llm-preflight and attest that result"
        )
    problems = _provenance_problems(evidence)
    if problems:
        raise ValueError(f"result cannot be attested: {'; '.join(problems)}")
    decision = result.get("decision")
    if not isinstance(decision, dict) or decision.get("state") not in _RESULTS:
        raise ValueError(
            "result has no pass, inconclusive or fail decision; "
            "run the check with a current llm-preflight and attest that result"
        )
    try:
        passed, warned, failed = _test_outcomes(result, decision["state"])
        routes = _routes(result)
        requests = _request_count(result)
    except (AttributeError, KeyError, TypeError) as exc:
        raise ValueError("result models are malformed; cannot attest it") from exc
    predicate: dict[str, Any] = {
        "result": _RESULTS[decision["state"]],
        "configuration": [
            _descriptor(
                "contract",
                evidence["contract_sha256"],
                {"validatorVersion": evidence.get("validator_version")},
            ),
            _descriptor("routes", evidence["routes_sha256"], {"routes": routes}),
            _descriptor("pricing", evidence["pricing_sha256"]),
            _descriptor(
                "evidence",
                evidence["evidence_sha256"],
                {
                    "checkedAt": result.get("timestamp"),
                    "runId": result.get("run_id"),
                    # The safe next command names the local config path.
                    "decision": {
                        key: copy.deepcopy(value)
                        for key, value in decision.items()
                        if key != "safe_next_command"
                    },
                    "provenance": copy.deepcopy(evidence),
                    "requests": requests,
                    "selection": _result_selection(result),
                    "costUsd": result.get("total_estimated_cost_usd"),
                    "costConfidence": result.get("cost_confidence"),
                    "retirementSnapshot": snapshot_summary()["newest_as_of"],
                    "claimsNotMade": list(CLAIMS_NOT_MADE),
                    "origin": "github-actions" if ci else "local",
                    "ci": dict(ci) if ci else None,
                    "attestedBy": f"llm-preflight {__version__}",
                },
            ),
        ],
    }
    if ci:
        predicate["url"] = run_url(ci)
    predicate.update(passedTests=passed, warnedTests=warned, failedTests=failed)
    record = {
        "_type": STATEMENT_TYPE,
        "subject": [
            {
                "name": config_name,
                "digest": {"sha256": config_digest},
                "annotations": {"role": "config"},
            },
            {
                "name": result_name,
                "digest": {"sha256": result_digest},
                "annotations": {"role": "result"},
            },
        ],
        "predicateType": PREDICATE_TYPE,
        "predicate": predicate,
    }
    problems = integrity_problems(record, today)
    if problems:
        # Refuse rather than write a record that verify and gate would reject.
        raise ValueError(f"result cannot be attested: {'; '.join(problems)}")
    return record


def load_record(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def integrity_problems(record: Any, today: date) -> list[str]:
    """Shape, predicate type and internal consistency; files are checked separately."""
    if not isinstance(record, dict):
        return ["the record is not a JSON object"]
    problems = []
    if record.get("_type") != STATEMENT_TYPE:
        problems.append("_type is not an in-toto Statement v1")
    if record.get("predicateType") != PREDICATE_TYPE:
        problems.append("predicateType is not the in-toto test-result v0.1 predicate")
    problems.extend(_subject_problems(record.get("subject")))
    predicate = record.get("predicate")
    if not isinstance(predicate, dict):
        return [*problems, "predicate is not an object"]
    result = predicate.get("result")
    if result not in _RESULTS.values():
        problems.append("predicate.result is not PASSED, WARNED or FAILED")
    tests = {field: predicate.get(field, []) for field in _TEST_FIELDS}
    for field, names in tests.items():
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            problems.append(f"predicate.{field} is not a list of test names")
            tests[field] = []
    descriptors = _descriptors(predicate.get("configuration"))
    missing = [name for name in _FINGERPRINTS if name not in descriptors]
    if missing:
        names = ", ".join(f"llm-preflight/{name}" for name in missing)
        return [*problems, f"predicate.configuration lacks {names}"]
    for name in _FINGERPRINTS:
        if not _is_sha256(_digest(descriptors[name])):
            problems.append(f"llm-preflight/{name} has no SHA-256 digest")
    evidence = descriptors["evidence"].get("annotations")
    if not isinstance(evidence, dict):
        return [*problems, "llm-preflight/evidence has no annotations"]
    routes = _routes_annotation(descriptors["routes"])
    if routes is None:
        problems.append("llm-preflight/routes does not list provider and model")
    else:
        if not all(
            _valid_route_name(route["provider"]) and _valid_route_name(route["model"])
            for route in routes
        ):
            problems.append(
                "llm-preflight/routes carries a malformed provider or model"
            )
        if not all(_valid_observed(route.get("observedModel")) for route in routes):
            problems.append("llm-preflight/routes carries a malformed observedModel")
    fingerprints = evidence.get("provenance")
    if not isinstance(fingerprints, dict) or fingerprints.get("schema_version") != 1:
        problems.append("the evidence carries no schema-version-1 provenance")
    else:
        problems.extend(_provenance_problems(fingerprints))
        problems.extend(
            f"llm-preflight/{name} digest does not match provenance.{name}_sha256"
            for name in _FINGERPRINTS
            if _digest(descriptors[name]) != fingerprints.get(f"{name}_sha256")
        )
    if not _valid_selection(evidence.get("selection")):
        problems.append("llm-preflight/evidence carries a malformed selection")
    checked = _timestamp(evidence.get("checkedAt"))
    if checked is None:
        problems.append("checkedAt is not a timezone-qualified ISO-8601 timestamp")
    elif checked.date() > today:
        problems.append(f"checkedAt is after today's date ({today.isoformat()})")
    decision = evidence.get("decision")
    state = decision.get("state") if isinstance(decision, dict) else None
    if state not in _RESULTS:
        problems.append("the evidence carries no pass, inconclusive or fail decision")
    elif result in _RESULTS.values() and _RESULTS[state] != result:
        problems.append(f"{result} does not match the {state} decision")
    if result == "PASSED":
        if evidence.get("costConfidence") != "complete":
            problems.append("a PASSED record needs complete cost confidence")
        if isinstance(decision, dict) and decision.get("blocking_warnings") != []:
            problems.append("a PASSED record cannot carry blocking warnings")
        if tests["failedTests"] or tests["warnedTests"]:
            problems.append("a PASSED record cannot list failed or warned tests")
        if not tests["passedTests"]:
            problems.append("a PASSED record must list the tests that passed")
    problems.extend(_origin_problems(evidence, predicate))
    return problems


def verify_record(
    record: Any,
    record_path: Path,
    today: date,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    routes: Sequence[Mapping[str, Any]] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Report integrity and freshness separately; they are never merged.

    `routes` overrides the record's own route list for the retirement check;
    the gate passes the routes it resolved from the current config. `root`
    (default: the working directory) is where subject names are looked up;
    when given, a subject file that resolves outside it is not read.
    """
    problems = integrity_problems(record, today)
    subjects = _subject_checks(record, record_path, root)
    problems.extend(
        f"the result file {subject['name']} does not match its subject digest"
        for subject in subjects
        if subject["role"] == "result" and subject["state"] == "differs"
    )
    predicate = record.get("predicate") if isinstance(record, dict) else None
    predicate = predicate if isinstance(predicate, dict) else {}
    descriptors = _descriptors(predicate.get("configuration"))
    evidence = _annotations(descriptors.get("evidence"))
    recorded = _routes_annotation(descriptors.get("routes")) or []
    if routes is None:
        routes = recorded
    origin = evidence.get("origin")
    url = predicate.get("url")
    return {
        "record": display_path(record_path),
        "result": predicate.get("result")
        if predicate.get("result") in _RESULTS.values()
        else None,
        "integrity": {"ok": not problems, "problems": problems, "subjects": subjects},
        "routes": _checked_routes(recorded),
        "freshness": _freshness(
            _timestamp(evidence.get("checkedAt")), routes, today, max_age_days
        ),
        "retirement_snapshot": snapshot_summary()["newest_as_of"],
        "origin": origin if origin in {"github-actions", "local"} else None,
        "url": url if isinstance(url, str) else None,
        "signature": SIGNATURE_NOTE,
    }


def printable(text: str) -> str:
    """Text safe for a terminal or CI log: a record is untrusted input, so every
    non-printable character, a newline or an escape sequence included, is
    shown as its backslash escape instead of being emitted."""
    return "".join(
        char if char.isprintable() else char.encode("unicode_escape").decode("ascii")
        for char in text
    )


def describe_route(route: Mapping[str, Any]) -> str:
    """`provider:model` and the model its provider reported answering, if any."""
    label = printable(f"{route['provider']}:{route['model']}")
    observed = route["observed_model"]
    if observed is None:
        return f"{label} did not report the model that answered"
    if isinstance(observed, list):
        models = printable(", ".join(observed))
        return f"{label} answered as {models} (responses disagreed)"
    return f"{label} answered as {printable(observed)}"


def current_fingerprints(
    config_path: Path, selection: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """The contract and route fingerprints a run of this config records.

    It resolves the config exactly as a run under `selection` (`--env`,
    `--migration-check`, `--prompt`, `--tests`; default: none) does before
    `provenance`, without loading credentials or contacting a provider.
    """
    selection = {**DEFAULT_SELECTION, **(selection or {})}
    config = load_config(config_path)
    config["_source_config_path"] = str(config_path.resolve())
    config = apply_environment(config, selection["environment"])
    config = apply_provider_presets(apply_model_aliases(config))
    validate_config_validations(config)
    if config.get("discovery"):
        raise ValueError(
            "its routes come from provider catalogue discovery, which needs the "
            "network; list them under models so the offline gate can fingerprint them"
        )
    if selection["migrationCheck"]:
        config = apply_migration_check(config)
    if selection["prompt"]:
        config = select_custom_prompt(config, selection["prompt"])
    if selection["tests"]:
        # Tests change no fingerprint, but an unknown test is a config error.
        select_test_profiles(config, selection["tests"])
    models = resolve_pricing(resolve_models(config))["models"]
    fingerprints = provenance(config, models, "")
    return {
        "contract_sha256": fingerprints["contract_sha256"],
        "routes_sha256": fingerprints["routes_sha256"],
        "routes": [
            {
                "provider": model.get("provider", "openai_compatible"),
                "model": model["model"],
            }
            for model in models
        ],
    }


def gate(
    config_path: Path,
    record_paths: Sequence[Path],
    today: date,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    selection: Mapping[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Decide offline whether the current tree has a fresh passing record.

    Pass only on the newest CI record that ran the gate's `selection`
    (default: a default run), matches the current contract and routes under
    it, is PASSED, consistent, fresh and not superseded. The gate, not the
    record, sets the selection: a record cannot lower the bar by having run
    less. A record that cannot be read makes the gate unable to decide: it
    might be the newest. With `root`, as for the MCP workspace, a record or
    subject file that resolves outside it is never read.
    """
    config = display_path(config_path)
    required = {**DEFAULT_SELECTION, **(selection or {})}
    report: dict[str, Any] = {
        "config": config,
        "selection": required,
        "contract_sha256": None,
        "routes_sha256": None,
        "max_age_days": max_age_days,
        "retirement_snapshot": snapshot_summary()["newest_as_of"],
        "signature": SIGNATURE_NOTE,
        "network_accessed": False,
        "records": [],
    }
    try:
        current = current_fingerprints(config_path, required)
    except (OSError, ValueError) as exc:
        reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else exc
        return _undecided_config(report, config, reason)
    except (AttributeError, KeyError, TypeError):
        return _undecided_config(report, config, "it is not a benchmark configuration")
    report["contract_sha256"] = current["contract_sha256"]
    report["routes_sha256"] = current["routes_sha256"]
    entries = [
        _evaluate(path, current, required, today, max_age_days, root)
        if error is None
        else _entry(path, "record_error", error)
        for path, error in _record_files(record_paths, root)
    ]
    report["records"] = [
        {key: value for key, value in entry.items() if not key.startswith("_")}
        for entry in entries
    ]
    unreadable = next((e for e in entries if e["verdict"] == "record_error"), None)
    if unreadable is not None:
        return {
            "decision": "undecided",
            "reason_code": "record_error",
            "why": (
                f"{unreadable['path']} cannot be checked: {unreadable['reason']}. "
                "The gate cannot decide without every record it was given."
            ),
            "next": [
                (
                    f"check that {unreadable['path']} is a record written by "
                    "llm-preflight attest, or leave it out of --records"
                ),
            ],
            **report,
        }
    candidates = [e for e in entries if e["verdict"] in _CANDIDATE_VERDICTS]
    if candidates:
        # On a tie the non-passing record wins: equal age cannot hide a failure.
        newest = max(candidates, key=lambda e: (e["_checked"], e["verdict"] != "pass"))
        code = "fresh_pass" if newest["verdict"] == "pass" else newest["verdict"]
    else:
        code, newest = "no_record", None
        for verdict in _BLOCKING_PRIORITY:
            matching = [e for e in entries if e["verdict"] == verdict]
            if matching:
                code = verdict
                newest = max(matching, key=lambda e: e["_checked"] or _EPOCH)
                break
    why, steps = _explain(
        code, newest, config, current, required, record_paths, max_age_days
    )
    return {
        "decision": "pass" if code == "fresh_pass" else "blocked",
        "reason_code": code,
        "why": why,
        "next": steps,
        **report,
    }


def _undecided_config(
    report: dict[str, Any], config: str, reason: object
) -> dict[str, Any]:
    return {
        "decision": "undecided",
        "reason_code": "config_error",
        "why": redact_secrets(f"The gate cannot fingerprint {config}: {reason}."),
        "next": [
            f"llm-preflight {_quote(config)} --doctor   (free: config and model resolution)",
            "fix the config or the gate's selection, then rerun the gate",
        ],
        **report,
    }


def _evaluate(
    path: Path,
    current: Mapping[str, Any],
    required: Mapping[str, Any],
    today: date,
    max_age_days: int,
    root: Path | None,
) -> dict[str, Any]:
    try:
        tracked = _tracked_by_git(path)
    except (OSError, ValueError) as exc:
        return _entry(
            path, "record_error", f"Git cannot tell whether it is tracked ({exc})"
        )
    if tracked:
        return _entry(path, "committed_record", "tracked by Git")
    try:
        record = load_record(path)
    except (OSError, ValueError) as exc:
        return _entry(path, "record_error", _read_error(exc))
    report = verify_record(record, path, today, max_age_days, current["routes"], root)
    if not report["integrity"]["ok"]:
        return _entry(path, "inconsistent_record", report["integrity"]["problems"][0])
    descriptors = _descriptors(record["predicate"]["configuration"])
    evidence = descriptors["evidence"]["annotations"]
    freshness = report["freshness"]
    entry = _entry(path, "pass", "fresh, passing CI record for this contract")
    entry.update(
        result=report["result"],
        origin=report["origin"],
        run_id=(evidence.get("ci") or {}).get("runId"),
        repository=(evidence.get("ci") or {}).get("repository"),
        checked_at=freshness["checked_at"],
        age_days=freshness["age_days"],
        valid_until=freshness["valid_until"],
        tests={
            field.removesuffix("Tests"): len(record["predicate"].get(field, []))
            for field in _TEST_FIELDS
        },
        blocking_warnings=len(evidence["decision"].get("blocking_warnings") or []),
        retired_routes=freshness["retired_routes"],
        routes=report["routes"],
        selection=evidence.get("selection"),
        contract_sha256=_digest(descriptors["contract"]),
        routes_sha256=_digest(descriptors["routes"]),
        _checked=_timestamp(evidence["checkedAt"]),
    )
    for verdict, reason, applies in (
        (
            "selection_changed",
            "does not record its selection"
            if entry["selection"] is None
            else "ran a different selection",
            entry["selection"] != required,
        ),
        (
            "contract_changed",
            "checked a different contract",
            entry["contract_sha256"] != current["contract_sha256"],
        ),
        (
            "routes_changed",
            "checked different routes",
            entry["routes_sha256"] != current["routes_sha256"],
        ),
        ("local_record", "no CI run identity", report["origin"] != "github-actions"),
        ("failed_record", "the run failed", report["result"] == "FAILED"),
        (
            "inconclusive_record",
            "the run was inconclusive",
            report["result"] == "WARNED",
        ),
        (
            "superseded",
            "a checked route has since retired",
            freshness["state"] == "superseded",
        ),
        ("stale", f"older than {max_age_days} days", freshness["state"] == "stale"),
    ):
        if applies:
            entry.update(verdict=verdict, reason=reason)
            break
    return entry


def _entry(path: Path, verdict: str, reason: str) -> dict[str, Any]:
    """One record's verdict; fields the gate could not read stay null."""
    return {
        "path": display_path(path),
        "verdict": verdict,
        "reason": redact_secrets(reason),
        "result": None,
        "origin": None,
        "run_id": None,
        "repository": None,
        "checked_at": None,
        "age_days": None,
        "valid_until": None,
        "tests": None,
        "blocking_warnings": None,
        "retired_routes": [],
        "routes": [],
        "selection": None,
        "contract_sha256": None,
        "routes_sha256": None,
        "_checked": None,
    }


def _explain(
    code: str,
    newest: dict[str, Any] | None,
    config: str,
    current: Mapping[str, Any],
    required: Mapping[str, Any],
    record_paths: Sequence[Path],
    max_age_days: int,
) -> tuple[str, list[str]]:
    """The why and the numbered next steps for a gate decision."""
    run = " ".join([_quote(config), *selection_flags(required)])
    fresh_check = [
        f"llm-preflight {run} --dry-run   (free: plan and cost)",
        "approve the plan, then run the bounded check",
        _ATTEST_NEXT,
    ]
    if code == "no_record" or newest is None:
        searched = ", ".join(display_path(path) for path in record_paths)
        return f"No preflight record was found in {searched}.", fresh_check
    record = newest["path"]
    described = _described(newest)
    latest = f"The latest record for this contract ({described})"
    if code == "fresh_pass":
        return (
            (
                f"Run {newest['run_id']} on {newest['repository']} passed this "
                f"contract and its routes on {newest['checked_at'][:10]} "
                f"({_age(newest['age_days'])}); it stays fresh until "
                f"{newest['valid_until']}. "
                + "".join(f"{describe_route(route)}. " for route in newest["routes"])
                + f"The signature is {SIGNATURE_NOTE}."
            ),
            [],
        )
    if code == "selection_changed":
        requires = describe_selection(required)
        if newest["selection"] is None:
            return (
                (
                    f"{latest} does not record which selection it ran (it was "
                    "attested from a result written before 2.22.0), so it cannot "
                    f"show that it ran what this gate requires: {requires}."
                ),
                fresh_check,
            )
        ran = describe_selection(newest["selection"])
        return (
            f"The latest record ({described}) ran {ran}; this gate requires {requires}.",
            [
                *fresh_check,
                f"if CI runs {ran} on purpose, give the gate the same selection",
            ],
        )
    if code == "contract_changed":
        return (
            (
                f"{config} changed (contract {_short(newest['contract_sha256'])} → "
                f"{_short(current['contract_sha256'])}). The latest record "
                f"({described}) checked a different contract."
            ),
            fresh_check,
        )
    if code == "routes_changed":
        return (
            (
                f"The routes in {config} changed (routes "
                f"{_short(newest['routes_sha256'])} → "
                f"{_short(current['routes_sha256'])}). The latest record "
                f"({described}) checked different routes."
            ),
            fresh_check,
        )
    if code == "stale":
        return (
            (
                f"{latest} is older than the {max_age_days} days allowed; it was "
                f"fresh until {newest['valid_until']}."
            ),
            fresh_check,
        )
    if code == "superseded":
        retired = ", ".join(
            f"{route['provider']}:{route['model']} "
            + (
                f"(retired on {route['retirement_date']})"
                if route["retirement_date"]
                else "(listed as retired)"
            )
            for route in newest["retired_routes"]
        )
        return (
            (
                f"{latest} checked {retired}, per this verifier's retirement "
                f"snapshot of {snapshot_summary()['newest_as_of']}."
            ),
            [
                (
                    f"llm-preflight {run} --dry-run   "
                    "(free: retirement verdict, replacement and cost)"
                ),
                (
                    "move each retired route to a current model, approve the "
                    "plan, then run the bounded check"
                ),
                _ATTEST_NEXT,
            ],
        )
    if code == "failed_record":
        tests = newest["tests"]
        return (
            (
                f"{latest} is FAILED: {tests['failed']} of {sum(tests.values())} "
                "tests failed."
            ),
            [
                f"llm-preflight verify {_quote(record)}   (free: the failed tests)",
                (
                    "fix the contract or the route, approve a fresh plan, then run "
                    "the bounded check"
                ),
                _ATTEST_NEXT,
            ],
        )
    if code == "inconclusive_record":
        warnings = _counted(newest["blocking_warnings"], "blocking warning")
        return (
            (
                f"{latest} is WARNED: the run was inconclusive with {warnings}, "
                "and an inconclusive run never passes the gate."
            ),
            [
                f"llm-preflight verify {_quote(record)}   (free: the blocking warnings)",
                (
                    "resolve each blocking warning, approve a fresh plan, then run "
                    "the bounded check"
                ),
                _ATTEST_NEXT,
            ],
        )
    if code == "inconsistent_record":
        return (
            f"{record} fails its integrity check: {newest['reason']}.",
            [
                (
                    f"llm-preflight verify {_quote(record)}   "
                    "(free: every integrity problem)"
                ),
                (
                    "discard the record; attest the saved result again or run a "
                    "fresh bounded check"
                ),
                _ATTEST_NEXT,
            ],
        )
    if code == "committed_record":
        return (
            (
                f"{record} is tracked by Git. A committed record can be "
                "hand-typed, so the gate never accepts one."
            ),
            [
                f"git rm --cached {_quote(record)}",
                f"keep records out of Git: add *{RECORD_SUFFIX} to .gitignore",
                "let CI attest each run and upload the record as an artifact",
            ],
        )
    return (
        (f"{latest} has no CI run identity. A local record never passes the gate."),
        [
            "run the bounded check in CI",
            _ATTEST_NEXT,
            (
                "download the record, then rerun: "
                f"llm-preflight gate {run} --records DIR"
            ),
        ],
    )


def selection_flags(selection: Mapping[str, Any]) -> list[str]:
    """The run flags that reproduce a selection, in the order the CLI applies them."""
    flags = []
    if selection.get("environment"):
        flags += ["--env", _quote(selection["environment"])]
    if selection.get("migrationCheck"):
        flags.append("--migration-check")
    if selection.get("prompt"):
        flags += ["--prompt", _quote(selection["prompt"])]
    if selection.get("tests"):
        flags += ["--tests", _quote(selection["tests"])]
    return flags


def describe_selection(selection: Mapping[str, Any]) -> str:
    return " ".join(selection_flags(selection)) or "a default run"


def _described(entry: Mapping[str, Any]) -> str:
    run = f"run {entry['run_id']}" if entry.get("run_id") else "a local run"
    if entry.get("age_days") is None:
        return run
    return f"{run}, {_age(entry['age_days'])}"


def _age(days: int) -> str:
    if days == 0:
        return "checked today"
    return f"{_counted(days, 'day')} old"


def _counted(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _short(digest: str | None) -> str:
    return f"{(digest or '?')[:8]}…"


def _quote(text: str) -> str:
    return shlex.quote(text)


def _record_files(
    paths: Iterable[Path], root: Path | None = None
) -> list[tuple[Path, str | None]]:
    """Each record file once; a directory contributes its *.preflight.json files.

    With `root`, a file that resolves outside it, through a symbolic link, is
    reported instead of read.
    """
    found: list[tuple[Path, str | None]] = []
    seen: set[Path] = set()
    for path in paths:
        if path.is_dir():
            files = sorted(
                item for item in path.rglob(f"*{RECORD_SUFFIX}") if item.is_file()
            )
        elif path.is_file():
            files = [path]
        else:
            found.append((path, "it does not exist or is not a file"))
            continue
        for item in files:
            resolved = item.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if root is not None and not _within(resolved, root):
                found.append((item, "it resolves outside the MCP workspace"))
            else:
                found.append((item, None))
    return found


def _within(path: Path, root: Path) -> bool:
    root = root.resolve()
    return path == root or root in path.parents


def _tracked_by_git(path: Path) -> bool:
    """Whether Git tracks the record, following a symbolic link to its target.

    A path outside every work tree is untracked. Inside one, a Git failure is
    raised: the gate cannot tell a committed record from a fresh artifact.
    """
    resolved = path.resolve()
    if not any((parent / ".git").exists() for parent in resolved.parents):
        return False
    try:
        listed = run_git(
            resolved.parent, "ls-files", "-z", "--", f":(literal){resolved.name}"
        )
    except FileNotFoundError as exc:
        raise OSError("git is not installed") from exc
    except subprocess.CalledProcessError as exc:
        raise OSError(f"git exited with status {exc.returncode}") from exc
    return bool(listed.stdout.strip("\0"))


def _freshness(
    checked: datetime | None,
    routes: Sequence[Mapping[str, Any]],
    today: date,
    max_age_days: int,
) -> dict[str, Any]:
    retired = []
    for route in routes:
        verdict = retirement_verdict(route.get("provider"), str(route["model"]), today)
        if verdict["status"] == "retired":
            retired.append(
                {
                    "provider": route.get("provider"),
                    "model": route["model"],
                    "retirement_date": verdict.get("retirement_date"),
                }
            )
    if checked is None or checked.date() > today:
        return {
            "state": "unknown",
            "checked_at": None,
            "age_days": None,
            "max_age_days": max_age_days,
            "valid_until": None,
            "retired_routes": retired,
        }
    age_days = (today - checked.date()).days
    state = "superseded" if retired else "stale" if age_days > max_age_days else "fresh"
    return {
        "state": state,
        "checked_at": checked.isoformat(),
        "age_days": age_days,
        "max_age_days": max_age_days,
        "valid_until": (checked.date() + timedelta(days=max_age_days)).isoformat(),
        "retired_routes": retired,
    }


def _subject_checks(
    record: Any, record_path: Path, root: Path | None = None
) -> list[dict[str, Any]]:
    """Compare each subject digest with its file, under root or beside the record.

    Without `root`, names are relative to the working directory. With it, a
    file that resolves outside `root` counts as absent and is never read.
    """
    subjects = record.get("subject") if isinstance(record, dict) else None
    if not isinstance(subjects, list) or _subject_problems(subjects):
        return []
    checks = []
    for subject in subjects:
        name = subject["name"]
        candidates = [
            (root or Path()) / name,
            record_path.parent / Path(name).name,
        ]
        found = next(
            (
                path
                for path in candidates
                if path.is_file() and (root is None or _within(path.resolve(), root))
            ),
            None,
        )
        if found is None:
            state = "absent"
        else:
            matches = _file_sha256(found) == subject["digest"]["sha256"]
            state = "matches" if matches else "differs"
        checks.append(
            {"name": name, "role": subject["annotations"]["role"], "state": state}
        )
    return checks


def _subject_problems(subjects: Any) -> list[str]:
    if not isinstance(subjects, list) or not subjects:
        return ["subject is not a non-empty list"]
    roles = []
    for subject in subjects:
        if (
            not isinstance(subject, dict)
            or not isinstance(subject.get("name"), str)
            or not _is_sha256(_digest(subject))
            or not isinstance(subject.get("annotations"), dict)
        ):
            return ["each subject needs a name, a SHA-256 digest and a role"]
        name = Path(subject["name"])
        if (
            not subject["name"]
            or not subject["name"].isprintable()
            or name.is_absolute()
            or ".." in name.parts
        ):
            return ["a subject name must be a relative path inside the project"]
        roles.append(subject["annotations"].get("role"))
    if sorted(roles) != ["config", "result"]:
        return ["subject must name exactly one config and one result"]
    return []


def _origin_problems(
    evidence: Mapping[str, Any], predicate: Mapping[str, Any]
) -> list[str]:
    origin = evidence.get("origin")
    ci = evidence.get("ci")
    if origin == "local":
        if ci is not None or "url" in predicate:
            return ["a local record cannot carry a CI identity or run URL"]
        return []
    if origin != "github-actions":
        return ["origin is neither github-actions nor local"]
    if (
        not isinstance(ci, dict)
        or set(ci) != {key for _, key in _GITHUB_VARIABLES}
        or not all(_valid_ci_field(key, value) for key, value in ci.items())
    ):
        return ["the GitHub Actions identity is incomplete or malformed"]
    if predicate.get("url") != run_url(ci):
        return ["predicate.url does not match the GitHub Actions identity"]
    return []


def _result_selection(result: Mapping[str, Any]) -> Any:
    """The result's run selection in record form; None when it records none.

    A malformed value is copied as found, so the integrity check refuses it.
    """
    selection = result.get("selection")
    if not isinstance(selection, dict):
        return selection
    return {
        "prompt": selection.get("prompt"),
        "tests": selection.get("tests"),
        "environment": selection.get("environment"),
        "migrationCheck": selection.get("migration_check"),
    }


def _valid_selection(value: Any) -> bool:
    """None, or the four selection names a run can combine.

    As on the command line, `--migration-check` excludes `--prompt` and
    `--tests`, and `--prompt` excludes `--tests`.
    """
    if value is None:
        return True
    if not isinstance(value, dict) or set(value) != set(DEFAULT_SELECTION):
        return False
    if not isinstance(value["migrationCheck"], bool) or not all(
        name is None
        or (
            isinstance(name, str)
            and 0 < len(name) <= _MAX_SELECTION_LENGTH
            and name.isprintable()
        )
        for name in (value["prompt"], value["tests"], value["environment"])
    ):
        return False
    exclusive = (value["migrationCheck"], value["prompt"], value["tests"])
    return sum(bool(item) for item in exclusive) <= 1


def _valid_route_name(value: str) -> bool:
    return 0 < len(value) <= _MAX_ROUTE_NAME_LENGTH and value.isprintable()


def _valid_observed(value: Any) -> bool:
    """Absent, one reported model, or two or more distinct ones, as attest writes."""
    if value is None:
        return True
    if isinstance(value, list):
        return (
            len(value) >= 2
            and len(set(map(str, value))) == len(value)
            and all(reported_model(item) is not None for item in value)
        )
    return reported_model(value) is not None


def _valid_ci_field(key: str, value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if key == "workflow":
        return 0 < len(value) <= _MAX_WORKFLOW_LENGTH and value.isprintable()
    return _CI_FIELDS[key].fullmatch(value) is not None


def _provenance_problems(evidence: Mapping[str, Any]) -> list[str]:
    problems = [
        f"provenance.{name}_sha256 is not a SHA-256 digest"
        for name in _FINGERPRINTS
        if not _is_sha256(evidence.get(f"{name}_sha256"))
    ]
    if problems:
        return problems
    # contracts.provenance hashes every other field into evidence_sha256.
    unsealed = {
        key: value for key, value in evidence.items() if key != "evidence_sha256"
    }
    if _fingerprint(unsealed) != evidence["evidence_sha256"]:
        return ["provenance does not match its evidence_sha256"]
    return []


def _test_outcomes(
    result: Mapping[str, Any], state: str
) -> tuple[list[str], list[str], list[str]]:
    """One test per model and profile, or per model and prompt without profiles.

    An inconclusive decision degrades every test that did not fail: it passed
    on evidence the decision does not accept.
    """
    passed: list[str] = []
    warned: list[str] = []
    failed: list[str] = []
    prompt = result.get("prompt_name") or "config-prompt"
    for model in result.get("models", []):
        label = f"{model.get('provider', 'openai_compatible')}:{model['model']}"
        profiles = model.get("profiles") or []
        units = (
            [
                (f"{label}/{profile['name']}", {"profiles": [profile]})
                for profile in profiles
            ]
            if profiles
            else [(f"{label}/{prompt}", model)]
        )
        for name, unit in units:
            if model_failed(unit):
                failed.append(name)
            elif state == "inconclusive":
                warned.append(name)
            else:
                passed.append(name)
    return passed, warned, failed


def _routes(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every resolved route, from the pricing ledger the run used.

    Each carries the model its provider reported answering; a result written
    before `observed_model` existed records none.
    """
    models = result.get("models", [])
    ledger = result.get("pricing_ledger") or [
        {
            "provider": model.get("provider", "openai_compatible"),
            "model": model["model"],
        }
        for model in result.get("models", [])
    ]
    return [
        {
            "provider": entry["provider"],
            "model": entry["model"],
            "pricingAsOf": entry.get("as_of"),
            "observedModel": observed_model(
                model.get("observed_model")
                for model in models
                if model.get("provider", "openai_compatible") == entry["provider"]
                and model["model"] == entry["model"]
            ),
        }
        for entry in ledger
    ]


def _request_count(result: Mapping[str, Any]) -> int:
    return sum(
        int((model.get(summary) or {}).get("requests", 0))
        for model in result.get("models", [])
        for summary in ("summary", "warmup_summary")
    )


def _checked_routes(routes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The recorded routes as reported: a malformed observed model shows as none."""
    return [
        {
            "provider": route["provider"],
            "model": route["model"],
            "observed_model": route.get("observedModel")
            if _valid_observed(route.get("observedModel"))
            else None,
        }
        for route in routes
    ]


def _routes_annotation(descriptor: Any) -> list[dict[str, Any]] | None:
    routes = _annotations(descriptor).get("routes")
    if not isinstance(routes, list) or not all(
        isinstance(route, dict)
        and isinstance(route.get("provider"), str)
        and isinstance(route.get("model"), str)
        for route in routes
    ):
        return None
    return routes


def _descriptor(
    name: str, digest: str, annotations: dict[str, Any] | None = None
) -> dict[str, Any]:
    descriptor: dict[str, Any] = {
        "name": f"llm-preflight/{name}",
        "digest": {"sha256": digest},
    }
    if annotations is not None:
        descriptor["annotations"] = annotations
    return descriptor


def _descriptors(configuration: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(configuration, list):
        return {}
    return {
        item["name"].removeprefix("llm-preflight/"): item
        for item in configuration
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and item["name"].startswith("llm-preflight/")
    }


def _annotations(descriptor: Any) -> dict[str, Any]:
    annotations = (
        descriptor.get("annotations") if isinstance(descriptor, dict) else None
    )
    return annotations if isinstance(annotations, dict) else {}


def _digest(descriptor: Mapping[str, Any]) -> Any:
    digest = descriptor.get("digest")
    return digest.get("sha256") if isinstance(digest, dict) else None


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _subject_name(path: Path) -> str:
    """A project-relative name; a file outside the working directory keeps its name only."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return resolved.name


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_error(exc: Exception) -> str:
    if isinstance(exc, OSError):
        return exc.strerror or "it cannot be read"
    if isinstance(exc, UnicodeDecodeError):
        return "it is not UTF-8 text"
    return "it is not valid JSON"
