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

4. Upload only the validated artifacts to TestPyPI. Set `TWINE_USERNAME` to
   `__token__` and `TWINE_PASSWORD` to a scoped TestPyPI token, then run:

   ```bash
   make publish-test
   ```

5. In a fresh virtual environment, install and smoke-test the published build:

   ```bash
   python3 -m pip install \
     --index-url https://test.pypi.org/simple/ \
     --extra-index-url https://pypi.org/simple/ \
     llm-speed-bench==<version>
   llm-bench --quick "Reply with ok." --models mock:local --no-save
   ```

6. Verify package metadata, the console entry point, mock demo, and exit code.

7. Create and publish a GitHub release for the matching `v<version>` tag.
   GitHub Actions rebuilds the tagged source, validates the metadata, and
   publishes to PyPI through Trusted Publishing. It does not use stored PyPI
   API tokens.

### Trusted Publishing setup

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
