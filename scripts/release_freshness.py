"""Real-clock release gate: the bundled examples are priced and retirement-current.

The unit suite pins its clock, so it cannot catch snapshot expiry. `make
release-freshness` runs this on the real date before a release build; `--today`
replays the gate for another day. Every failing example is printed with its
reasons, and any failure exits 1.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from llm_preflight.catalog import resolve_models
from llm_preflight.features import (
    apply_model_aliases,
    apply_provider_presets,
)
from llm_preflight.pricing import pricing_coverage_report
from llm_preflight.retirements import today_utc
from llm_preflight.runner import load_config, validate_config_validations
from llm_preflight.source_audit import audit_source

EXAMPLES = (
    "current-model-comparison",
    "gpt-6.1-terra",
    "glm-5.3-flash",
    "glm-5.3-flashx",
    "kimi-k3.1-pro",
    "kimi-k3.1-pro-highspeed",
    "minimax-m3.1-flash",
    "minimax-m3",
    "mistral-large-4",
    "cohere-command-a-plus",
    "mythos-5.1-restricted",
    "native-chinese-smoke",
    "approved-smoke",
    "gemini-4-argon",
    "cross-provider-run",
    "frontier-candidates",
    "flagship-comparison",
    "gpt-6.1-sol-comparison",
    "anthropic-5.5-comparison",
    "anthropic-5.5-checks",
    "glm-5.3-comparison",
    "glm-5.3-openrouter-comparison",
)
_FLAGGED = {"retired", "retiring", "stale"}


def pricing_reasons(path: Path, today: date) -> list[str]:
    """The `--pricing-check` verdict for one example: empty when it passes."""
    config = apply_provider_presets(apply_model_aliases(load_config(path)))
    validate_config_validations(config)
    report = pricing_coverage_report(
        resolve_models(config),
        today=today,
        require_current_pricing=bool(config.get("require_current_pricing")),
    )
    if report["enforcement_ok"]:
        return []
    return [
        f"{warning['provider']}/{warning['model']}: {warning['message']}"
        for warning in report["warnings"]
    ] or ["pricing coverage is incomplete"]


def retirement_reasons(path: Path, today: date) -> tuple[str, list[str]]:
    """The `--audit-source --ci` decision and each flagged model reference."""
    audit = audit_source(path, today=today)
    return audit["decision"], [
        f"{item['path']}:{item['line']}: {item['model']} — "
        f"{item['retirement']['status']}: {item['retirement']['reason']}"
        for item in audit["references"]
        if item["retirement"]["status"] in _FLAGGED
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        help="check as of this YYYY-MM-DD instead of today's UTC date",
    )
    args = parser.parse_args(argv)
    today = args.today or today_utc()
    failed = False
    for example in EXAMPLES:
        label = f"examples/{example}.json"
        reasons = pricing_reasons(ROOT / label, today)
        print(f"{'FAIL' if reasons else 'ok'} pricing-check {label}")
        print("".join(f"  {reason}\n" for reason in reasons), end="")
        failed = failed or bool(reasons)
    decision, reasons = retirement_reasons(ROOT / "examples", today)
    blocked = decision in {"fail", "inconclusive"}
    print(f"{'FAIL' if blocked else 'ok'} audit-source examples: {decision}")
    print("".join(f"  {reason}\n" for reason in reasons), end="")
    failed = failed or blocked
    print(f"Release freshness on {today.isoformat()}: {'fail' if failed else 'pass'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
