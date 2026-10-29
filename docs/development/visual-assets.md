# Visual asset specification

**Last reviewed:** 2026-10-19 · **As of:** v2.22.2

Use this specification when creating or regenerating project images. Measured
results, terminal recordings and exported report cards have distinct profiles
because they serve different tasks. Preserve the underlying observations and
make outcomes readable before adding decoration.

The machine-readable tokens for documentation images and terminal exports are
in [style.json](../images/style.json). The measured-results renderer reads those
tokens directly. Product report cards retain their existing renderer profile;
changing that profile is a separate product behavior change.

## Fonts and typography

Use regular weight 400 and bold 700. Keep model names and numerical values as
text in the SVG; never trace numbers into paths or recreate them with image
generation. Sizes below are source pixels before browser scaling.

| Profile | Font | Sizes |
|---|---|---|
| Documentation figures and measured models | Liberation Sans; fall back to Arial, Helvetica, sans-serif | Title 31; subtitle 20; column headers 19 bold; model names 21; values 19; footnotes 18 |
| Terminal contents | Liberation Mono, with DejaVu Sans Mono fallback for new captures | 22; line-height 1.2; preserve the CLI's native ANSI colors |
| Terminal captions | Liberation Sans | Outcome title 24 bold; explanation 22; badge 19 bold; window title and small labels 17 |
| Product report cards | Helvetica, Arial, sans-serif; values use ui-monospace, Menlo, Consolas, DejaVu Sans Mono, monospace | Product label 16 bold; verdict 28 bold; field labels 13 bold; values 14 mono; evidence footer 12 mono |

Install the Liberation font family in the rendering environment and retain its
version with the export evidence. Fallbacks preserve readability when an SVG
is viewed on another system; browser font selection can change exact metrics.
If a localized label needs CJK glyphs, install Noto Sans CJK SC and check the
rendered output for missing glyphs. Chinese model families can keep their
upstream Latin names and exact API IDs; they do not require translated labels.

Avoid all-caps prose, condensed fonts, shadows and tiny disclaimer text. Keep
status words visible alongside color. Do not reduce font size to fit more rows.

## Documentation figure colors

| Token | Hex | Use |
|---|---|---|
| Background | `#0d1117` | Figure canvas |
| Surface | `#161b22` | Alternating table rows |
| Header | `#21262d` | Column header strip |
| Border | `#30363d` | Decorative separators |
| Text | `#e6edf3` | Primary labels and values |
| Muted | `#aeb9c7` | Dates, context and limitations |
| Pass text | `#7ee787` | All configured checks passed |
| Failure text | `#ff7b72` | No successful checks or rejected requests |
| Warning text | `#f2cc60` | Partial pass counts or incomplete evidence |
| Information | `#58a6ff` | Actions and neutral explanatory emphasis |

Use status colors for the stated outcome, not as a model-family brand color.
Unknown values display `—` with a nearby explanation; they never become zero.
Primary text and status labels must retain readable contrast on their surface.
Color alone must not distinguish pass, failure or missing evidence.

Terminal framing uses a `#080c12` outer canvas, `#252b34` title bar and
`#434a54` outline. Caption badges use pass `#3fb950`, failure `#f85149`,
warning `#d29922`, and information `#58a6ff`, with dark ink `#081018`.
CLI output keeps the captured terminal theme; do not recolor its verdicts.

Product cards use a white canvas (`#ffffff`), black text/border (`#000000`)
and these existing verdict bands:

| Verdict | Band | Text |
|---|---|---|
| PASS | `#1a7f37` | `#ffffff` |
| INCONCLUSIVE | `#f2c94c` | `#000000` |
| FAIL | `#cf222e` | `#ffffff` |
| EXPIRED | `#6e7781` | `#ffffff` |

See `llm_preflight/reporting.py` for the authoritative
status mapping. The dark documentation palette must not silently change the
product card fixtures.

## Dimensions and spacing

