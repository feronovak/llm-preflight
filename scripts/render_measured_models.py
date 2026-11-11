"""Render the README's dated observations from the retained comparison evidence.

Run `python3 scripts/render_measured_models.py`; use --check in verification.
This documentation utility uses only the standard library and makes no requests.
"""

from __future__ import annotations

import argparse
import json
import math
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CURRENT_MEASUREMENT = "2026-11-11"
DEFAULT_DATA = (
    ROOT / "docs/data/model-comparison-2026-10-29.json",
    ROOT / f"docs/data/model-comparison-{CURRENT_MEASUREMENT}-five-models.json",
    ROOT / f"docs/data/model-comparison-{CURRENT_MEASUREMENT}.json",
)
DEFAULT_OUTPUT = ROOT / f"docs/images/measured-models-{CURRENT_MEASUREMENT}.svg"
DEFAULT_LIGHT_OUTPUT = (
    ROOT / f"docs/images/measured-models-{CURRENT_MEASUREMENT}-light.svg"
)
# Display order inside each result group: provider, then model, newest/largest first.
MODEL_ORDER = (
    "gpt-6-astra",
    "gpt-6.1-sol",
    "gpt-6.1-terra",
    "gpt-6-luna",
    "claude-fable-5-2",
    "claude-fable-5-1",
    "claude-opus-5-5",
    "claude-sonnet-5-5",
    "claude-haiku-5-5",
    "gemini-4-argon",
    "gemini-4-carbon",
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.1-flash-lite",
    "grok-4.7",
    "deepseek-v4-pro",
    "deepseek-flash",
    "qwen3.8-max",
    "qwen3.8-flash",
    "MiniMax-M3",
    "mistral-large-4",
    "glm-5.3",
    "glm-5.3-flashx",
    "glm-5.3-flash",
    "kimi-k3.1-pro",
)
# Models the default summary leaves out; their rows stay in the data and the guide.
DEFAULT_HIDDEN = {"claude-mythos-5-2"}
MODEL_NAMES = {
    "gpt-6-astra": "GPT-6 Astra",
    "gpt-6.1-sol": "GPT-6.1 Sol",
    "gpt-6-luna": "GPT-6 Luna",
    "claude-opus-5-5": "Claude Opus 5.5",
    "claude-sonnet-5-5": "Claude Sonnet 5.5",
    "claude-haiku-5-5": "Claude Haiku 5.5",
    "gemini-4-argon": "Gemini 4 Argon",
    "gemini-3.8-flash": "Gemini 3.8 Flash",
    "gemini-3.1-flash-lite": "Gemini 3.1 Flash-Lite",
    "z-ai/glm-5.3": "GLM 5.3",
    "z-ai/glm-5.3-flash": "GLM 5.3 Flash",
    "deepseek/deepseek-v4.1-flash": "DeepSeek V4.1 Flash",
    "qwen/qwen3.8-max-0902": "Qwen 3.8 Max 0902",
    "qwen/qwen3.8-flash": "Qwen 3.8 Flash",
}


def load_data(data_paths: Path | tuple[Path, ...] | None = None) -> dict:
    """Read one aggregate, or merge the rows of several in display order."""
    hidden = DEFAULT_HIDDEN if data_paths is None else set()
    if data_paths is None:
        data_paths = DEFAULT_DATA
    if isinstance(data_paths, Path):
        data_paths = (data_paths,)
    first, *rest = (json.loads(path.read_text()) for path in data_paths)
    rows = [*first["rows"], *(r for d in rest for r in d["rows"])]
    rows = [row for row in rows if row["model"] not in hidden]
    return {**first, "rows": in_display_order(rows)}


def in_display_order(rows: list[dict]) -> list[dict]:
    """Sort rows by MODEL_ORDER; models it does not list keep their order, last."""
    rank = {model: i for i, model in enumerate(MODEL_ORDER)}
    return sorted(rows, key=lambda row: rank.get(row["model"], len(rank)))


def http_label(evidence: dict) -> str:
    """Name the shared HTTP status of failed calls, else a plain count label."""
    statuses = {f.get("http_status") for f in evidence.get("failures", [])}
    if len(statuses) == 1 and isinstance(next(iter(statuses)), int):
        return f"HTTP {statuses.pop()}"
    return evidence.get("api_failure_summary", "API errors")


