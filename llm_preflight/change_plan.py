"""Read-only Git change discovery for conservative preflight planning."""

from __future__ import annotations

import re
import stat

# Only CalledProcessError is used; run_git starts Git.
import subprocess  # nosec B404
from pathlib import Path
from typing import Any

from .git import run_git
from .source_audit import audit_source_text, display_path

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
    unreadable: list[str] = []
    # Git reports a path it cannot lstat as deleted; only a missing path is.
    gone = {item for item in deleted_files if _may_be_deleted(root / item)}
    # Paths stay as Git listed them for file and Git access, and are displayed
    # as UTF-8 text.
    for relative_path in changed_files:
        shown = display_path(relative_path)
        path = (root / relative_path).resolve()
        if relative_path in deleted_files and relative_path not in gone:
            unreadable.append(shown)
            continue
        deleted = relative_path in gone
        if not deleted and root != path and root not in path.parents:
            continue
        if deleted:
            text = _git(root, "show", f"{reference}:{relative_path}").stdout
            source = Path(relative_path)
        else:
            try:
                if not stat.S_ISREG(path.stat().st_mode):
                    continue
                text = path.read_text(encoding="utf-8")
            except (FileNotFoundError, NotADirectoryError):
                continue  # nothing here to read, as is_file() decided
            except (OSError, UnicodeDecodeError):
                # Unknown is never "no contract surface": report it.
                unreadable.append(shown)
                continue
            source = path
        findings = audit_source_text(source, text)["references"]
        if findings:
            triggers.extend(
                {
                    "kind": "model_id",
                    "path": shown,
                    "line": finding["line"],
                    "provider": finding["provider"],
                    "model": finding["model"],
                    "pricing_status": finding["status"],
                    **({"change": "deleted"} if deleted else {}),
                }
                for finding in findings
            )
            continue
        trigger = _contract_surface_trigger_text(text, shown)
        if trigger:
            if deleted:
                trigger["change"] = "deleted"
            triggers.append(trigger)
    return {
        "schema_version": 1,
        "reference": reference,
        "network_accessed": False,
        "paid_work_authorized": False,
        "changed_files": [display_path(item) for item in changed_files],
        "deleted_files": [display_path(item) for item in deleted_files if item in gone],
        "files_unreadable": len(unreadable),
        "unreadable_files": unreadable,
        "plan_incomplete": bool(unreadable),
        "triggers": triggers,
        "requires_preflight_review": bool(triggers or unreadable),
        "notes": [
            *([unreadable_note(len(unreadable))] if unreadable else []),
            "Static findings cannot identify dynamic model selection; review application changes.",
            "This change plan is no-spend evidence and never authorizes paid work.",
        ],
    }


def _may_be_deleted(path: Path) -> bool:
    """False only when Git listed path as deleted because it may not be seen."""
    try:
        path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return True
    except OSError:
        return False
    return True


def unreadable_note(count: int) -> str:
    """The incomplete-plan statement shared by JSON notes and CLI text."""
    subject, pronoun = ("1 file", "it") if count == 1 else (f"{count} files", "they")
    return (
        f"Plan incomplete: {subject} could not be read as UTF-8 text; "
        f"{pronoun} may still change a model ID, prompt, schema or tool definition."
    )


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
    # Looking for edits inside a submodule runs git status there, under the
    # submodule's own configuration. A changed submodule commit is still listed.
    changed = _git(
        root,
        "diff",
        "--name-only",
        "--diff-filter=ACMRD",
        "--ignore-submodules=dirty",
        "-z",
        reference,
        "--",
    )
    deleted = _git(
        root,
        "diff",
        "--name-only",
        "--diff-filter=D",
        "--ignore-submodules=dirty",
        "-z",
        reference,
        "--",
    )
    staged = _git(
        root,
        "diff",
        "--cached",
        "--name-only",
        "--diff-filter=ACMRD",
        "--ignore-submodules=dirty",
        "-z",
        reference,
        "--",
    )
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    paths = [
        Path(item)
        for item in [
            *changed.stdout.split("\0"),
            *staged.stdout.split("\0"),
            *untracked.stdout.split("\0"),
        ]
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
    try:
        # The Git reference is validated before this call.
        return run_git(repository, *arguments)
    except FileNotFoundError as exc:
        raise ValueError("Git is required for --change-plan") from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or "Git could not inspect this repository"
        raise ValueError(message) from exc
