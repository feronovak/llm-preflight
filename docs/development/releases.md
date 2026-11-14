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

A release that only refreshes model data is tagged and published without a
manual step. This section describes the two release paths and the check that
chooses between them.

### Two paths

- **Data-only release.** `.github/workflows/auto-release.yml` classifies the
  range, tags it and publishes it, as described below. It acts only while the
  repository variable `AUTO_RELEASE` is `on`; otherwise it reports its verdict
  in the run summary and stops.
- **Any other release.** No tag is created. The maintainer tags the release and
  publishes it as before, and `release.yml` runs after the GitHub release.

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
- the data documentation: `docs/data/`, the measured-model images and guides
  (`observed-model-comparison.md`, `current-snapshots.md`), `visual-assets.md`,
  `docs/DOCMAP.md`, `docs/index.md`, `README.md` and the data tests
  (`test_pricing.py`, `test_retirements.py`, `test_model_updates.py`,
  `test_documentation.py`, `test_package.py`);
- substituting the previous release's version in `action.yml`, `examples/`,
  other documentation pages and `tests/test_distribution.py`.

A pin PR must stay a pure substitution. Each changed line differs from the
base only in versions, and every new version equals the version of the tag the
range starts from. Write pinned text so it names the current pin and nothing
else: do not add or move an older version (for example a history of earlier
release defaults), because that would make the next range fail the check.

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
tuple or list, so a model name can be added to an existing list. The shape
must come from the same table in the base. Comments do not count as changes,
but an encoding declaration or a byte-order mark does: the files are parsed as
Python reads them, and any encoding other than UTF-8 does not qualify. A deleted or renamed data file does not qualify.

The workflow runs the classifier from the base tag, never from the head, so a
range cannot approve its own rules. The first release that contains the
classifier is therefore still tagged by the maintainer.

### What the workflow does

1. It starts when the `tests` workflow succeeds for a push to `main`, and
   continues only when that commit changed the `pyproject.toml` version: the
   merged release-prep commit, which has already passed review.
2. It waits up to 20 minutes for the seven required checks on that commit.
3. It runs the base tag's classifier. A base tag that has no classifier, or a
   range that does not qualify, ends the run with the reasons in the summary
   and no tag.
4. For a qualifying range, the `release` job (the only job with write access)
   creates the tag `vX.Y.Z` at that exact commit; an existing tag that points
   elsewhere fails the job. It then dispatches `testpypi.yml` and waits for it,
   creates the GitHub release from the `CHANGELOG.md` section, and dispatches
   `release.yml` on the tag. `release.yml` publishes to PyPI and the MCP
   Registry as for a manual release. A tag, a release or a run created with the
   workflow token does not start other workflows by itself, which is why the
   two dispatches exist.

`release.yml` runs from a manual dispatch only on a `v*` tag; on a branch its
`build` job is skipped. It still checks that the tag equals the package
version.

The first release that contains the classifier is tagged by the maintainer,
because its base tag has no classifier. Automatic releases start with the one
after it.

### If an automatic release fails

A failure after the tag leaves the tag in place and publishes nothing more. A
red `testpypi.yml` or `release.yml` run is recovered by re-running its failed
jobs; the registry step has its own recovery path above. A failed job before
the tag (checks not green, classifier error) creates nothing: fix the cause and
re-run the failed `auto-release` run, or tag by hand.

### Maintainer steps

These are repository settings that the workflow cannot change and this page
does not verify:

- Allow the GitHub Actions app to create `v*` tags: restrict tag creation in
  one ruleset with that bypass, and keep update and deletion restricted in a
  second ruleset without it, so release tags stay immutable.
- Set the repository variable `AUTO_RELEASE` to `on`.
- Check whether the `pypi` environment has required reviewers. If it has, an
  automatic release waits for that approval at the PyPI job.
