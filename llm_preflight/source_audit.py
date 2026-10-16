from __future__ import annotations

import re
import shutil

# _git_files uses an absolute executable and argument arrays.
import subprocess  # nosec B404
from datetime import date
from pathlib import Path
from typing import Any

from .pricing import PUBLIC_PRICING
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


def audit_source(path: Path, today: date | None = None) -> dict[str, Any]:
    """Find literal model IDs without importing project code or contacting providers."""
    current = today or today_utc()
    root = path.resolve()
    if not root.exists():
        raise ValueError(f"audit source path does not exist: {path}")
    files, file_selection = _project_files(root)
    references = []
    for file_path in files:
        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        display_path = (
            str(file_path.relative_to(root)) if root.is_dir() else str(file_path)
        )
        references.extend(
            _references_for_lines(lines, file_path.suffix, display_path, current)
        )
    unique = list(
        dict.fromkeys(
            (item["path"], item["line"], item["model"]) for item in references
        )
    )
    references = [
        next(
            item
            for item in references
            if (item["path"], item["line"], item["model"]) == key
        )
        for key in unique
    ]
    return {
        "root": str(root),
        "network_accessed": False,
        "files_scanned": len(files),
        "file_selection": file_selection,
        "references": references,
        **_summary_fields(references),
    }


def _project_files(root: Path) -> tuple[list[Path], str]:
    """Source files under root and how they were selected: file, git or filesystem."""
    if root.is_file():
        return [root], "file"
    selected = _git_files(root)
    file_selection = "git"
    if selected is None:
        selected = list(root.rglob("*"))
        file_selection = "filesystem"
    # The skip list applies to tracked files too, so Git selection removes only
    # ignored files. A symlink may point anywhere; only files that resolve
    # inside root are read.
    files = sorted(
        candidate
        for candidate in selected
        if candidate.suffix.casefold() in _SOURCE_SUFFIXES
        and not any(part in _SKIP_PARTS for part in candidate.parts)
        and candidate.is_file()
        and candidate.resolve().is_relative_to(root)
    )
    return files, file_selection


def _git_files(root: Path) -> list[Path] | None:
    """Tracked and unignored files under root, or None outside a Git work tree."""
    executable = shutil.which("git")
    if executable is None:
        return None
    git = [str(Path(executable).resolve()), "-C", str(root), "ls-files", "-z"]
    paths: list[str] = []
    # Submodule files are tracked by their own repository; --others cannot
    # recurse, so untracked files are listed by a second call.
    for arguments in (
        ["--cached", "--recurse-submodules"],
        ["--others", "--exclude-standard"],
    ):
        try:
            # No shell is used and every argument is fixed.
            completed = subprocess.run(  # nosec B603
                [*git, *arguments],
                check=True,
                text=True,
                capture_output=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        paths.extend(item for item in completed.stdout.split("\0") if item)
    return [
        root / relative
        for relative in map(Path, dict.fromkeys(paths))
        if not relative.is_absolute() and ".." not in relative.parts
    ]


def audit_source_text(
    path: Path, text: str, today: date | None = None
) -> dict[str, Any]:
    """Find literal model IDs in supplied source text without writing it to disk."""
    references = _references_for_lines(
        text.splitlines(), path.suffix, str(path), today or today_utc()
    )
    return {
        "root": str(path),
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
        for model in candidates:
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
    unique = list(
        dict.fromkeys(
            (item["path"], item["line"], item["model"]) for item in references
        )
    )
    return [
        next(
            item
            for item in references
            if (item["path"], item["line"], item["model"]) == key
        )
        for key in unique
    ]
