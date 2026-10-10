VERSION := $(shell python3 -c "from llm_preflight import __version__; print(__version__)")
DIST_FILES := dist/llm_preflight-$(VERSION)*
FRESHNESS_EXAMPLES := approved-smoke cross-provider-run frontier-candidates \
	flagship-comparison gpt-6.1-sol-comparison anthropic-5.5-comparison \
	anthropic-5.5-checks glm-5.3-comparison glm-5.3-openrouter-comparison

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
	@for example in $(FRESHNESS_EXAMPLES); do \
		echo "pricing-check examples/$$example.json"; \
		python3 -m llm_preflight examples/$$example.json --pricing-check --json --no-save > /dev/null || exit 1; \
	done
	python3 -m llm_preflight --audit-source examples --ci

test-one:
	@test -n "$(TEST)" || (echo "Usage: make test-one TEST=path::test_name" && exit 2)
	python3 -m pytest -q "$(TEST)"
