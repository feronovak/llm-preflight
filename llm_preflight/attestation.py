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
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .catalog import resolve_models
from .client import observed_model, reported_model
from .contracts import _fingerprint, provenance, selection_fingerprint
from .features import (
    apply_environment,
    apply_migration_check,
    apply_model_aliases,
    apply_provider_presets,
    apply_smoke_mode,
)
from .git import run_git
from .github_actions import ci_identity, valid_ci_field, valid_ci_identity
from .pricing import resolve_pricing
from .redaction import redact_secrets
from .retirements import retirement_verdict, snapshot_summary
from .runner import (
    load_config,
    model_failed,
    run_repetitions,
    select_custom_prompt,
    selected_profiles,
    validate_config_validations,
)
from .source_audit import display_path

STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://in-toto.io/attestation/test-result/v0.1"
RECORD_SUFFIX = ".preflight.json"
DEFAULT_MAX_AGE_DAYS = 30
# A record is untrusted input: one larger or deeper than any attest writes is
# refused before it can exhaust memory or the stack.
MAX_RECORD_BYTES = 1 << 20
_MAX_RECORD_DEPTH = 64
DEFAULT_SERVER_URL = "https://github.com"
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
# The run flags that shape what a run sends; names only, so a record never
# carries a credential or an env-file path. A recorded selection adds
# `repetitions`, how many times the run sent each prompt.
DEFAULT_SELECTION: dict[str, Any] = {
    "prompt": None,
    "tests": None,
    "environment": None,
    "migrationCheck": False,
    "smoke": False,
}
_SELECTION_KEYS = {*DEFAULT_SELECTION, "repetitions"}
_MAX_SELECTION_LENGTH = 200
_MAX_REPETITIONS = 1_000_000
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
    "foreign_record",
    "inconsistent_record",
    "selection_changed",
    "contract_changed",
    "routes_changed",
    "prompt_changed",
)
# The run identity attest requires the result and its own job to share.
_SAME_RUN = ("repository", "serverUrl", "runId", "commit")
_ATTEST_NEXT = "llm-preflight attest results/<new>.json   (CI does this for you)"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def default_record_path(result_path: Path) -> Path:
    """`results/run.json` is attested to `results/run.preflight.json`."""
    return result_path.with_suffix(RECORD_SUFFIX)


def expected_repository(
    flag: str | None, environ: Mapping[str, str]
) -> dict[str, str] | None:
    """The repository a gate accepts records from, or None when it is unknown.

    It is `--repository OWNER/NAME`, else GITHUB_REPOSITORY; the server is
    GITHUB_SERVER_URL, else github.com. A malformed value is refused; a flag
    that contradicts GITHUB_REPOSITORY is reported by `repository_conflict`.
    """
    repository = flag or environ.get("GITHUB_REPOSITORY") or None
    if repository is None:
        return None
    server = environ.get("GITHUB_SERVER_URL") or DEFAULT_SERVER_URL
    if not valid_ci_field("repository", repository):
        raise ValueError(
            f"the expected repository {repository!r} is not OWNER/NAME, such as acme/app"
        )
    if not valid_ci_field("serverUrl", server):
        raise ValueError(f"GITHUB_SERVER_URL {server!r} is not an https:// server URL")
    return {"repository": repository, "serverUrl": server}


def repository_conflict(flag: str | None, environ: Mapping[str, str]) -> str | None:
    """GITHUB_REPOSITORY when `--repository` names another repository, else None.

    Names are compared without regard to case, as GitHub compares them.
    """
    environment = environ.get("GITHUB_REPOSITORY") or None
    if flag is None or environment is None:
        return None
    return None if flag.casefold() == environment.casefold() else environment


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
) -> tuple[dict[str, Any], str | None]:
    """Read a saved result and its config; return their record and, for a local
    record, why it carries no GitHub Actions run identity."""
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
    ci, local_reason = _run_origin(result, environ)
    record = build_record(
        result,
        result_name=_subject_name(result_path),
        result_digest=hashlib.sha256(result_bytes).hexdigest(),
        config_name=_subject_name(config_path),
        config_digest=_file_sha256(config_path),
        ci=ci,
        today=today,
    )
    return record, local_reason


