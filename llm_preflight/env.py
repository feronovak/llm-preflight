from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


def resolve_config_env_file(
    config_path: Path,
    config: dict[str, Any],
    *,
    explicit: Path | None = None,
    no_env_file: bool = False,
) -> tuple[Path | None, str]:
    """Resolve one selected env file without searching for credentials.

    An explicit CLI path preserves the established behaviour. A config reference
    must be a relative path contained by the benchmark configuration directory.
    """
    if no_env_file:
        return None, "disabled"
    if explicit is not None:
        return explicit, "explicit"
    config_dir = config_path.resolve().parent
    reference = config.get("env_file")
    if reference is None:
        return (config_dir / ".env.production").resolve(), "default"
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("env_file must be a non-empty relative path")
    candidate = Path(reference.replace("\\", "/"))
    if candidate.is_absolute():
        raise ValueError("env_file must be relative to the config directory")
    resolved = (config_dir / candidate).resolve()
    if resolved != config_dir and config_dir not in resolved.parents:
        raise ValueError("env_file must stay within the config directory")
    return resolved, "config"


def load_env_file(path: Path) -> set[str]:
    """Load simple KEY=value entries without executing shell code."""
    loaded: set[str] = set()
    if not path.exists():
        return loaded
    for line_number, raw_line in enumerate(path.read_text().splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"{path}:{line_number}: expected KEY=value")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"{path}:{line_number}: invalid variable name {key!r}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = re.sub(r"\s+#.*$", "", value).strip()
        if key not in os.environ:
            os.environ[key] = value
            loaded.add(key)
    return loaded
