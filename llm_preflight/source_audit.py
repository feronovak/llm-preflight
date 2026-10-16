from __future__ import annotations

import os
import re

# Only CalledProcessError is used; run_git starts Git.
import subprocess  # nosec B404
from datetime import date
from pathlib import Path
from typing import Any

from .git import run_git
from .pricing import PUBLIC_PRICING
from .redaction import redact_secrets
from .retirements import (
    retirement_verdict,
    snapshot_summary,
    today_utc,
    unique_next_commands,
    worst_decision,
)

_RETIREMENT_FINDINGS = {"retired", "retiring", "stale"}
_CONFIDENCE = "limited_static_pricing_and_retirement"
_NOTES = [
    "Only literal model IDs are reported; dynamic model selection requires review.",
    "Pricing unknown means the bundled static pricing table has no matching entry; it is advisory, not a catalog verdict.",
    "Retirement verdicts come from the bundled snapshot of the official Anthropic, OpenAI and selected Gemini deprecation and model pages for text-generation models; unknown means no row and is not a verdict.",
]

_SOURCE_SUFFIXES = {
    ".py",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
}
_SKIP_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__", "results"}
_GIT_REASON_LIMIT = 120
_QUOTED = re.compile(
    r"(?P<quote>['\"])(?P<value>[A-Za-z0-9][A-Za-z0-9._:/-]*)(?P=quote)"
)
_MODEL_PREFIX = re.compile(
    r"^(?:(?:anthropic|openai|google|xai|x-ai|deepseek|qwen|alibaba|typesafe|z-ai|zai)/)?(?:gpt-[A-Za-z0-9]|claude-[A-Za-z0-9]|gemini-[A-Za-z0-9]|grok-[A-Za-z0-9]|deepseek-[A-Za-z0-9]|qwen[A-Za-z0-9]|glm-[A-Za-z0-9]|jev-[A-Za-z0-9]|o[1-9](?:-|$))",
    re.IGNORECASE,
)
_YAML_MODEL = re.compile(
    r"\bmodel(?:_id)?\s*:\s*(?P<value>[A-Za-z0-9][A-Za-z0-9._:/-]*)"
)


def _provider_for(model: str) -> str | None:
    lowered = model.rsplit("/", 1)[-1].casefold()
    if lowered.startswith("gpt-") or re.match(r"^o[1-9](?:-|$)", lowered):
        return "openai"
    if lowered.startswith("claude-"):
        return "anthropic"
    if lowered.startswith("gemini-"):
        return "gemini"
    if lowered.startswith("grok-"):
        return "xai"
    if lowered.startswith("deepseek-"):
        return "deepseek"
    if lowered.startswith("qwen"):
        return "qwen"
    if lowered.startswith("glm-"):
        return "zai"
    if lowered.startswith("jev-"):
        return "typesafe"
    return None


def _is_finding(item: dict[str, Any]) -> bool:
    return (
        item["status"] != "pricing_known"
        or item["retirement"]["status"] in _RETIREMENT_FINDINGS
    )


def _summary_fields(references: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "findings": [item for item in references if _is_finding(item)],
        "ok": True,
        "decision": worst_decision(
            item["retirement"]["decision"] for item in references
        ),
        "next_commands": unique_next_commands(
            item["retirement"] for item in references
        ),
        "retirement_snapshot": snapshot_summary(),
        "confidence": _CONFIDENCE,
        "notes": list(_NOTES),
    }


def display_path(path: Path | str) -> str:
    """A file system or Git path as UTF-8 text; bytes that are not UTF-8 become
    backslash escapes, since a lone surrogate is invalid in JSON output."""
    return os.fsencode(path).decode("utf-8", "backslashreplace")


def audit_source(path: Path, today: date | None = None) -> dict[str, Any]:
    """Find literal model IDs without importing project code or contacting providers."""
    current = today or today_utc()
    root = path.resolve()
    if not root.exists():
        raise ValueError(f"audit source path does not exist: {path}")
    files, file_selection, file_selection_reason = _project_files(root)
    references = []
    unreadable = 0
    for file_path in files:
        # One file that is not UTF-8 or may not be read leaves the rest audited.
        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            unreadable += 1
            continue
        shown = display_path(
            file_path.relative_to(root) if root.is_dir() else file_path
        )
        references.extend(
            _references_for_lines(lines, file_path.suffix, shown, current)
        )
    scanned = len(files) - unreadable
    summary = _summary_fields(references)
    if not scanned:
        # A scan that read no file has no evidence; unknown is never a pass.
        summary["decision"] = "inconclusive"
    return {
        "root": display_path(root),
        "network_accessed": False,
        "files_scanned": scanned,
        "file_selection": file_selection,
        "file_selection_reason": file_selection_reason,
        "files_unreadable": unreadable,
        "references": references,
        **summary,
    }


