# Code map

Where code lives, and what each area is responsible for.

| Path | Responsibility |
|---|---|
| `llm_preflight/` | the package: checks, providers, reporting, machine decisions, and the two console entry points |
| `tests/` | the suite; every behaviour change starts here per the development contract above |
| `docs/` | published documentation — guides, reference, operations, automation |
| `examples/` | runnable configuration samples referenced by the guides |
| `requirements/` | pinned dependency sets for development and CI |
| `.github/` | CI workflows and issue templates |

Entry points, declared in `pyproject.toml`:

| Command | Module |
|---|---|
| `llm-preflight` | `llm_preflight.__main__:main` |
| `llm-preflight-mcp` | `llm_preflight.mcp:main` |
