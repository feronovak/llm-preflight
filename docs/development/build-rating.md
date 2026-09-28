# Build quality rating

Use this rubric for every reviewable build and release candidate. It serves
maintainers and contributors; it rates this project's implementation and
evidence, not model performance or market popularity.

## Scope and identity

- Record package version, Git commit, dirty-worktree state, build date,
  comparison baseline and reviewer. A commit alone cannot identify uncommitted
  work: retain a source archive or content manifest and its SHA-256.
- Identify the actual wheel and sdist by SHA-256. Do not rate source checks as
  proof that an installed package works.
- Use [North star](../NORTH_STAR.md) and [Product decisions](../DECISIONS.md)
  as the product contract. The ignored local roadmap supplies current priorities.
  An explicit owner decision can revise scope; record it before scoring.
- Review the complete current build, then explain changes from the previous
  rated build. Reuse evidence only when its scope, inputs and relevant content
  hashes still match. Changes invalidate affected evidence, not every check.
- Mark each checkpoint `pass`, `fail` or `unverified`, with a file reference,
  command result or retained artifact. Missing evidence is `unverified` and
  earns no point. A plan, test count or reviewer assertion alone is insufficient.
- Retain reports under ignored `scratchpad/build-ratings/` or another private
  owner-selected store. Keep credentials, private prompts and responses out of
  public reports and package artifacts.

## Scoring

Each dimension has five checkpoints. Its score is the count of proven passes,
from **0 to 5**. All checkpoints apply; no discretionary `N/A` points or changed
weights. Maintenance-only builds can pass product checkpoints by demonstrating
that they preserve existing workflows and direction.

`Total / 100 = sum(weight × dimension_score / 5)`

| Dimension | Weight | What it measures |
|---|---:|---|
| OSS quality | 15 | Usability, contribution and distribution |
| Code quality | 20 | Correctness, maintainability and reproducibility |
| Integrity | 25 | Honest evidence and dependable trust boundaries |
| Mission | 10 | Catching integration regressions before shipping |
| Vision | 5 | Reproducible evidence attached to change reviews |
| North-star alignment | 5 | Usefulness for reviewing actual project changes |
| Niche fit | 10 | Small teams maintaining concrete LLM integrations |
| Documentation quality | 10 | Accurate, usable and consistent guidance |

Scores are a maintainer rubric, not an industry certification. Keep weights
stable across builds. A rubric revision needs a recorded reason and new rubric
identifier; do not change it merely to improve a score. Initial ID: `build-rating-1`.

## Checkpoints

### O — OSS quality

1. **O1:** License and package metadata agree; project, documentation, issue
   and security-reporting routes exist and lead to the intended material.
2. **O2:** A fresh contributor can follow the documented development setup and
   run deterministic tests without provider keys or live calls.
3. **O3:** A clean wheel install and a separate clean sdist install expose the
   correct version and both console entry points; documented local smoke works.
4. **O4:** Runtime remains standard-library-only. Build/dev dependencies are
   declared and pinned through the established tooling; artifact metadata
   confirms no non-extra runtime dependency.
5. **O5:** Distribution contents, changelog and version semantics match the
   build. Private plans, study data, credentials, tests and GitHub workflows
   are excluded; required user examples and documentation are retained.

### C — Code quality

1. **C1:** Each behavior change has recorded focused red/green evidence and
   meaningful assertions; fixes reproduce the defect before implementation.
2. **C2:** The complete test suite passes for this source state. Provider
   changes use deterministic mocked protocol fixtures, including failures.
3. **C3:** Formatting, lint, type, security and secret checks pass. Findings
   are resolved or a tool false positive is documented narrowly and reviewed.
4. **C4:** The changed code follows module ownership and established patterns;
   no unnecessary duplicate logic, hidden side effects or unrelated refactor
   is introduced. Record concrete inspected files and conclusions.
5. **C5:** Changed branches include meaningful boundary/failure coverage.
   Review coverage deltas and explain decreases; pricing, planning and decision
   paths have assertions for their critical invariants. Coverage percentage or
   more tests alone does not prove correctness.

### I — Integrity

1. **I1:** Unknown usage, prices and retry costs remain unknown. Known subtotal
   and complete total differ explicitly. Legacy evidence cannot substantiate
   invented savings; estimates are not presented as invoices.
