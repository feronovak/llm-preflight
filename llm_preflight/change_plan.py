"""Read-only Git change discovery for conservative preflight planning."""

from __future__ import annotations

import re
import shutil

# _git uses an absolute executable and argument arrays.
import subprocess  # nosec B404
from pathlib import Path
from typing import Any

from .source_audit import audit_source, audit_source_text

_REFERENCE = re.compile(r"[A-Za-z0-9._/@^~-]+\Z")
_CONTRACT_SURFACE = re.compile(
    r"\b(?P<field>prompt|system_prompt|validation|json_schema|tools?|tool_choice|"
    r"response_format|provider_options)\b",
    re.IGNORECASE,
)


def git_change_plan(repository: Path, reference: str = "HEAD") -> dict[str, Any]:
    """Report static LLM-integration change signals without provider access."""
    root = _repository_root(repository)
    _validate_reference(reference)
    changed_files, deleted_files = _changed_files(root, reference)
    triggers: list[dict[str, Any]] = []
    for relative_path in changed_files:
        path = (root / relative_path).resolve()
        deleted = relative_path in deleted_files
        if not deleted and root != path and root not in path.parents:
            continue
        if not deleted and not path.is_file():
            continue
        if deleted:
            previous = _git(root, "show", f"{reference}:{relative_path}").stdout
            findings = audit_source_text(Path(relative_path), previous)["references"]
        else:
            findings = audit_source(path)["references"]
        if findings:
            triggers.extend(
                {
                    "kind": "model_id",
                    "path": relative_path,
                    "line": finding["line"],
                    "provider": finding["provider"],
                    "model": finding["model"],
                    "pricing_status": finding["status"],
                    **({"change": "deleted"} if deleted else {}),
                }
                for finding in findings
            )
            continue
        trigger = (
            _contract_surface_trigger_text(previous, relative_path)
            if deleted
            else _contract_surface_trigger(path, relative_path)
        )
        if trigger:
            if deleted:
                trigger["change"] = "deleted"
            triggers.append(trigger)
    return {
        "schema_version": 1,
        "reference": reference,
        "network_accessed": False,
        "paid_work_authorized": False,
        "changed_files": changed_files,
        "deleted_files": deleted_files,
        "triggers": triggers,
        "requires_preflight_review": bool(triggers),
        "notes": [
            "Static findings cannot identify dynamic model selection; review application changes.",
            "This change plan is no-spend evidence and never authorizes paid work.",
        ],
    }


def _repository_root(repository: Path) -> Path:
    completed = _git(repository, "rev-parse", "--show-toplevel")
    return Path(completed.stdout.strip()).resolve()


def _validate_reference(reference: str) -> None:
    if (
        not isinstance(reference, str)
        or not reference
        or reference.startswith("-")
        or not _REFERENCE.fullmatch(reference)
    ):
        raise ValueError("Git reference contains unsupported characters")


def _changed_files(root: Path, reference: str) -> tuple[list[str], list[str]]:
    changed = _git(
        root,
        "diff",
        "--name-only",
        "--diff-filter=ACMRD",
        "-z",
        reference,
        "--",
    )
    deleted = _git(
        root, "diff", "--name-only", "--diff-filter=D", "-z", reference, "--"
    )
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    paths = [
        Path(item)
        for item in [*changed.stdout.split("\0"), *untracked.stdout.split("\0")]
        if item
    ]
    safe = []
    for path in paths:
        if path.is_absolute() or ".." in path.parts:
            continue
        safe.append(path.as_posix())
    deleted_paths = [Path(item) for item in deleted.stdout.split("\0") if item]
    safe_deleted = sorted(
        path.as_posix()
        for path in deleted_paths
        if not path.is_absolute() and ".." not in path.parts
    )
    return sorted(set(safe)), safe_deleted


def _contract_surface_trigger(path: Path, relative_path: str) -> dict[str, Any] | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return None
    return _contract_surface_trigger_text("\n".join(lines), relative_path)


def _contract_surface_trigger_text(
    text: str, relative_path: str
) -> dict[str, Any] | None:
    for line_number, line in enumerate(text.splitlines(), 1):
        match = _CONTRACT_SURFACE.search(line)
        if match:
            return {
                "kind": "contract_surface",
                "path": relative_path,
                "line": line_number,
                "field": match["field"].casefold(),
            }
    return None


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("git")
    if executable is None:
        raise ValueError("Git is required for --change-plan")
    try:
        # No shell is used; the Git reference is validated before this call.
        return subprocess.run(  # nosec B603
            [str(Path(executable).resolve()), "-C", str(repository), *arguments],
            check=True,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise ValueError("Git is required for --change-plan") from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or "Git could not inspect this repository"
        raise ValueError(message) from exc