def classify(evidence: dict) -> str:
    """Group a row by what its result lets a reader conclude."""
    if not evidence["api_successful"]:
        return "none"
    if evidence["api_successful"] < evidence["requests"]:
        return "incomplete"
    return "pass" if evidence["valid"] == evidence["requests"] else "partial"


def table_rows(data: dict) -> list[dict]:
    """Validate the evidence and return one display record per model."""
    request_counts = {row["requests"] for row in data["rows"]}
    if len(request_counts) != 1 or next(iter(request_counts)) <= 0:
        raise ValueError("All rows must have the same positive request count")
    rows = []
    for row in data["rows"]:
        cost = row["estimated_cost_usd"]
        if cost is not None and (not math.isfinite(cost) or cost < 0):
            raise ValueError("Cost must be finite nonnegative evidence or null")
        if not 0 <= row["valid"] <= row["api_successful"] <= row["requests"]:
            raise ValueError("Invalid passing/API/request counts")
        group = classify(row)
        errors = row["requests"] - row["api_successful"]
        rate_limits = sum(
            f.get("category") == "rate_limit" for f in row.get("failures", [])
        )
        if not errors:
            error_label = "0"
        elif group == "none":
            error_label = f"{errors} × {http_label(row)}"
        else:
            error_label = (
                f"{errors} rate limits" if rate_limits == errors else str(errors)
            )
        if cost is None and row.get("cost_coverage", {}).get("known_requests", 0) > 0:
            subtotal = row["known_cost_subtotal_usd"]
            if not math.isfinite(subtotal) or subtotal < 0:
                raise ValueError("Known cost must be finite nonnegative evidence")
            cost_label = f"${subtotal:.6f} known"
        else:
            cost_label = f"${cost:.6f}" if cost is not None else "—"
        passed = f"{row['valid']}/{row['api_successful']}"
        if group == "none":
            passed = "not available"
        elif row.get("contract_failure_summary"):
            passed += f" · {row['contract_failure_summary']}"
        latency = row["mean_latency_seconds"]
        rows.append(
            {
                "name": row.get(
                    "display_name", MODEL_NAMES.get(row["model"], row["model"])
                ),
                "route": row["route"],
                "group": group,
                "valid": row["valid"],
                "responses": row["api_successful"],
                "errors": errors,
                "rate_limits": rate_limits,
                "http": http_label(row) if group == "none" else "",
                "passed": passed,
                "error_label": error_label,
                "latency": f"{latency:.3f}s" if latency is not None else "—",
                "cost": cost_label,
                "date": row["observed_on"],
            }
        )
    return rows


def plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def describe(rows: list[dict], requests: int) -> str:
    """One-sentence result summary used as the image description."""
    full = [r for r in rows if r["group"] == "pass"]
    parts = [f"{len(full)} passed {requests}/{requests}"]
    partial: dict[int, int] = {}
    for r in rows:
        if r["group"] == "partial":
            partial[r["valid"]] = partial.get(r["valid"], 0) + 1
    parts += [f"{n} passed {v}/{requests}" for v, n in sorted(partial.items())]
    for r in rows:
        if r["group"] == "incomplete":
            limits = (
                f"{r['errors']} rate limits"
                if r["rate_limits"] == r["errors"]
                else plural(r["errors"], "API error")
            )
            parts.append(
                f"{r['name']} {plural(r['responses'], 'response')} and {limits}"
            )
        elif r["group"] == "none":
            parts.append(f"{r['name']} 0 responses ({r['http']})")
    return (
        f"{len(rows)} models attempted on {requests} checks: {', '.join(parts)}. "
        "Small synthetic sample, not a ranking or production approval."
    )


GROUP_TITLES = {
    "pass": ("Passed every check", "pass_text"),
    "partial": ("Contract failures", "warning_text"),
    "incomplete": ("Incomplete: API errors", "warning_text"),
    "none": ("No response", "fail_text"),
}