def _project_files(root: Path) -> tuple[list[Path], str, str | None]:
    """Source files under root, how they were selected, and why Git was not used."""
    if root.is_file():
        return [root], "file", None
    listed = _git_files(root)
    reason: str | None = None
    if isinstance(listed, str):
        selected, file_selection, reason = list(root.rglob("*")), "filesystem", listed
    else:
        selected, file_selection = listed, "git"
    # The skip list applies to tracked files too, so Git selection removes only
    # ignored files. It matches below root only: a project inside a directory
    # named results is still read. A symlink may point anywhere; only files
    # that resolve inside root are read.
    files = sorted(
        candidate
        for candidate in selected
        if candidate.suffix.casefold() in _SOURCE_SUFFIXES
        and not any(part in _SKIP_PARTS for part in candidate.relative_to(root).parts)
        and candidate.is_file()
        and candidate.resolve().is_relative_to(root)
    )
    return files, file_selection, reason


def _git_files(root: Path) -> list[Path] | str:
    """Tracked and unignored files under root, or why Git cannot select them."""
    try:
        prefix = run_git(root, "rev-parse", "--show-prefix").stdout.strip()
        # Below the top of a work tree an ignored root lists no file at all, as
        # for a project kept inside a dotfiles repository that ignores "*".
        if prefix:
            ignored = run_git(root, "check-ignore", "-q", ".", check=False)
            if ignored.returncode == 0:
                return "the path is ignored by its enclosing git repository"
        paths: list[str] = []
        # Submodule files are tracked by their own repository; --others cannot
        # recurse, so untracked files are listed by a second call.
        for arguments in (
            ["--cached", "--recurse-submodules"],
            ["--others", "--exclude-standard"],
        ):
            listed = run_git(root, "ls-files", "-z", *arguments).stdout
            paths.extend(item for item in listed.split("\0") if item)
    except FileNotFoundError:
        return "git is not installed"
    except OSError:
        return "git could not be started"
    except subprocess.CalledProcessError as exc:
        return f"git could not list files: {_git_failure(exc.stderr, exc.returncode)}"
    except ValueError as exc:
        return f"git could not list files: {exc}"
    files: list[Path] = []
    for item in dict.fromkeys(paths):
        relative = Path(item)
        if relative.is_absolute() or ".." in relative.parts:
            continue
        # --others reports an untracked nested repository as "dir/" without
        # its files; those are selected as the filesystem walk selects them.
        files.extend(
            (root / relative).rglob("*") if item.endswith("/") else [root / relative]
        )
    return files


def _git_failure(stderr: str | None, returncode: int) -> str:
    """Git's first error line: printable, without secrets, capped in length."""
    lines = [line for line in (stderr or "").splitlines() if line.strip()]
    if not lines:
        return f"exit status {returncode}"
    printable = "".join(character for character in lines[0] if character.isprintable())
    line = redact_secrets(printable.strip().removeprefix("fatal: "))
    if len(line) > _GIT_REASON_LIMIT:
        line = line[: _GIT_REASON_LIMIT - 1] + "…"
    return str(line)


def audit_source_text(
    path: Path, text: str, today: date | None = None
) -> dict[str, Any]:
    """Find literal model IDs in supplied source text without writing it to disk."""
    references = _references_for_lines(
        text.splitlines(), path.suffix, display_path(path), today or today_utc()
    )
    return {
        "root": display_path(path),
        "network_accessed": False,
        "files_scanned": 1,
        "references": references,
        **_summary_fields(references),
    }


def _references_for_lines(
    lines: list[str], suffix: str, display_path: str, today: date
) -> list[dict[str, Any]]:
    references = []
    for line_number, line in enumerate(lines, 1):
        candidates = [match.group("value") for match in _QUOTED.finditer(line)]
        if suffix.casefold() in {".yaml", ".yml"}:
            yaml_content = line.split("#", 1)[0]
            candidates.extend(
                match.group("value") for match in _YAML_MODEL.finditer(yaml_content)
            )
        # A model ID found twice on one line is one reference.
        for model in dict.fromkeys(candidates):
            if not _MODEL_PREFIX.match(model):
                continue
            provider = _provider_for(model)
            catalog_model = model.rsplit("/", 1)[-1]
            key = (provider, catalog_model) if provider else None
            priced = key in PUBLIC_PRICING if key else False
            references.append(
                {
                    "path": display_path,
                    "line": line_number,
                    "provider": provider,
                    "model": model,
                    "status": "pricing_known" if priced else "pricing_unknown",
                    "confidence": "official_snapshot" if priced else "unknown",
                    "retirement": retirement_verdict(provider, model, today),
                }
            )
    return references
