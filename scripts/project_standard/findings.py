"""The one shared vocabulary. Every checker speaks Findings and nothing else.

Severity is data, never control flow: a check reports what it saw, and the
runner alone decides the exit code. `skipped` exists because a check that did
not run must never read as a check that passed.
"""

from dataclasses import dataclass, field
from typing import Optional

ERROR = "error"
WARN = "warn"
SKIPPED = "skipped"

SEVERITIES = (ERROR, WARN, SKIPPED)


@dataclass(frozen=True)
class Finding:
    check: str
    severity: str
    message: str
    path: Optional[str] = None
    line: Optional[int] = None

    def __post_init__(self):
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity: {self.severity!r}")

    @property
    def location(self) -> str:
        if self.path and self.line:
            return f"{self.path}:{self.line}"
        return self.path or ""

    def render(self) -> str:
        where = f"{self.location} — " if self.location else ""
        return f"[{self.check}] {where}{self.message}"

    def as_dict(self) -> dict:
        return {
            "check": self.check,
            "severity": self.severity,
            "message": self.message,
            "path": self.path,
            "line": self.line,
        }


def error(check: str, message: str, path=None, line=None) -> Finding:
    return Finding(check, ERROR, message, path, line)


def warn(check: str, message: str, path=None, line=None) -> Finding:
    return Finding(check, WARN, message, path, line)


def skipped(check: str, message: str) -> Finding:
    return Finding(check, SKIPPED, message)


@dataclass
class Report:
    findings: list = field(default_factory=list)
    summary: str = ""

    @property
    def errors(self):
        return [f for f in self.findings if f.severity == ERROR]

    @property
    def warns(self):
        return [f for f in self.findings if f.severity == WARN]

    @property
    def skips(self):
        return [f for f in self.findings if f.severity == SKIPPED]

    @property
    def exit_code(self) -> int:
        return 1 if self.errors else 0

    def ranked(self):
        order = {ERROR: 0, WARN: 1, SKIPPED: 2}
        return sorted(self.findings, key=lambda f: (order[f.severity],
                                                    _num(f.check), f.check))


def _num(check: str) -> float:
    digits = "".join(c for c in check if c.isdigit())
    return float(digits) if digits else 999.0
