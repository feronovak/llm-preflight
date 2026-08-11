# Development Contract

This project uses test-driven development with a strict red/green/refactor loop.

For every behavior change:

1. Red: add or modify the smallest test that describes the desired externally
   observable behavior. Run that focused test and confirm it fails for the
   expected reason.
2. Green: implement the smallest production change that makes the focused test
   pass. Do not weaken assertions to obtain a passing result.
3. Verify: run the complete test suite and confirm all tests pass.
4. Refactor: improve structure only while the full suite stays green.

Bug fixes must begin with a regression test that reproduces the bug. Provider
integrations must use deterministic mocked protocol fixtures; live API calls are
optional integration verification and must never be required by the unit suite.

Commands:

```bash
make test-one TEST=tests/test_catalog.py::test_openrouter_normalization_and_limit
make test
```

Never leave intentionally failing tests in the completed work. Record the red
test result during development, not as committed broken code.

## Local Planning Memory

`ROADMAP.md` is the local, ignored source of truth for product direction and
next steps. When asked about the roadmap, planned work, or what to do next,
read it before answering. Keep it current whenever a planned slice, its scope,
or its target version changes; do not add it to Git or package artifacts.

Use semantic versioning: `major.minor.bugfix`. Increase `major` for breaking
changes, `minor` for backward-compatible product features, and `bugfix` for
backward-compatible fixes and release-only corrections.

## Release Documentation Rule

When preparing any release, review public documentation and any maintained
operational material affected by the release. Do not retain repository files
solely to guide an agent: private roadmap, launch, and maintainer runbook
material belongs outside the public repository unless it intentionally serves
contributors. GitHub Actions workflows remain versioned in the repository for
reproducibility, but must not be included in published package artifacts.

The release preflight must also verify that package artifacts contain only
user-facing documentation and required examples: `README.md`, `LICENSE`,
`CHANGELOG.md`, `SECURITY.md` when applicable, and example configuration files.

Before creating or pushing a release tag, finalize `CHANGELOG.md`: replace the
`Unreleased` placeholder for that version with the release date, verify the
entries describe the shipped behavior, and include the finalized file in the
release commit. Never publish a release whose tagged changelog still labels
that version `Unreleased`.

## What this is

`llm-preflight` runs local, cross-provider preflight checks before an LLM model
switch. It ships to PyPI as a console tool with two entry points,
`llm-preflight` and `llm-preflight-mcp`, and takes no runtime dependencies.

## Running it

```bash
make test        # the full suite
make coverage    # suite with coverage
make package     # build the distribution
make audit       # dependency and security audit
```

## Git hygiene

No AI assistant is recorded as a contributor: no `Co-Authored-By` trailer
naming one, no session reference, no generation notice in a pull request body,
and no commit authored under an assistant identity.

Internal planning stays out of the published repository: the roadmap, the
release runbook and the PRDs are deliberately gitignored and declared local
below. Everything else a contributor needs is tracked.

## Where things are

Every tracked document is indexed in [`docs/DOCMAP.md`](docs/DOCMAP.md).

## project-standard

```yaml
adopted: 6e43dbdffdaeed0e7c0bd573a8e5ce13a48a1ce2
next-steps: local     # internal prioritisation; not published
release-flow: local   # release runbook; not published
prds: local           # PRD-*.md, gitignored
critical-paths:       # a wrong verdict here ships a cost or trust figure users act on
  - llm_preflight/pricing.py
  - llm_preflight/features.py
```
