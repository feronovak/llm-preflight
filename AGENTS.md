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
