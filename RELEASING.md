# Releasing

## Validate 1.0.0 on TestPyPI

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
     llm-speed-bench==1.0.0
   llm-bench --quick "Reply with ok." --models mock:local --no-save
   ```

6. Verify package metadata, the console entry point, mock demo, and exit code.
   Only then upload the same artifacts to PyPI.

Do not regenerate artifacts after TestPyPI validation. A public release must
use the identical wheel and source distribution.
