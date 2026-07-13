# Releasing

## Release Process

1. Start from a clean checkout of the release tag.
2. Install release tooling:

   ```bash
   python3 -m pip install -e ".[release]"
   ```

3. Run the complete local gate:

   ```bash
   make test
   make audit
   make package
   make check-dist
   ```

4. In GitHub Actions, run **TestPyPI validation** from `main`. It runs the
   complete gate, publishes through TestPyPI Trusted Publishing, fresh-installs
   the exact version, and runs the mock CLI demo. It does not use an API token.

5. Create and publish a GitHub release for the matching `v<version>` tag.
   GitHub Actions rebuilds the tagged source, validates the metadata, and
   publishes to PyPI through Trusted Publishing. It does not use stored PyPI
   API tokens.

### Trusted Publishing setup

On TestPyPI, add a GitHub Actions publisher for the same project with:

- Owner: `feronovak`
- Repository: `llm-speed-bench`
- Workflow filename: `testpypi.yml`
- Environment name: `testpypi`

On PyPI, open the `llm-speed-bench` project, select **Publishing**, and add a
GitHub Actions publisher with:

- Owner: `feronovak`
- Repository: `llm-speed-bench`
- Workflow filename: `release.yml`
- Environment name: `pypi`

In GitHub, create the `pypi` environment and require a manual reviewer before
deployments. This approval is the final gate before a release is uploaded.

The CI release build is independent of the TestPyPI artifacts. It rebuilds from
the immutable release tag and verifies that the tag matches the package version.