def _run_origin(
    result: Mapping[str, Any], environ: Mapping[str, str]
) -> tuple[dict[str, str] | None, str | None]:
    """The run identity a record carries, or None and why the record is local.

    A record names a GitHub Actions run only when the result recorded that run
    as it ran and attest runs in the same run, so the identity of the job that
    attests can never stand in for the run that checked.
    """
    attesting = ci_identity(environ)
    recorded = result.get("ci")
    if attesting is None and recorded is None:
        return None, "no CI run identity"
    if attesting is None:
        return None, (
            "it was attested outside the GitHub Actions run that made the result"
        )
    if recorded is None:
        return None, (
            "the result records no GitHub Actions run identity: it ran outside "
            "GitHub Actions or with llm-preflight before 2.22.0"
        )
    if not valid_ci_identity(recorded):
        return None, "the result's GitHub Actions run identity is malformed"
    if any(recorded[key] != attesting[key] for key in _SAME_RUN):
        return None, "the result was made in another GitHub Actions run"
    return dict(recorded), None


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
    # The result's provenance seals what the run sent. Copy the selection hash
    # and the verdict into that seal here, so an annotation edit cannot make
    # a different selection or a rewritten pass verify.
    sealed = _seal_verdict(evidence, result, decision)
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
                sealed["evidence_sha256"],
                {
                    "checkedAt": result.get("timestamp"),
                    "runId": result.get("run_id"),
                    # The safe next command names the local config path.
                    "decision": {
                        key: copy.deepcopy(value)
                        for key, value in decision.items()
                        if key != "safe_next_command"
                    },
                    "provenance": sealed,
                    "requests": requests,
                    "selection": _result_selection(result),
                    "selectionSha256": result.get("selection_sha256"),
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
    """Parse a record file as untrusted JSON, refusing one larger than
    MAX_RECORD_BYTES or nested deeper than any record attest writes."""
    with path.open("rb") as handle:
        data = handle.read(MAX_RECORD_BYTES + 1)
    if len(data) > MAX_RECORD_BYTES:
        raise ValueError(f"the record is larger than {MAX_RECORD_BYTES:,} bytes")
    too_deep = f"the record is nested more than {_MAX_RECORD_DEPTH} levels deep"
    try:
        record = json.loads(data.decode("utf-8"))
    except RecursionError:
        raise ValueError(too_deep) from None
    if _too_deep(record):
        raise ValueError(too_deep)
    return record


def _too_deep(value: Any) -> bool:
    """Whether objects and arrays nest deeper than _MAX_RECORD_DEPTH, found
    without recursion."""
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, dict | list):
            if depth > _MAX_RECORD_DEPTH:
                return True
            children = item.values() if isinstance(item, dict) else item
            stack.extend((child, depth + 1) for child in children)
    return False


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
    # Records attested before the verdict was sealed have no decision_state.
    # A checksum is not a signature: a writer who reseals the digest and the
    # descriptor can still substitute a verdict. This catches an edit that
    # leaves the seal behind.
    if isinstance(fingerprints, dict) and "decision_state" in fingerprints:
        problems.extend(
            _sealed_annotation_problems(evidence, fingerprints, decision, state)
        )
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
    check_subjects: bool = True,
) -> dict[str, Any]:
    """Report integrity and freshness separately; they are never merged.

    `routes` overrides the record's own route list for the retirement check;
    the gate passes the routes it resolved from the current config. `root`
    (default: the working directory) is where subject names are looked up;
    when given, a subject file that resolves outside it is not read. Without
    `check_subjects`, as in the gate, no file but the record is read: files in
    a pull request's tree must not decide which record counts.
    """
    problems = integrity_problems(record, today)
    subjects = _subject_checks(record, record_path, root) if check_subjects else []
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
    ci = evidence.get("ci")
    url = predicate.get("url")
    return escaped(
        {
            "record": display_path(record_path),
            "result": predicate.get("result")
            if predicate.get("result") in _RESULTS.values()
            else None,
            "integrity": {
                "ok": not problems,
                "problems": problems,
                "subjects": subjects,
            },
            "routes": _checked_routes(recorded),
            "freshness": _freshness(
                _timestamp(evidence.get("checkedAt")), routes, today, max_age_days
            ),
            "retirement_snapshot": snapshot_summary()["newest_as_of"],
            "origin": origin if origin in {"github-actions", "local"} else None,
            "repository": ci.get("repository") if isinstance(ci, dict) else None,
            "server_url": ci.get("serverUrl") if isinstance(ci, dict) else None,
            "url": url if isinstance(url, str) else None,
            "signature": SIGNATURE_NOTE,
        }
    )


