from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from .pricing import PUBLIC_PRICING
from .retirements import retirement_verdict, snapshot_summary, worst_decision

_RETIREMENT_FINDINGS = {"retired", "retiring", "stale"}
_CONFIDENCE = "limited_static_pricing_and_retirement"
_NOTES = [
    "Only literal model IDs are reported; dynamic model selection requires review.",
    "Pricing unknown means the bundled static pricing table has no matching entry; it is advisory, not a catalog verdict.",
    "Retirement verdicts come from the bundled snapshot of the official anthropic and openai deprecation pages for text-generation models; unknown means no row and is not a verdict.",
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
        "next_commands": list(
            dict.fromkeys(
                item["retirement"]["next_command"]
                for item in references
                if "next_command" in item["retirement"]
            )
        ),
        "retirement_snapshot": snapshot_summary(),
        "confidence": _CONFIDENCE,
        "notes": list(_NOTES),
    }


def audit_source(path: Path, today: date | None = None) -> dict[str, Any]:
    """Find literal model IDs without importing project code or contacting providers."""
    current = today or date.today()
    root = path.resolve()
    if not root.exists():
        raise ValueError(f"audit source path does not exist: {path}")
    files = (
        [root]
        if root.is_file()
        else sorted(
            candidate
            for candidate in root.rglob("*")
            if candidate.is_file()
            and candidate.suffix.casefold() in _SOURCE_SUFFIXES
            and not any(part in _SKIP_PARTS for part in candidate.parts)
        )
    )
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
        "references": references,
        **_summary_fields(references),
    }


def audit_source_text(
    path: Path, text: str, today: date | None = None
) -> dict[str, Any]:
    """Find literal model IDs in supplied source text without writing it to disk."""
    references = _references_for_lines(
        text.splitlines(), path.suffix, str(path), today or date.today()
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
