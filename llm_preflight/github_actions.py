"""The GitHub Actions run identity a result and its record carry.

A run reads it when it starts and writes it into the result; `attest` reads it
again and keeps it only when both name the same run. It holds names and
numbers only, never a token.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, TypeGuard

# Each variable that names a run, with its key in a result or record.
GITHUB_VARIABLES = (
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


def ci_identity(environ: Mapping[str, str]) -> dict[str, str] | None:
    """The GitHub Actions run identity, or None outside CI.

    A partial or malformed identity is refused rather than recorded as local,
    so a misconfigured workflow cannot silently produce a record the gate
    ignores.
    """
    values = {key: environ.get(name, "") for name, key in GITHUB_VARIABLES}
    if not any(values.values()):
        return None
    missing = [name for name, key in GITHUB_VARIABLES if not values[key]]
    if missing:
        raise ValueError(
            f"incomplete GitHub Actions identity: {', '.join(missing)} not set; "
            "unset every GITHUB_* run variable to attest a local record"
        )
    malformed = [
        name for name, key in GITHUB_VARIABLES if not valid_ci_field(key, values[key])
    ]
    if malformed:
        raise ValueError(f"malformed GitHub Actions identity: {', '.join(malformed)}")
    return values


def valid_ci_identity(value: Any) -> TypeGuard[dict[str, str]]:
    """Exactly the six run fields, each well formed."""
    return (
        isinstance(value, dict)
        and set(value) == {key for _, key in GITHUB_VARIABLES}
        and all(valid_ci_field(key, item) for key, item in value.items())
    )


def valid_ci_field(key: str, value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if key == "workflow":
        return 0 < len(value) <= _MAX_WORKFLOW_LENGTH and value.isprintable()
    if key == "repository" and {".", ".."} & set(value.split("/")):
        return False
    return _CI_FIELDS[key].fullmatch(value) is not None
