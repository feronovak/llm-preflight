# Code map

**Last reviewed:** 2026-09-09 · **As of:** v2.14.0

Where code lives, and what each area is responsible for.

| Path | Responsibility |
|---|---|
| `llm_preflight/` | the package: change planning, contract checks, providers, reporting, machine decisions, and the two console entry points |
| `llm_preflight/images.py` | validate and materialize bounded local or caller-supplied image inputs without retaining bytes in results |
| `llm_preflight/env.py` | resolve and load one explicitly selected project env file without executing shell code or overwriting shell values |
| `tests/` | the suite; every behaviour change starts here per the development contract above |
| `docs/` | published documentation — guides, reference, operations, automation |
| `examples/` | runnable configuration samples referenced by the guides |
| `requirements/` | pinned dependency sets for development and CI |
| `.github/` | CI workflows and safe issue forms for provider breakage and pricing drift |
| `action.yml` | GitHub Marketplace composite action; no-spend preflight checks by default |
| `server.json` | MCP Registry metadata for the PyPI-distributed local stdio server |
| `plugins/llm-preflight/` | repository-contained Codex plugin and safe-preflight skill |

Entry points, declared in `pyproject.toml`:

| Command | Module |
|---|---|
| `llm-preflight` | `llm_preflight.__main__:main` |
| `llm-preflight-mcp` | `llm_preflight.mcp:main` |