| Asset class | Source size | Layout |
|---|---|---|
| Measured-results image | 1280 px wide; current 19-row image is 1516 px high | 32 px text margins; 16 px panel margins; 16 px corners; header starts at y=148; data at y=196; 60 px per row; 180 px footer |
| Terminal GIF and MP4 | 1248 × 996 px | 90 columns × 28 rows; native viewport beneath window chrome; captions outside the viewport; 16 px outer frame margins |
| Product report card | 600 px wide; content determines height | 20 px margin, 2 px black outline, native wrapping and verdict band |
| Historical demo GIF | 1100 × 720 px | Frozen legacy assets; new recordings use the current terminal profile |
| Vision input fixture | 1254 × 1254 px | Input data, not promotional artwork; preserve exact bytes |

Measured-image height is `196 + 60 × row_count + 180`. Keep the complete cohort in one
image, increasing its height while preserving source order and context.
Do not shrink text or discard failures to fit.
The column origins are x=`32, 302, 480, 650, 800, 1030`: model, contract passed,
API errors, mean latency, estimated token cost for this run, connection route.
Show the observation date once above the table. Contract results use successful
API responses as their denominator; display API errors separately and explicitly
mark incomplete evaluations. A partial cost shows its known subtotal and an
unknown total. Add failure explanations below the affected cells.

SVG is the canonical measured-table image. It stays sharp in Markdown and
can be opened at full size. Link a text equivalent for narrow screens and
assistive technology. If a PNG is needed for an external channel, export it
at twice the source dimensions, preserve aspect ratio, and use sRGB. Check the
figure at its intended display width before publication.

## Measured models and future Chinese model runs

Generate the figure from retained aggregates; never edit its numerical SVG
labels by hand. The current summary uses only the October 29 JSON and keeps
all 19 models in one image. Neither default nor `--data` input silently inherits
historical rows.

Each source row supplies `model`, `route`, `observed_on`, `requests`,
`api_successful`, `valid`, `mean_latency_seconds` and `estimated_cost_usd`.
Optional `display_name` supplies an upstream-readable label. Optional `contract_failure_summary` explains observed contract failures.
Optional `failures` categories identify rate limits; other API errors retain
their count. `known_cost_subtotal_usd` with positive `cost_coverage.known_requests`
permits a clearly labelled partial cost when the total remains null. Optional top-level `display_title` names the workload.

Use the same positive request count for each row in one figure so its cost
column has a truthful denominator. The subtitle shows the date or date range; each row keeps its actual
route. Preserve separate rows when the same model has native and routed
observations. Keep missing latency/cost null in the JSON and unavailable in
the image. Never infer a native Z.ai, DeepSeek or Qwen observation from an
OpenRouter call. Keep model errors and wrong-label responses in the dataset.

The image is a selected workload observation, not an assertion of market share
or a universal model ranking. Preserve the method, request limits, reasoning
settings, price evidence and failure analysis beside the full text results.
Do not regenerate a “newly tested” date merely because the image was restyled.
New provider runs require their own authorized evidence before adding rows.

From a source checkout, regenerate and check the current figure:

```bash
python3 scripts/render_measured_models.py
python3 scripts/render_measured_models.py --check
```

After creating a new reviewed aggregate JSON, supply its actual path and a new
output filename. For example, replace the dated paths below with your evidence:

```bash
python3 scripts/render_measured_models.py \
  --data docs/data/model-comparison-YYYY-MM-DD.json \
  --output docs/images/measured-models-YYYY-MM-DD.svg
```

The renderer uses only the standard library and makes no network request.
Update the README's image/alt text and method link together. Run the focused
comparison-evidence and regeneration tests, then the full suite. A descriptive failure label must agree with the retained failure analysis;
zero successful calls alone does not establish why the API failed.

## Terminal recording rules

Record an actual shell PTY with prompts, typed commands, scrolling history and
unchanged CLI output. Native application clears are allowed; the recorder must
not replace screens with reconstructed output. Explain actions and outcomes
in the external caption area, clearly distinct from terminal text.

A contract demo follows accepted response → changed response rejected → fixed
response accepted. A mock demo explains local test pass and expected overall
inconclusive before a reader can mistake it for provider approval. Include
visible offline/synthetic labels when those are the evidence conditions.

