VERSION := $(shell python3 -c "from llm_preflight import __version__; print(__version__)")
DIST_FILES := dist/llm_preflight-$(VERSION)*

.PHONY: audit check-dist coverage package publish-test release-freshness test test-one

test:
	python3 -m pytest -q

coverage:
	python3 -m coverage run -m pytest -q
	python3 -m coverage report

package:
	python3 -m build

check-dist:
	python3 -m twine check $(DIST_FILES)

publish-test: package check-dist
	python3 -m twine upload --repository testpypi $(DIST_FILES)

audit:
	ruff format --check . --exclude results
	ruff check . --exclude results
	mypy llm_preflight
	bandit -q -r llm_preflight
	detect-secrets-hook --baseline .secrets.baseline \
		llm_preflight tests .github .env.example \
		benchmark.example.json benchmark.auto.example.json pyproject.toml

# Real-clock check that the bundled examples are still priced and retirement-
# current; the unit suite pins the date so it cannot catch snapshot expiry.
release-freshness:
	python3 scripts/release_freshness.py

test-one:
	@test -n "$(TEST)" || (echo "Usage: make test-one TEST=path::test_name" && exit 2)
	python3 -m pytest -q "$(TEST)"
