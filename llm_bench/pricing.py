from __future__ import annotations

from typing import Any


# Standard synchronous API rates in USD per million tokens. Provider catalogs
# do not consistently return prices, so these public rates fill that gap.
# OpenRouter prices remain dynamic and take precedence when its catalog returns
# them. Gemini 3.1 Pro uses the <=200k-input tier.
PUBLIC_PRICING: dict[tuple[str, str], tuple[float, float, str]] = {
    ("openai", "gpt-5.5"): (5.0, 30.0, "2026-07-09"),
    ("openai", "gpt-5.4-mini"): (0.75, 4.5, "2026-07-09"),
    ("openai", "gpt-5.4-nano"): (0.2, 1.25, "2026-07-09"),
    ("openai", "gpt-4.1"): (2.0, 8.0, "2026-07-09"),
    ("openai", "gpt-4.1-mini"): (0.4, 1.6, "2026-07-09"),
    ("openai", "gpt-4.1-nano"): (0.1, 0.4, "2026-07-09"),
    ("gemini", "gemini-3.1-pro-preview"): (2.0, 12.0, "2026-07-09"),
    ("gemini", "gemini-3.5-flash"): (1.5, 9.0, "2026-07-09"),
    # Introductory Sonnet 5 rate through 2026-08-31.
    ("anthropic", "claude-sonnet-5"): (2.0, 10.0, "2026-07-09"),
    ("anthropic", "claude-fable-5"): (10.0, 50.0, "2026-07-09"),
    ("anthropic", "claude-opus-4-8"): (5.0, 25.0, "2026-07-09"),
    ("xai", "grok-4.3"): (1.25, 2.5, "2026-07-09"),
}


def apply_public_pricing(model: dict[str, Any]) -> dict[str, Any]:
    if (
        model.get("input_cost_per_million") is not None
        and model.get("output_cost_per_million") is not None
    ):
        return model
    key = (model.get("provider", "openai_compatible"), model["model"])
    pricing = PUBLIC_PRICING.get(key)
    if pricing is None:
        return model
    input_price, output_price, as_of = pricing
    return {
        **model,
        "input_cost_per_million": input_price,
        "output_cost_per_million": output_price,
        "pricing_metadata": {
            "source": "public provider pricing",
            "as_of": as_of,
        },
    }