Keep ordinary reading pauses around 1.5–3 seconds, and completed plans and
important outcomes around 3–5 seconds. These are starting points for review;
readability matters more than constant motion. Do not animate text merely to
avoid a static frame, speed up output until it is unreadable, or add an
unrelated gate scene to a validator story.

The title bar is 48 px high; reserve a 150 px caption area outside the native
viewport and retain the export's outer padding.

Export looping GIF at 12 fps, and MP4 at 24 fps with H.264/yuv420p. Use a
128-color adaptive GIF palette as the initial preset; verify status colors
and text after quantization. Frame dimensions and terminal output are the same
between formats. Provide alt text, a text walkthrough and an MP4 link.

Retain the commands, answers, raw cast, actual exit codes, captions, timestamps,
export tool versions and artifact hashes in local evidence. Verify the expected
outcomes before export and decode the complete MP4. Keep a contact sheet of
key actions and results for visual review. Use a new public filename when a
replacement should bypass a cached old image. Keep the current recordings until behavior or profile changes warrant a
reviewed replacement.

## Current asset inventory

This inventory includes tracked images and their companion videos. Treat the
legacy assets and input fixtures as deliberate exceptions, not templates for
new illustrations.

| Asset | Profile and size | Source or regeneration |
|---|---|---|
| `docs/images/measured-models-2026-10-29.svg` | Current measured results, 1280×1516; 19 rows | `scripts/render_measured_models.py`; October 29 aggregates |
| `docs/images/measured-models.svg` | Historical measured results, 1280×946 | Retained October 14/earlier summary; unchanged for older documentation links |
| `docs/images/contract-check-session.gif` and `.mp4` | Current terminal, 1248 × 996; about 23 seconds | Actual local contract-check pass/reject/fix session; follow terminal rules above |
| `docs/images/default-template-evidence-session.gif` and `.mp4` | Current terminal, 1248 × 996; about 30 seconds | Actual init/default interactive mock and CLI JSON session; refreshed for 2.22.2 evidence-aware summary |
| `docs/images/contract-break.svg` | Product report card, 600 × 392 | `python3 -m llm_preflight report examples/reports/schema-break.json --format svg` |
| `docs/images/readme-demo.gif` | Legacy terminal, 1100 × 720 | Historical mock recording; preserve bytes, use the approved current demo for new placements |
| `docs/images/interactive-demo.gif` | Legacy terminal, 1100 × 720 | Historical paid comparison; preserve its original scope and bytes |
| `tests/fixtures/cards/pass.svg` | Product card, 600 × 496 | Golden output of `tests/test_reporting.py` |
| `tests/fixtures/cards/fail.svg` | Product card, 600 × 514 | Golden output of `tests/test_reporting.py` |
| `tests/fixtures/cards/inconclusive.svg` | Product card, 600 × 432 | Golden output of `tests/test_reporting.py` |
| `tests/fixtures/cards/expired.svg` | Product card, 600 × 418 | Golden output of `tests/test_reporting.py` |
| `examples/vision/order-4821.png` | Fixed vision input, 1254 × 1254 | Test/example input; do not recolor, restyle or replace as a visual cleanup |

Historical demos are not fully specified by the current font/palette profile;
keep them unchanged until an explicitly reviewed replacement is needed. The
report-card fixtures are product regression evidence: a change requires its
own red/green behavior test and review. Vision-fixture changes can alter
content fingerprints and request identity, so review them as input changes.

## Review before publication

Verify displayed values against source evidence, native versus routed labels,
observation dates and missing-cost status. Check glyph coverage, wrapping and
clipping at full size and README width. Confirm status words remain legible in
a paused frame, and check the text equivalent and all public URLs.

Keep SVG self-contained with a viewBox, accessible title/description and no
scripts, foreign objects, remote fonts or external image resources. Preserve
explicit dimensions for PNG/GIF and avoid stretches. Every new asset needs a
source, profile and regeneration recipe in this inventory. Review material
visual changes with a reader unfamiliar with the edit when available.
