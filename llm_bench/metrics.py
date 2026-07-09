from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any


def percentile(values: Iterable[float], p: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * p
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def stats(values: Iterable[float]) -> dict[str, float | None]:
    data = list(values)
    if not data:
        return {"mean": None, "min": None, "p50": None, "p95": None, "max": None}
    return {
        "mean": sum(data) / len(data),
        "min": min(data),
        "p50": percentile(data, 0.50),
        "p95": percentile(data, 0.95),
        "max": max(data),
    }


def summarize(samples: list[dict[str, Any]], model: dict[str, Any]) -> dict[str, Any]:
    successful = [sample for sample in samples if sample["ok"]]

    def numbers(field: str) -> list[float]:
        return [
            float(sample[field])
            for sample in successful
            if sample.get(field) is not None
        ]

    input_tokens = sum(numbers("input_tokens"))
    output_tokens = sum(numbers("output_tokens"))
    input_price = model.get("input_cost_per_million")
    output_price = model.get("output_cost_per_million")
    cost = None
    if input_price is not None and output_price is not None:
        cost = (
            input_tokens * float(input_price) / 1_000_000
            + output_tokens * float(output_price) / 1_000_000
        )

    return {
        "requests": len(samples),
        "successful": len(successful),
        "failed": len(samples) - len(successful),
        "success_rate": len(successful) / len(samples) if samples else 0,
        "latency_seconds": stats(numbers("latency_seconds")),
        "ttft_seconds": stats(numbers("ttft_seconds")),
        "output_tokens_per_second": stats(numbers("output_tokens_per_second")),
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "estimated_cost_usd": cost,
    }
