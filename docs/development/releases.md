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
