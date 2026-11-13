# Data files

**Last reviewed:** 2026-11-13 · **As of:** v2.25.3

Recorded observations and ratings that other pages cite. Nothing here is read at runtime.

| File | What it holds |
|---|---|
| `model-comparison-*.json` | One eight-case measured run per file: method, totals and one row per model (validity, latency, tokens, estimated cost). The [observed model comparison](../guides/observed-model-comparison.md) is built from them. |
| `gemini-4-hydrogen-smoke-2026-11-13.json` | One live smoke request for `gemini-4-hydrogen`: the request checks that applied and the reported cost against the bundled rates. |
| `model-importance.json` | A tier and a one-line reason for every model in the bundled pricing and retirement data. |

## Model importance

`model-importance.json` rates each bundled model so it is clear how much each one is tested.

| Tier | Which models |
|---|---|
| 1 | Current-generation general-purpose text models a team would pick today: the flagship and main sizes of OpenAI, Anthropic, Google Gemini and xAI, and the newest flagship of each other natively supported provider. These are the models the measured comparison shows. |
| 2 | Other generally available text models: dated snapshots, older generations still active, specialised variants. |
| 3 | Previews, restricted or invite-only access, deprecated or retiring models, and OpenRouter-only models. |

Each row has `provider`, `model`, `tier` and `reason`. A test (`tests/test_model_importance.py`) fails when a bundled model has no row or a row names a model that is not bundled.
