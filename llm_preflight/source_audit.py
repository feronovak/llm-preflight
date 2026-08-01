from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .pricing import PUBLIC_PRICING


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
    r"^(?:(?:anthropic|openai|google|xai|x-ai)/)?(?:gpt-[A-Za-z0-9]|claude-[A-Za-z0-9]|gemini-[A-Za-z0-9]|grok-[A-Za-z0-9]|o[1-9](?:-|$))",
    re.I,
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
    return None


def audit_source(path: Path) -> dict[str, Any]:
    """Find literal model IDs without importing project code or contacting providers."""
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
        for line_number, line in enumerate(lines, 1):
            candidates = [match.group("value") for match in _QUOTED.finditer(line)]
            if file_path.suffix.casefold() in {".yaml", ".yml"}:
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
                        "path": str(file_path.relative_to(root))
                        if root.is_dir()
                        else str(file_path),
                        "line": line_number,
                        "provider": provider,
                        "model": model,
                        "status": "pricing_known" if priced else "pricing_unknown",
                        "confidence": "official_snapshot" if priced else "unknown",
                    }
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
    findings = [item for item in references if item["status"] != "pricing_known"]
    return {
        "root": str(root),
        "network_accessed": False,
        "files_scanned": len(files),
        "references": references,
        "findings": findings,
        "ok": True,
        "confidence": "limited_static_pricing",
        "notes": [
            "Only literal model IDs are reported; dynamic model selection requires review.",
            "Pricing unknown means the bundled static pricing table has no matching entry; it is advisory, not a catalog or retirement verdict.",
        ],
    }