2. **I2:** Every accepted output-schema constraint is enforced recursively or
   refused before provider work. Case-specific expectations are distinguished
   from generic schema validity; negative fixtures expose weak validators.
3. **I3:** Strict freshness does not depend on descriptive source labels.
   Retry-expanded request/cost bounds, credential redaction, environment-file
   policy and workspace/URL restrictions remain verified.
4. **I4:** CLI, MCP, saved results, baselines and reports agree on pass/fail/
   inconclusive, exit semantics and degraded evidence. Validator provenance
   and legacy comparability are explicit; unknown is never silently a pass.
5. **I5:** Claims are traceable to retained evidence. Synthetic fixtures,
   captured-output replay and live observations are labelled separately.
   No unsupported competitor superiority, adoption, latency or safety claim
   is added. Paid work and deployment remain owner decisions.

### M — Mission

Mission: help engineers catch LLM integration regressions before shipping.

1. **M1:** Each changed feature or fix names the integration risk it addresses;
   maintenance work identifies the existing capability it preserves.
2. **M2:** A project-specific positive and negative case demonstrates the
   expected detection, including its boundary and missing evidence.
3. **M3:** Broken requests/contracts cannot produce shipping-ready evidence;
   errors identify a safe, actionable correction without exposing content.
4. **M4:** The workflow fits pre-merge CLI/CI or agent-assisted review and
   preserves a useful no-spend validation/planning path.
5. **M5:** The build does not imply production approval or broaden its promise
   beyond tested consumer/request/provider contracts. Parser-execution limits
   remain explicit.

### V — Vision

Vision: every LLM-related pull request carries reproducible compatibility,
latency and cost evidence.

1. **V1:** Results identify workload, validator semantics, route, settings and
   relevant price evidence sufficiently for a scoped rerun.
2. **V2:** An offline review artifact can be produced and read without running
   a provider request or requiring a new hosted service.
3. **V3:** Comparable baselines show useful changes; incompatible or incomplete
   evidence is identified before drawing improvement conclusions.
4. **V4:** Compatibility, latency and cost state their measured or unavailable
   status. Local fixture checks are not presented as observed model latency.
5. **V5:** The reviewer can trace a decision back to the configuration and
   evidence. Reproducibility means a recorded procedure, not a promise of
   identical stochastic outputs or stable model aliases.

### N — North-star alignment

North star: projects using evidence to review actual LLM-related changes.
This dimension rates support for that outcome, not the number of customers.

1. **N1:** The build's change is linked to a concrete project review job;
   repository-owned cases and owner data are valid evidence for this mapping.
2. **N2:** A retained artifact lets a reviewer identify checked scope, verdict,
   unknown evidence and cost status without interpreting raw provider logs.
3. **N3:** Setup and reuse are documented for existing project configuration;
   credential references do not require copying secrets into benchmark files.
4. **N4:** Source/application alignment is tested or its limitations are
   documented; a standalone provider contract is not claimed to execute the
   application's parser automatically.
5. **N5:** Any adoption metric states its window, unique projects, reviewer use
   and evidence category. Unknown adoption remains unknown; installs, stars,
   demos and reruns are not substituted for real review use. No external
   participant count, telemetry or repeat-project threshold gates this rating.

### S — Niche fit

Primary segment: small teams changing models, routes, prompts or structured
outputs in an existing LLM feature.

1. **S1:** Changed scope names a segment job, such as routing, extraction,
   a strict JSON consumer or a provider/model migration.
2. **S2:** The supported path remains local and practical in a small team's
   existing CLI/CI workflow, without mandatory service accounts or dashboards.
3. **S3:** The tested request, consumer expectations and approved cost envelope
   are visible; model catalogue membership does not imply execution support.
4. **S4:** New scope respects the durable product boundaries. Broad RAG scoring,
   agent trajectories, leaderboards or hosted observability are not smuggled
   into an unrelated slice; a scope change needs a recorded owner decision.
5. **S5:** Competitive positioning uses an evidenced job comparison and states
   when another tool fits better. Feature parity, popularity and hypothetical
   external pilots are not treated as demand evidence or prerequisites.

### D — Documentation quality

1. **D1:** README/onboarding give a working local first run and the next
   project-specific step, with no hidden credentials or paid requests.
