# Release workflow

This page is for maintainers and contributors who need to know what a release
does after the tag. It covers the jobs of `.github/workflows/release.yml`, the
registry recovery path and where the pinned versions live.

## What a release runs

Publishing a GitHub release for a `v*` tag starts the `release` workflow. The
jobs run in this order:

1. `build` checks that the tag equals `v<__version__>`, runs
   `make release-freshness`, builds the wheel and sdist and uploads them.
2. `pypi-publish` publishes them to PyPI. It runs in the `pypi` environment, so
   it waits for the maintainer's approval. It is the only job with a PyPI
   trusted-publishing identity.
3. `mcp-registry-publish` publishes `server.json` to the MCP Registry. It needs
   `pypi-publish` and runs only for `v*` tags. It has no environment, so it
   adds no second approval; the `pypi` approval already gates it.

`mcp-registry-publish` waits until PyPI serves the released version, downloads
`mcp-publisher`, checks its SHA-256 against the value pinned in the workflow,
logs in with `mcp-publisher login github-oidc` and runs
`mcp-publisher publish server.json`. GitHub OIDC replaces a stored token: the
job alone holds `id-token: write`, and the workflow-level permission stays
`contents: read`.

## If the registry publish fails

The job turns red and PyPI stays published. Open the run and choose
**Re-run failed jobs**: that reruns only `mcp-registry-publish`, with no new
approval. The registry rejects a version it already has, so a rerun after a
successful publish fails; the job does not retry on its own. If the rerun
cannot succeed, run `mcp-publisher login github` and
`mcp-publisher publish server.json` by hand from a checkout of the tag.

## Where the pins live

- `MCP_PUBLISHER_VERSION` and `MCP_PUBLISHER_SHA256` in the
  `mcp-registry-publish` job. To update the tool, download the release asset,
  compute its `sha256sum` yourself and change both values in one commit.
- The published package version in `action.yml` (`package-version` default),
  `examples/` and the documentation.

The Action smoke workflow (`.github/workflows/action-smoke.yml`) passes no
version. It installs the `action.yml` default, so a pin PR changes nothing
under `.github/`.

## Automatic maintenance releases

A release that only refreshes model data can be tagged without a manual step.
This section describes the check that decides it. The workflow that acts on the
result is planned and not active yet: until it lands, every release is still
tagged by the maintainer.

### What qualifies

A release qualifies when every change since the previous `v*` tag is one of:

- rows and review dates in the data tables of `llm_preflight/pricing.py`
  (`PUBLIC_PRICING`, `_PROVIDER_PRICING_PAGES`, `_MODEL_PRICING_PAGES`,
  `PUBLIC_PRICING_CHANGES`, `PUBLIC_PRICING_DETAILS`) and of
  `llm_preflight/retirements.py` (`_ANTHROPIC`, `_OPENAI`, `_GEMINI`,
  `_REVIEWED` and the three `*_DEPRECATIONS_URL` constants);
- the version files, as a patch bump of the previous tag: `pyproject.toml`,
  `llm_preflight/__init__.py`, `server.json` and the Codex plugin manifest,
  all naming the same version, with a dated `CHANGELOG.md` heading for it;
- the data documentation: `docs/data/`, the measured-model images and guides,
  `README.md` and the data tests (`test_pricing.py`, `test_retirements.py`,
  `test_model_updates.py`, `test_documentation.py`, `test_package.py`);
- substituting the previous release's version in `action.yml`, `examples/`,
  other documentation pages and `tests/test_distribution.py`.

Any other change does not qualify, including a new feature, a `Breaking:`
change of behaviour, anything under `.github/` or `scripts/`, and a dependency
change. Such a release keeps the maintainer's `tag`.

### How the check works

`scripts/release_classify.py --base <tag> --head <sha>` decides from the diff,
without judgement. It prints JSON with `qualifies`, `base`, `head`, `version`
and `reasons`, and exits 0 when the range qualifies, 1 when it does not and 2
on an error such as an unreadable range or a file that does not parse.

For the two Python data files it parses the base and head versions, blanks the
value of each data table and requires the rest of the module to be identical,
so a changed function, constant, import or annotation fails. Each table must be
assigned exactly once, and its new value may contain only literals, other
tables and calls to the row builders. A comprehension qualifies only when it
has the same shape as one in the base and its source is unchanged or a literal
tuple or list, so a model name can be added to an existing list. Comments do
not count as changes. A deleted or renamed data file does not qualify.

The workflow runs the classifier from the base tag, never from the head, so a
range cannot approve its own rules. The first release that contains the
classifier is therefore still tagged by the maintainer.