def render(
    data_path: Path | tuple[Path, ...] | None = None, theme: str = "dark"
) -> str:
    style = json.loads((ROOT / "docs/images/style.json").read_text())
    colors = style["colors" if theme == "dark" else "colors_light"]
    layout = style["measured_models"]
    data = load_data(data_path)
    rows = table_rows(data)
    title = (
        data.get("display_title", "Observed model results")
        if data_path
        else f"Eight application checks across {len(rows)} models"
    )
    request_count = data["rows"][0]["requests"]
    dates = sorted(row["date"] for row in rows)
    as_of = dates[-1]
    groups = [
        (key, [r for r in rows if r["group"] == key])
        for key in GROUP_TITLES
        if any(r["group"] == key for r in rows)
    ]
    width = layout["width"]
    height = (
        layout["table_top"]
        + len(rows) * layout["row_height"]
        + len(groups) * layout["group_height"]
        + layout["footer_height"]
    )

    def text(
        x: int,
        y: int,
        value: str,
        size: int,
        color: str = "text",
        bold: bool = False,
        anchor: str = "start",
    ) -> str:
        return (
            f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" '
            f'fill="{colors[color]}" font-weight="{700 if bold else 400}">{escape(value)}</text>'
        )

    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description" '
            f'font-family="{escape(style["fonts"]["sans"], quote=True)}">'
        ),
        "<!-- Generated by scripts/render_measured_models.py. Do not edit values here. -->",
        f'<title id="title">{escape(title)}</title>',
        f'<desc id="description">{escape(describe(rows, request_count))}</desc>',
        (
            f'<rect width="{width}" height="{height}" rx="16" '
            f'fill="{colors["background"]}" stroke="{colors["border"]}"/>'
        ),
        text(32, 50, title, layout["title_size"], bold=True),
        text(
            32,
            86,
            f"{len(rows)} models · {request_count} requests each · as of {as_of}",
            layout["subtitle_size"],
            "muted",
        ),
        text(
            32,
            118,
            "Small synthetic sample; passing does not establish overall model quality.",
            layout["subtitle_size"],
            "muted",
        ),
    ]
    header_top = layout["table_top"] - layout["header_height"] - 8
    parts.append(
        f'<rect x="16" y="{header_top}" width="{width - 32}" height="{layout["header_height"]}" '
        f'rx="6" fill="{colors["header"]}"/>'
    )
    columns = layout["columns"]
    headers = ("Model · route", "Contract passed", "API errors", "Latency", "Est. cost")
    baseline = header_top + 27
    for x, header in zip(columns, headers):
        parts.append(text(x, baseline, header, layout["header_size"], bold=True))
    top = layout["table_top"]
    for key, members in groups:
        label, color = GROUP_TITLES[key]
        parts.append(
            f'<g class="group" data-group="{key}">'
            + text(
                32,
                top + 27,
                f"{label} · {plural(len(members), 'model')}",
                layout["header_size"],
                color,
                bold=True,
            )
            + "</g>"
        )
        top += layout["group_height"]
        for index, row in enumerate(members):
            if index % 2 == 0:
                parts.append(
                    f'<rect x="16" y="{top}" width="{width - 32}" height="{layout["row_height"]}" fill="{colors["surface"]}"/>'
                )
            status = "pass_text" if key == "pass" else color
            y = top + 29
            parts.append(f'<g data-model="{escape(row["name"], quote=True)}">')
            parts.append(
                f'<text x="{columns[0]}" y="{y}" font-size="{layout["model_size"]}" fill="{colors["text"]}">'
                f'<tspan font-weight="700">{escape(row["name"])}</tspan>'
                f'<tspan fill="{colors["muted"]}"> · {escape(row["route"])}</tspan></text>'
            )
            cells = (
                (row["passed"], status),
                (row["error_label"], "warning_text" if row["errors"] else "text"),
                (row["latency"], "text"),
                (row["cost"], "text"),
            )
            for x, (value, cell_color) in zip(columns[1:], cells):
                parts.append(text(x, y, value, layout["cell_size"], cell_color))
            parts.append("</g>")
            top += layout["row_height"]
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="Write one image here; without it the dark and light defaults are written",
    )
    parser.add_argument("--theme", choices=("dark", "light"), default="dark")
    parser.add_argument(
        "--data",
        type=Path,
        action="append",
        help="New aggregate JSON; repeat to concatenate several, without historical additions",
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    targets = (
        [(args.output, args.theme)]
        if args.output
        else [(DEFAULT_OUTPUT, "dark"), (DEFAULT_LIGHT_OUTPUT, "light")]
    )
    status = 0
    for output, theme in targets:
        try:
            content = render(tuple(args.data) if args.data else None, theme).encode()
        except (ValueError, KeyError, OSError) as error:
            parser.error(str(error))
        if args.check:
            if not output.is_file() or output.read_bytes() != content:
                print(f"Outdated image: {output}")
                status = 1
            else:
                print(f"Current image: {output}")
            continue
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content)
        print(f"Wrote {output}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