def escaped(value: Any) -> Any:
    """`value` with every string valid Unicode text, for a report built from an
    untrusted record. A lone surrogate, from a JSON escape such as \\udcff or a
    file name that is not UTF-8, becomes its backslash escape, so every
    report encodes as strict UTF-8 JSON."""
    if isinstance(value, str):
        return value.encode("utf-8", "backslashreplace").decode("utf-8")
    if isinstance(value, dict):
        return {escaped(key): escaped(item) for key, item in value.items()}
    if isinstance(value, list):
        return [escaped(item) for item in value]
    return value


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
    """The fingerprints a run of this config records: its contract, routes and
    prompts, each with the request sent with it, and how many times it sends
    each prompt.

    It resolves the config and its test profiles exactly as a run under
    `selection` (`--env`, `--smoke`, `--migration-check`, `--prompt`,
    `--tests`; default: none) does before `provenance`, without loading
    credentials or contacting a provider.
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
    if selection["smoke"]:
        config = apply_smoke_mode(config)
    if selection["migrationCheck"]:
        config = apply_migration_check(config)
    if selection["prompt"]:
        config = select_custom_prompt(config, selection["prompt"])
    profiles = selected_profiles(
        config,
        "quick-migration-check" if selection["migrationCheck"] else selection["tests"],
    )
    models = resolve_pricing(resolve_models(config))["models"]
    fingerprints = provenance(config, models, "", profiles)
    return {
        "contract_sha256": fingerprints["contract_sha256"],
        "routes_sha256": fingerprints["routes_sha256"],
        "prompts": fingerprints["prompts"],
        "repetitions": run_repetitions(config, profiles),
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
    repository: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Decide offline whether the current tree has a fresh passing record.

    Pass only on the newest CI record that ran the gate's `selection`
    (default: a default run), as many times per prompt as the config now asks,
    matches the current contract, routes and prompts under it, and is PASSED,
    consistent, fresh and not superseded. A record that ran another selection
    or fewer repetitions never counts. Only a record from the expected
    repository (`repository`, else GITHUB_REPOSITORY in `environ`; see
    `expected_repository`) counts; without one, or when the two disagree, the
    gate cannot decide, since another repository's record can carry the same
    fingerprints. A record is judged by its own consistency, never by files in
    the tree. One that cannot be read, or fails its integrity check, makes the
    gate unable to decide when it might be the newest. With `root`, as for the
    MCP workspace, a record that resolves outside it is never read.
    """
    environ = environ if environ is not None else {}
    expected = expected_repository(repository, environ)
    conflict = repository_conflict(repository, environ)
    return escaped(
        _decide(
            config_path,
            record_paths,
            today,
            max_age_days,
            {**DEFAULT_SELECTION, **(selection or {})},
            root,
            None if conflict else expected,
            (repository, conflict) if conflict else None,
        )
    )


