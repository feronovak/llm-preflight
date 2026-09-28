# Set up a real project

**Last reviewed:** 2026-09-28 · **As of:** v2.18.2

Use one representative request from your application and a rule its consumer
actually enforces. This example routes a known billing ticket and rejects the
wrong queue. It checks that integration contract; it does not grade open-ended
answer quality or exercise application code automatically.

## 1. Adapt one contract

Save this config as `benchmark.json` in the root of the project you want to
check. The same file is available as a [support routing example](../../examples/project-integration/support-routing.json)
in the source repository.

```json
{
  "name": "support-routing-contract",
  "env_file": ".env.production",
  "prompt": "I was charged twice for the same subscription. Reply with only the support queue label.",
  "models": [
    {
      "name": "approved-route",
      "provider": "openai",
      "model": "replace-with-your-reviewed-model-id",
      "api_key_env": "PROJECT_OPENAI_KEY"
    }
  ],
  "request": {
    "system_prompt": "Route the ticket. Return one lowercase label: billing, technical, or account.",
    "temperature": 0,
    "max_output_tokens": 20
  },
  "validation": {"exact": "billing"},
  "validation_fixtures": [
    {"name": "expected queue", "response": "billing", "expect": "pass"},
    {"name": "wrong queue", "response": "technical", "expect": "fail"}
  ],
  "repetitions": 1,
  "warmups": 0,
  "max_requests": 1,
  "save_responses": false
}
```

In that project's `benchmark.json`, replace the model ID with the reviewed ID
your application calls. Change the prompt, system prompt, and validator to match
your deployed request and parser. The example's `exact: billing` rule is right
only if that exact response is required for the chosen ticket. Preserve one
accepted and one rejected `validation_fixtures` response so a weak or overly
strict rule is caught locally. For JSON payloads, use a `json_schema` that
matches the fields your application parses; see [output contracts](../guides/output-contracts.md).

The example references `.env.production` beside `benchmark.json` and looks for
`PROJECT_OPENAI_KEY`. Change `api_key_env` to the variable name your project
already uses, and set `env_file` to the relative path of your existing env
file. A config `env_file` reference must stay within the config's directory;
placing `benchmark.json` at the project root lets it refer to env files below
that root. Shell values take precedence. The config stores only those names
and paths, never the credential value. Keep the env file out of Git. If your
app builds prompts dynamically, generate this JSON from application-owned
code and review the generated config alongside the change.

## 2. Check locally without a provider request

Run these from your project root after editing the config:

```bash
llm-preflight benchmark.json --contract-check
llm-preflight benchmark.json --doctor --json
llm-preflight benchmark.json --pricing-check
llm-preflight benchmark.json --dry-run --json
```

`--contract-check` tests the accepted and rejected fixtures without loading
credentials. Doctor identifies the key source or a missing key without showing
the value. Pricing check flags unknown or stale rates. Dry run shows the route,
request bound, estimated cost, and retention plan without generation. Resolve
its warnings before considering a live request. The example caps the run at
one request; add a reviewed `max_estimated_cost_usd` to the config after price
coverage is known and before a paid run.

## 3. Save evidence after approval

After reviewing the plan and authorizing a bounded provider request, capture
the JSON result and render a standalone report:

```bash
mkdir -p results
llm-preflight benchmark.json --json --no-save > results/run.json
llm-preflight report results/run.json --output results/report.html
```

The benchmark may exit `1` for a failed contract or `3` for inconclusive
evidence. Keep `results/run.json` and render it even in those cases; read its
structured `decision` and blocking warnings before acting. Report export
makes no provider request and omits prompts, responses, local paths, and
credentials. See [reviewable reports](../guides/reports.md).

## 4. Add a no-spend pull request check

Commit `benchmark.json` and add this workflow to your project at
`.github/workflows/llm-preflight.yml`. It checks the local validator and run
plan on pull requests without credentials or generation:

```yaml
name: LLM contract preflight
on: pull_request
permissions:
  contents: read
jobs:
  contract:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: python -m pip install "llm-preflight==2.18.2"
      - run: llm-preflight benchmark.json --contract-check
      - run: llm-preflight benchmark.json --dry-run --no-env-file --json
```

This CI job proves that the committed contract fixtures and plan remain valid;
it is not live model evidence. Add a paid job only in a trusted workflow with
repository secrets and reviewed request and cost bounds. The [CI guide](../automation/ci.md)
explains baseline gates and the fork-safe mock starter. For coding agents, use
the same config with the [MCP server](../automation/mcp.md): `validate_config`
and `dry_run_plan` inspect it without provider access.

## 5. Generate configuration from application-owned code

The [application-alignment example](../../examples/application_alignment/export_preflight.py)
is a source-checkout prototype for the 2.18.0 validator subset. Its
[small application contract](../../examples/application_alignment/app.py) owns
request construction, response fields, and a separate parser. The exporter
reuses those definitions and adds expectations for one billing ticket. It
does not contact a provider, read credentials, or execute the parser.

From a checkout of this source version:

```bash
python3 -m examples.application_alignment.export_preflight > /tmp/app-preflight.json
python3 -m llm_preflight /tmp/app-preflight.json --contract-check --json
python3 -m llm_preflight /tmp/app-preflight.json --dry-run --no-env-file --json
```

The generated configuration uses a mock, one request, zero synthetic cost,
and no retained responses. A mock run remains inconclusive. The Python example
is available in the repository, not an installed Preflight import or command.
The request/schema and generated-config JSON fixtures are versioned beside it;
[focused tests](../../tests/test_application_alignment.py) check their content
and demonstrate a field rename changing the generated request and schema.

In your application, regenerate during CI and compare against the reviewed
configuration. If it differs, review the request, schema, and case expectations
together with the application change. Keep application parser tests as a
separate gate: a standalone contract can pass while a changed consumer fails.
Shared generation reduces duplicate definitions; it does not prove production
parser execution or semantic answer quality. A generic allowed queue is also
different from the expected queue for a particular ticket.

For a live adaptation, use the application's reviewed route and price evidence
and choose approved request/cost caps. The mock's zero rates are not live model
prices. This prototype has deterministic verification, not pilot adoption
evidence; scope further integration work from actual team friction.
