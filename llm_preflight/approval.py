"""Bounded local approval receipts that never authorize provider work."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .redaction import redact_secrets


def create_approval_receipt(
    plan: dict[str, Any], *, note: str, expires_at: str, now: datetime | None = None
) -> dict[str, Any]:
    """Record a human-reviewed plan without granting execution authority."""
    if not isinstance(note, str) or not note.strip():
        raise ValueError("approval note must be a non-empty string")
    current = now or datetime.now(timezone.utc)
    expiry = _timestamp(expires_at, "approval expiry")
    if expiry <= current:
        raise ValueError("approval expiry must be in the future")
    safe_plan = redact_secrets(plan)
    return {
        "schema_version": 1,
        "kind": "llm-preflight-approval-receipt",
        "created_at": current.isoformat(),
        "expires_at": expiry.isoformat(),
        "note": note.strip(),
        "plan_sha256": _fingerprint(safe_plan),
        "bounds": {
            "possible_requests": plan.get("possible_requests"),
            "maximum_estimated_cost_usd": plan.get("maximum_estimated_cost_usd"),
        },
        "recorded_human_approval": True,
        "authorizes_paid_run": False,
    }


def verify_approval_receipt(
    receipt: Any, plan: dict[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    """Check receipt integrity against the current plan and wall-clock expiry."""
    if not isinstance(receipt, dict) or receipt.get("schema_version") != 1:
        return _verification("invalid", "receipt schema is not supported")
    try:
        expiry = _timestamp(receipt.get("expires_at"), "receipt expiry")
    except ValueError:
        return _verification("invalid", "receipt expiry is invalid")
    current = now or datetime.now(timezone.utc)
    if expiry <= current:
        return _verification("expired", "receipt has expired")
    if receipt.get("plan_sha256") != _fingerprint(redact_secrets(plan)):
        return _verification(
            "mismatch", "receipt does not match the current no-spend plan"
        )
    return _verification(
        "recorded", "receipt matches the current no-spend plan and has not expired"
    )


def write_approval_receipt(
    path: Path, receipt: dict[str, Any], *, replace: bool
) -> None:
    """Write one local receipt atomically with owner-only permissions."""
    if path.exists() and not replace:
        raise ValueError(
            f"approval receipt already exists: {path}; use --replace-approval-receipt"
        )
    if path.is_symlink():
        raise ValueError("approval receipt path must not be a symbolic link")
    parent_exists = path.parent.exists()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not parent_exists:
        path.parent.chmod(0o700)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", text=True
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(receipt, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
        path.chmod(0o600)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def load_approval_receipt(path: Path) -> dict[str, Any]:
    """Read a local receipt without interpreting it as execution authority."""
    if path.is_symlink():
        raise ValueError("approval receipt path must not be a symbolic link")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(  # noqa: TRY004 - public receipt-validation error
            "approval receipt must be a JSON object"
        )
    return payload


def _verification(state: str, reason: str) -> dict[str, Any]:
    return {
        "ok": state == "recorded",
        "state": state,
        "reason": reason,
        "authorizes_paid_run": False,
    }


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be an ISO-8601 timestamp")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if timestamp.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return timestamp.astimezone(timezone.utc)


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(encoded.encode()).hexdigest()