def _decide(
    config_path: Path,
    record_paths: Sequence[Path],
    today: date,
    max_age_days: int,
    selection: dict[str, Any],
    root: Path | None,
    repository: Mapping[str, str] | None,
    conflict: tuple[str | None, str] | None,
) -> dict[str, Any]:
    config = display_path(config_path)
    report: dict[str, Any] = {
        "config": config,
        "selection": {**selection, "repetitions": None},
        "repository": repository["repository"] if repository else None,
        "server_url": repository["serverUrl"] if repository else None,
        "contract_sha256": None,
        "routes_sha256": None,
        "max_age_days": max_age_days,
        "retirement_snapshot": snapshot_summary()["newest_as_of"],
        "signature": SIGNATURE_NOTE,
        "network_accessed": False,
        "records": [],
    }
    try:
        current = current_fingerprints(config_path, selection)
    except (OSError, ValueError) as exc:
        reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else exc
        return _undecided_config(report, config, reason)
    except (AttributeError, KeyError, TypeError):
        return _undecided_config(report, config, "it is not a benchmark configuration")
    # A record must have sent each prompt as many times as the config asks now.
    required = {**selection, "repetitions": current["repetitions"]}
    report["selection"] = required
    report["contract_sha256"] = current["contract_sha256"]
    report["routes_sha256"] = current["routes_sha256"]
    if conflict is not None:
        flag, environment = conflict
        return {
            "decision": "undecided",
            "reason_code": "repository_unknown",
            "why": (
                "The gate cannot tell which repository this tree belongs to: "
                f"--repository names {flag}, but GITHUB_REPOSITORY is "
                f"{environment}."
            ),
            "next": [
                (
                    "drop --repository in GitHub Actions, or give the repository "
                    "GITHUB_REPOSITORY names"
                )
            ],
            **report,
        }
    if repository is None:
        run = " ".join([_quote(config), *selection_flags(required)])
        searched = " ".join(_quote(display_path(path)) for path in record_paths)
        return {
            "decision": "undecided",
            "reason_code": "repository_unknown",
            "why": (
                "The gate cannot tell which repository this tree belongs to: no "
                "--repository OWNER/NAME was given and GITHUB_REPOSITORY is not "
                "set. A record from another repository can carry the same "
                "fingerprints, so the gate never decides without it."
            ),
            "next": [
                (
                    f"llm-preflight gate {run} --repository OWNER/NAME --records "
                    f"{searched}   (the repository this tree belongs to)"
                )
            ],
            **report,
        }
    entries = [
        _evaluate(path, current, required, repository, today, max_age_days)
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
        # A broken record's date is unproven; without one it might be newest.
        broken = next(
            (
                e
                for e in entries
                if e["verdict"] == "inconsistent_record"
                and (e["_checked"] is None or e["_checked"] >= newest["_checked"])
            ),
            None,
        )
        if broken is not None:
            return {
                "decision": "undecided",
                "reason_code": "record_error",
                "why": (
                    f"{broken['path']} fails its integrity check "
                    f"({broken['reason']}) and might be newer than "
                    f"{_described(newest)}. The gate cannot decide while a "
                    "record it cannot judge might be the newest."
                ),
                "next": [
                    (
                        f"llm-preflight verify {_quote(broken['path'])}   "
                        "(free: every integrity problem)"
                    ),
                    (
                        "discard the broken record or download it again intact, "
                        "then rerun the gate"
                    ),
                ],
                **report,
            }
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
        code,
        newest,
        config,
        current,
        required,
        repository,
        record_paths,
        max_age_days,
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
    repository: Mapping[str, str],
    today: date,
    max_age_days: int,
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
    report = verify_record(
        record, path, today, max_age_days, current["routes"], check_subjects=False
    )
    if not report["integrity"]["ok"]:
        entry = _entry(path, "inconsistent_record", report["integrity"]["problems"][0])
        # Unproven, but the only hint of whether it might be the newest.
        entry["_checked"] = _timestamp(report["freshness"]["checked_at"])
        return entry
    descriptors = _descriptors(record["predicate"]["configuration"])
    evidence = descriptors["evidence"]["annotations"]
    freshness = report["freshness"]
    entry = _entry(path, "pass", "fresh, passing CI record for this contract")
    entry.update(
        result=report["result"],
        origin=report["origin"],
        run_id=(evidence.get("ci") or {}).get("runId"),
        repository=(evidence.get("ci") or {}).get("repository"),
        server_url=(evidence.get("ci") or {}).get("serverUrl"),
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
        selection_sha256=evidence.get("selectionSha256"),
        contract_sha256=_digest(descriptors["contract"]),
        routes_sha256=_digest(descriptors["routes"]),
        _checked=_timestamp(evidence["checkedAt"]),
        _prompt_change=_prompt_change(
            evidence["provenance"]["prompts"], current["prompts"]
        ),
    )
    for verdict, reason, applies in (
        (
            "foreign_record",
            f"from {entry['repository']} on {entry['server_url']}",
            report["origin"] == "github-actions"
            and not _same_repository(entry, repository),
        ),
        (
            "selection_changed",
            "does not record its selection"
            if entry["selection"] is None
            else "does not record its raw selection"
            if not _is_sha256(entry.get("selection_sha256"))
            else "ran a different selection",
            # Compare a digest of the selection as chosen. The stored names are
            # redacted, so two prompts called sk-alpha and sk-beta would match
            # as text.
            entry["selection"] is None
            or not _is_sha256(entry.get("selection_sha256"))
            or entry["selection_sha256"] != selection_fingerprint(required),
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
        (
            "prompt_changed",
            _prompt_reason(entry["_prompt_change"]),
            entry["_prompt_change"] is not None,
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
        "server_url": None,
        "checked_at": None,
        "age_days": None,
        "valid_until": None,
        "tests": None,
        "blocking_warnings": None,
        "retired_routes": [],
        "routes": [],
        "selection": None,
        "selection_sha256": None,
        "contract_sha256": None,
        "routes_sha256": None,
        "_checked": None,
        "_prompt_change": None,
    }


def _prompt_change(
    recorded: Sequence[Mapping[str, Any]], current: Sequence[Mapping[str, Any]]
) -> tuple[str, str | None] | None:
    """How the prompts sent now differ from those a record checked, or None.

    The kind is `unrecorded`, `text`, `request`, `both`, `added` or `removed`,
    with the prompt it names. Order is not compared: a test selector is
    canonical in a record, so custom tests may run in another order.
    """
    if not all("request_sha256" in entry for entry in recorded):
        return ("unrecorded", None)

    def key(entry: Mapping[str, Any]) -> tuple[str, str, str]:
        return (entry["name"], entry["sha256"], entry["request_sha256"])

    unchecked = Counter(map(key, current)) - Counter(map(key, recorded))
    gone = Counter(map(key, recorded)) - Counter(map(key, current))
    for name, text, request in (key(entry) for entry in current):
        if (name, text, request) not in unchecked:
            continue
        before = next((item for item in gone if item[0] == name), None)
        if before is None:
            return ("added", name)
        if before[1] != text and before[2] != request:
            return ("both", name)
        return ("text" if before[1] != text else "request", name)
    return ("removed", next(iter(gone))[0]) if gone else None


def _prompt_reason(change: tuple[str, str | None] | None) -> str:
    kind, name = change or ("", None)
    return {
        "unrecorded": "does not record the request options of its prompts",
        "text": f"the text of prompt {name} changed",
        "request": f"the request options of prompt {name} changed",
        "both": f"the text and the request options of prompt {name} changed",
        "added": f"did not check prompt {name}",
        "removed": f"checked prompt {name}, which is no longer sent",
    }.get(kind, "")


def _explain(
    code: str,
    newest: dict[str, Any] | None,
    config: str,
    current: Mapping[str, Any],
    required: Mapping[str, Any],
    expected: Mapping[str, str],
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
                f"contract, its prompts and its routes on {newest['checked_at'][:10]} "
                f"({_age(newest['age_days'])}); it stays fresh until "
                f"{newest['valid_until']}. "
                + "".join(f"{describe_route(route)}. " for route in newest["routes"])
                + f"The signature is {SIGNATURE_NOTE}."
            ),
            [],
        )
    if code == "foreign_record":
        return (
            (
                f"The latest record ({described}) comes from "
                f"{newest['repository']} on {newest['server_url']}, not "
                f"{expected['repository']} on {expected['serverUrl']}. A record "
                "from another repository proves nothing about this one."
            ),
            [
                "run the bounded check in this repository's CI",
                _ATTEST_NEXT,
                (
                    "download that run's record, then rerun: "
                    f"llm-preflight gate {run} --records DIR"
                ),
            ],
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
        if ran == requires:
            if newest["selection"].get("repetitions") != required.get("repetitions"):
                # Same flags, so the config now sends each prompt more or fewer times.
                return (
                    (
                        f"The latest record ({described}) ran {ran} with "
                        f"{_counted(newest['selection']['repetitions'], 'repetition')} "
                        f"per prompt; {config} now asks for {required['repetitions']} "
                        "under the same selection."
                    ),
                    fresh_check,
                )
            return (
                (
                    f"The latest record ({described}) recorded {ran}, but that "
                    "is not the selection this gate requires."
                ),
                fresh_check,
            )
        return (
            (
                f"The latest record ({described}) ran {_with_depth(newest['selection'])}; "
                f"this gate requires {_with_depth(required)}."
            ),
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
    if code == "prompt_changed":
        kind, name = newest["_prompt_change"]
        prompt = f"prompt {name}"
        whys = {
            "unrecorded": (
                f"{latest} does not record the request options its prompts were "
                "sent with (it was attested from a result written before "
                "2.22.0), so it cannot show that it checked the current prompts."
            ),
            "text": f"The text of {prompt} changed since the latest record "
            f"({described}) checked it.",
            "request": (
                f"The request options of {prompt} changed since the latest record "
                f"({described}) checked it: its system prompt, temperature, token "
                "limit, presets, provider options or images."
            ),
            "both": f"The text and the request options of {prompt} changed since "
            f"the latest record ({described}) checked it.",
            "added": f"{config} now sends {prompt}, which the latest record "
            f"({described}) did not check.",
            "removed": f"The latest record ({described}) checked {prompt}, which "
            "is no longer sent.",
        }
        return whys[kind], fresh_check
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
    if selection.get("smoke"):
        flags.append("--smoke")
    if selection.get("migrationCheck"):
        flags.append("--migration-check")
    if selection.get("prompt"):
        flags += ["--prompt", _quote(selection["prompt"])]
    if selection.get("tests"):
        flags += ["--tests", _quote(selection["tests"])]
    return flags


def describe_selection(selection: Mapping[str, Any]) -> str:
    return " ".join(selection_flags(selection)) or "a default run"


def _with_depth(selection: Mapping[str, Any]) -> str:
    """The selection and how many times it sends each prompt."""
    repetitions = _counted(selection["repetitions"], "repetition")
    return f"{describe_selection(selection)} ({repetitions} per prompt)"


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
    if not valid_ci_identity(ci):
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
        "smoke": selection.get("smoke"),
        "repetitions": selection.get("repetitions"),
    }


def _valid_selection(value: Any) -> bool:
    """None, or the selection flags a run can combine and how many times it
    sent each prompt.

    As on the command line, `--migration-check` excludes `--prompt` and
    `--tests`, and `--prompt` excludes `--tests`; `--smoke` sends each prompt
    once.
    """
    if value is None:
        return True
    if not isinstance(value, dict) or set(value) != _SELECTION_KEYS:
        return False
    repetitions = value["repetitions"]
    if not (
        isinstance(value["migrationCheck"], bool)
        and isinstance(value["smoke"], bool)
        and isinstance(repetitions, int)
        and not isinstance(repetitions, bool)
        and 1 <= repetitions <= _MAX_REPETITIONS
        and (repetitions == 1 or not value["smoke"])
    ):
        return False
    if not all(
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


def _same_repository(entry: Mapping[str, Any], expected: Mapping[str, str]) -> bool:
    """GitHub owner and repository names, like host names, ignore case."""
    return (
        str(entry["repository"]).casefold() == expected["repository"].casefold()
        and str(entry["server_url"]).rstrip("/").casefold()
        == expected["serverUrl"].rstrip("/").casefold()
    )


def _seal_verdict(
    evidence: Mapping[str, Any], result: Mapping[str, Any], decision: Mapping[str, Any]
) -> dict[str, Any]:
    """Provenance plus the selection hash and verdict, resealed.

    The result file keeps the run's provenance. The record's copy also binds
    the hash and the verdict the gate reads, so changing either annotation
    without this seal fails integrity.
    """
    sealed = copy.deepcopy(dict(evidence))
    sealed.pop("evidence_sha256", None)
    sealed["selection_sha256"] = result.get("selection_sha256")
    sealed["decision_state"] = decision.get("state")
    sealed["blocking_warnings"] = copy.deepcopy(decision.get("blocking_warnings"))
    sealed["cost_confidence"] = result.get("cost_confidence")
    sealed["evidence_sha256"] = _fingerprint(sealed)
    return sealed


def _sealed_annotation_problems(
    evidence: Mapping[str, Any],
    fingerprints: Mapping[str, Any],
    decision: Any,
    state: Any,
) -> list[str]:
    """Annotation fields that disagree with the sealed provenance."""
    problems = []
    if evidence.get("selectionSha256") != fingerprints.get("selection_sha256"):
        problems.append("selectionSha256 does not match the sealed selection")
    if state != fingerprints.get("decision_state"):
        problems.append("the decision does not match the sealed decision")
    warnings = decision.get("blocking_warnings") if isinstance(decision, dict) else None
    if warnings != fingerprints.get("blocking_warnings"):
        problems.append("blocking warnings do not match the sealed decision")
    if evidence.get("costConfidence") != fingerprints.get("cost_confidence"):
        problems.append("cost confidence does not match the sealed cost confidence")
    return problems


def _provenance_problems(evidence: Mapping[str, Any]) -> list[str]:
    problems = [
        f"provenance.{name}_sha256 is not a SHA-256 digest"
        for name in _FINGERPRINTS
        if not _is_sha256(evidence.get(f"{name}_sha256"))
    ]
    if problems:
        return problems
    if not _valid_prompts(evidence.get("prompts")):
        return ["provenance.prompts is not a list of prompt fingerprints"]
    # contracts.provenance hashes every other field into evidence_sha256.
    unsealed = {
        key: value for key, value in evidence.items() if key != "evidence_sha256"
    }
    if _fingerprint(unsealed) != evidence["evidence_sha256"]:
        return ["provenance does not match its evidence_sha256"]
    return []


def _valid_prompts(value: Any) -> bool:
    """Each prompt a run sent: its name, text digest and length, and the digest
    of its request options, which results written before 2.22.0 lack."""
    return isinstance(value, list) and all(
        isinstance(entry, dict)
        and isinstance(entry.get("name"), str)
        and _is_sha256(entry.get("sha256"))
        and ("request_sha256" not in entry or _is_sha256(entry["request_sha256"]))
        for entry in value
    )


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
    if isinstance(exc, json.JSONDecodeError):
        return "it is not valid JSON"
    return str(exc)
