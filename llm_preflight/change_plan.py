"""Read-only Git change discovery for conservative preflight planning."""

from __future__ import annotations

import re
import stat

# Only CalledProcessError is used; run_git starts Git.
import subprocess  # nosec B404
from pathlib import Path
from typing import Any, NamedTuple

from .git import run_git
from .source_audit import (
    _SKIP_PARTS,
    _SOURCE_SUFFIXES,
    audit_source_text,
    display_path,
)

_UNOPENED = re.compile(r"could not open directory '(?P<directory>.+?)'")
_REFERENCE = re.compile(r"[A-Za-z0-9._/@^~-]+\Z")
_CONTRACT_SURFACE = re.compile(
    r"\b(?P<field>prompt|system_prompt|validation|json_schema|tools?|tool_choice|"
    r"response_format|provider_options)\b",
    re.IGNORECASE,
)


class _Listing(NamedTuple):
    changed: list[str]
    deleted: list[str]
    staged: set[str]
    # Directories Git could not open: the files in them were not listed.
    unopened: list[str]


class _Findings:
    """Triggers and unreadable paths gathered while reading changed files."""

    def __init__(self) -> None:
        self.triggers: list[dict[str, Any]] = []
        self.unreadable: list[str] = []

    def add(self, text: str, relative: str, source: Path, change: str | None) -> None:
        shown = display_path(relative)
        if _not_utf8(text):
            # The audit counts a non-UTF-8 file only when it selects the
            # file; other files (images, archives) hold no model ID to miss.
            if _audit_selects(relative, source):
                self.unreadable.append(shown)
            return
        marker = {"change": change} if change else {}
        findings = audit_source_text(source, text)["references"]
        if findings:
            self.triggers.extend(
                {
                    "kind": "model_id",
                    "path": shown,
                    "line": finding["line"],
                    "provider": finding["provider"],
                    "model": finding["model"],
                    "pricing_status": finding["status"],
                    **marker,
                }
                for finding in findings
            )
            return
        trigger = _contract_surface_trigger_text(text, shown)
        if trigger:
            self.triggers.append({**trigger, **marker})


def git_change_plan(repository: Path, reference: str = "HEAD") -> dict[str, Any]:
    """Report static LLM-integration change signals without provider access."""
    root = _repository_root(repository)
    _validate_reference(reference)
    listing = _changed_files(root, reference)
    found = _Findings()
    found.unreadable.extend(display_path(item) for item in listing.unopened)
    # Git reports a path it cannot lstat as deleted; only a missing path is.
    gone = {item for item in listing.deleted if _may_be_deleted(root / item)}
    # Paths stay as Git listed them for file and Git access, and are displayed
    # as UTF-8 text.
    for relative in listing.changed:
        if relative in listing.deleted and relative not in gone:
            found.unreadable.append(display_path(relative))
            continue
        if relative in gone:
            previous = _git(root, "show", f"{reference}:{relative}").stdout
            found.add(previous, relative, Path(relative), "deleted")
            if not _lstat_succeeds(root / relative):
                continue
        _scan_work_tree(root, relative, relative in listing.staged, found)
    return {
        "schema_version": 1,
        "reference": reference,
        "network_accessed": False,
        "paid_work_authorized": False,
        "changed_files": [display_path(item) for item in listing.changed],
        "deleted_files": [
            display_path(item) for item in listing.deleted if item in gone
        ],
        "files_unreadable": len(found.unreadable),
        "unreadable_files": found.unreadable,
        "plan_incomplete": bool(found.unreadable),
        "triggers": found.triggers,
        "requires_preflight_review": bool(found.triggers or found.unreadable),
        "notes": [
            *([unreadable_note(len(found.unreadable))] if found.unreadable else []),
            "Static findings cannot identify dynamic model selection; review application changes.",
            "This change plan is no-spend evidence and never authorizes paid work.",
        ],
    }


def _scan_work_tree(root: Path, relative: str, staged: bool, found: _Findings) -> None:
    try:
        path = (root / relative).resolve()
        if root != path and root not in path.parents:
            return
        text = _read_regular(path)
    except (OSError, RuntimeError):
        # Unknown is never "no contract surface": report it. A symlink loop
        # raises RuntimeError from resolve() before Python 3.13.
        found.unreadable.append(display_path(relative))
        return
    if text is not None:
        found.add(text, relative, path, None)
    if staged:
        index = _index_text(root, relative)
        if index is not None and index != text:
            found.add(index, relative, Path(relative), "staged")


def _read_regular(path: Path) -> str | None:
    """The text of a regular file; None when nothing is there to read."""
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            return None
        return path.read_text(encoding="utf-8", errors="surrogateescape")
    except (FileNotFoundError, NotADirectoryError):
        return None


def _index_text(root: Path, relative: str) -> str | None:
    completed = run_git(root, "show", f":{relative}", check=False)
    return completed.stdout if completed.returncode == 0 else None


def _not_utf8(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return True
    return False


def _audit_selects(relative: str, source: Path) -> bool:
    """Whether --audit-source would read this file: its suffix and skip list."""
    return source.suffix.casefold() in _SOURCE_SUFFIXES and not any(
        part in _SKIP_PARTS for part in Path(relative).parts
    )


def _lstat_succeeds(path: Path) -> bool:
    try:
        path.lstat()
    except OSError:
        return False
    return True


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


def _changed_files(root: Path, reference: str) -> _Listing:
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
    staged_paths = {Path(item).as_posix() for item in staged.stdout.split("\0") if item}
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
    return _Listing(
        sorted(set(safe)),
        safe_deleted,
        {item for item in staged_paths if item in safe},
        _unopened_directories(untracked.stderr),
    )


def _unopened_directories(stderr: str) -> list[str]:
    """Directories Git warned it could not open; any other warning is the root."""
    found: list[str] = []
    for line in stderr.splitlines():
        match = _UNOPENED.search(line)
        directory = Path(match["directory"]) if match else Path(".")
        if directory.is_absolute() or ".." in directory.parts:
            continue
        shown = directory.as_posix()
        if shown not in found:
            found.append(shown if shown == "." else shown + "/")
    return found


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