2. **D2:** Affected CLI, configuration, output-schema, decision, result and MCP
   references match shipped/build behavior, including nullability and limits.
3. **D3:** Examples and maintained commands have execution or fixture evidence;
   links resolve and the generated documentation map includes new documents.
4. **D4:** Release status, installable pins, supported providers/constraints,
   source-checkout prototypes and deferred scope are consistent. Unpublished
   work is not described as an available release.
5. **D5:** Guidance explains failure/inconclusive cases, privacy, pricing
   completeness and application-alignment limits in plain language. Material
   claims have supporting evidence; redundant/stale instructions are corrected.

## Hard gates and verdict

Record each applicable gate separately as `pass`, `fail` or `unverified`:

1. Full tests and audit pass; no intentionally failing test remains.
2. No known wrong pass, fabricated cost, ignored accepted constraint, freshness
   bypass, secret exposure, unauthorized spend or unjustified boundary weakening.
3. Wheel/sdist build and metadata checks pass, followed by independent clean
   installs and CLI/MCP smoke; evidence matches the actual rated artifacts.
4. Public contract/version compatibility is verified and material documentation
   claims agree with the build.
5. **Before publication only:** changelog is dated and describes the tagged
   behavior; release version, artifacts and installable automation pins agree.
   For an unpublished build, mark this gate `not_due` and publication readiness
   `not_assessed`; this does not earn a scoring point or imply release approval.

A failed gate yields **blocked**, regardless of total. An unverified required
gate yields **unverified**, not ready. With all applicable gates passing:

| Total | Rating |
|---|---|
| 90–100 | Strong |
| 80–89 | Good; record improvement priorities |
| 65–79 | Needs improvement |
| Below 65 | Weak |

Mark **build ready** only with total at least 80, every dimension at least 3/5
and integrity 5/5. Otherwise mark **needs improvement**. Keep the numeric rating
and readiness verdict separate. A strong average cannot hide weak documentation
or product alignment. Passing this rubric never authorizes publication or spend.

## Evidence workflow for every build

1. Identify the source/artifacts and compare the diff with the baseline. Read
   the direction documents and affected user workflows before rating them.
2. Record focused red/green results during implementation. Run `make test`,
   `make coverage` and `make audit` for the completed source state.
3. Run `make package` and `make check-dist`. Inspect contents and dependency/
   entry-point metadata; test wheel and sdist independently outside the checkout.
4. Exercise a project-specific no-spend contract, plan and mock result, plus MCP
   initialization/workflow access. Confirm mock-only evidence is inconclusive.
5. Review affected public docs, execute relevant examples and regenerate the
   index with `python3 -m scripts.project_standard.cli generate` after new docs
   are tracked. Apply the publication-only gate when preparing a release.
6. Score all 40 checkpoints, record gates, compute the total and compare each
   dimension with the baseline. Explain each decrease and the top three actions.
7. Retain the report beside its logs/hashes. After a subsequent change, invalidate
   the affected evidence and rerate it; do not label a changed artifact with an
   earlier green score. This is a review process, not an automated scoring tool.

## Per-build report template

```text
Rubric: build-rating-1
Build/version/date:
Commit + dirty state + source SHA-256:
Wheel SHA-256 / sdist SHA-256:
Baseline build / reviewer:
Owner scope decisions:

Checkpoint | pass/fail/unverified | evidence reference | finding
[One row for each O1–O5, C1–C5, I1–I5, M1–M5, V1–V5, N1–N5, S1–S5, D1–D5]

Dimension | score/5 | weight | weighted points | baseline delta
OSS quality | ... | 15 | ... | ...
Code quality | ... | 20 | ... | ...
Integrity | ... | 25 | ... | ...
Mission | ... | 10 | ... | ...
Vision | ... | 5 | ... | ...
North-star alignment | ... | 5 | ... | ...
Niche fit | ... | 10 | ... | ...
Documentation | ... | 10 | ... | ...

Total: .../100
Hard gates: [each status + evidence; publication gate not_due if unpublished]
Numeric rating: strong/good/needs improvement/weak
Build verdict: ready/needs improvement/blocked/unverified
Publication readiness: not_assessed/ready/blocked/unverified
Unverified claims and known limitations:
Top three improvements: [action + evidence of completion required]
Optional adoption observations: [known/unknown; no invented project counts]
```
