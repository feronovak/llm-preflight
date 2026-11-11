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
    ROOT / f"docs/data/model-comparison-{CURRENT_MEASUREMENT}.json",
)
DEFAULT_OUTPUT = ROOT / f"docs/images/measured-models-{CURRENT_MEASUREMENT}.svg"
# A model added in a later aggregate is shown directly above its predecessor.
ROW_ABOVE = {"claude-fable-5-2": "claude-fable-5-1"}
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
    """Read one aggregate, or concatenate the rows of several in the given order."""
    if data_paths is None:
        data_paths = DEFAULT_DATA
    if isinstance(data_paths, Path):
        data_paths = (data_paths,)
    first, *rest = (json.loads(path.read_text()) for path in data_paths)
    rows = [*first["rows"], *(r for d in rest for r in d["rows"])]
    return {**first, "rows": place_above(rows)}


def place_above(rows: list[dict]) -> list[dict]:
    """Move each model in ROW_ABOVE directly above its predecessor when both exist."""
    for model, anchor in ROW_ABOVE.items():
        moved = [row for row in rows if row["model"] == model]
        if not moved or not any(row["model"] == anchor for row in rows):
            continue
        rows = [row for row in rows if row["model"] != model]
        at = next(i for i, row in enumerate(rows) if row["model"] == anchor)
        rows[at:at] = moved
    return rows


def observed_rows(
    data_path: Path | tuple[Path, ...] | None = None,
) -> list[tuple[str, ...]]:
    data = load_data(data_path)
    current = data["rows"]
    request_counts = {row["requests"] for row in current}
    if len(request_counts) != 1 or next(iter(request_counts)) <= 0:
        raise ValueError("All rows must have the same positive request count")
    rows = []
    for row in current:
        cost = row["estimated_cost_usd"]
        if cost is not None and (not math.isfinite(cost) or cost < 0):
            raise ValueError("Cost must be finite nonnegative evidence or null")
        if not 0 <= row["valid"] <= row["api_successful"] <= row["requests"]:
            raise ValueError("Invalid passing/API/request counts")
        rows.append(
            (
                row.get("display_name", MODEL_NAMES.get(row["model"], row["model"])),
                row.get("api_failure_summary", f"0/{row['requests']}")
                if not row["api_successful"]
                else f"{row['valid']}/{row['requests']}",
                f"{row['mean_latency_seconds']:.3f}s"
                if row["mean_latency_seconds"] is not None
                else "—",
                f"${row['estimated_cost_usd']:.6f}"
                if row["estimated_cost_usd"] is not None
                else "—",
                row["observed_on"],
                row["route"],
            )
        )
    return rows


def render(data_path: Path | tuple[Path, ...] | None = None) -> str:
    style = json.loads((ROOT / "docs/images/style.json").read_text())
    colors = style["colors"]
    layout = style["measured_models"]
    rows = observed_rows(data_path)
    data = load_data(data_path)
    title = (
        data.get("display_title", "Observed model results")
        if data_path
        else f"Eight application checks across {len(rows)} models"
    )
    request_count = data["rows"][0]["requests"]
    dates = sorted(row[4] for row in rows)
    year, month, day = dates[-1].split("-")
    last_update = f"Last update: {day}.{month}.{year}"
    width = layout["width"]
    height = (
        layout["table_top"] + len(rows) * layout["row_height"] + layout["footer_height"]
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
        (
            '<desc id="description">Selected dated observations. '
            "Latency includes API successes, including contract failures, and excludes API errors. "
            "An em dash means unavailable; total cost is unknown where usage is missing. "
            "Routes, request settings and dates differ. This is not a ranking or production approval."
            "</desc>"
        ),
        f'<rect width="{width}" height="{height}" rx="16" fill="{colors["background"]}"/>',
        text(32, 52, title, layout["title_size"], bold=True),
        text(
            width - 32,
            52,
            last_update,
            layout["subtitle_size"],
            "muted",
            anchor="end",
        ),
        text(
            32,
            86,
            f"{len(rows)} models · {request_count} requests each",
            layout["subtitle_size"],
            "muted",
        ),
        text(
            32,
            120,
            "Small synthetic sample; passing does not establish overall model quality.",
            layout["subtitle_size"],
            "muted",
        ),
        f'<rect x="16" y="148" width="{width - 32}" height="48" rx="6" fill="{colors["header"]}"/>',
    ]
    columns = layout["columns"]
    headers = (
        "Model",
        "Contract passed",
        "API errors",
        "Mean latency",
        "Est. cost · this run",
        "Connection route",
    )
    for x, header in zip(columns, headers):
        parts.append(text(x, 179, header, layout["header_size"], bold=True))
    for index, (observed, evidence) in enumerate(zip(rows, data["rows"])):
        responses = evidence["api_successful"]
        errors = evidence["requests"] - responses
        rate_limits = sum(
            failure.get("category") == "rate_limit"
            for failure in evidence.get("failures", [])
        )
        error_label = (
            f"{errors} rate limits" if errors and rate_limits == errors else str(errors)
        )
        cost = observed[3]
        partial = (
            cost == "—"
            and evidence.get("cost_coverage", {}).get("known_requests", 0) > 0
        )
        if partial:
            subtotal = evidence["known_cost_subtotal_usd"]
            if not math.isfinite(subtotal) or subtotal < 0:
                raise ValueError("Known cost must be finite nonnegative evidence")
            cost = f"${subtotal:.6f} known"
        row = (
            observed[0],
            f"{evidence['valid']}/{responses} passed" if responses else "Not evaluated",
            error_label,
            observed[2],
            cost,
            observed[5],
        )

        top = layout["table_top"] + index * layout["row_height"]
        if index % 2 == 0:
            parts.append(
                f'<rect x="16" y="{top}" width="{width - 32}" height="{layout["row_height"]}" fill="{colors["surface"]}"/>'
            )
        parts.append(f'<g data-model="{escape(row[0], quote=True)}">')
        for column, (x, value) in enumerate(zip(columns, row)):
            color = "text"
            if column == 1:
                color = (
                    "pass_text"
                    if responses and evidence["valid"] == responses
                    else "warning_text"
                )
                if errors:
                    color = "warning_text"
            elif column == 2 and errors:
                color = "warning_text"
            size = layout["model_size"] if column == 0 else layout["cell_size"]
            parts.append(text(x, top + 25, value, size, color))
        parts.append('<g class="annotations">')
        contract_note = evidence.get("contract_failure_summary")
        if contract_note:
            parts.append(
                text(
                    columns[1],
                    top + 47,
                    contract_note,
                    layout["footnote_size"],
                    "warning_text",
                )
            )
        elif errors:
            parts.append(
                text(
                    columns[1],
                    top + 47,
                    "incomplete evaluation",
                    layout["footnote_size"],
                    "warning_text",
                )
            )
        if partial:
            parts.append(
                text(
                    columns[4],
                    top + 47,
                    "total unknown",
                    layout["footnote_size"],
                    "warning_text",
                )
            )
        parts.append("</g></g>")
    footer_top = height - layout["footer_height"] + 16
    parts.extend(
        [
            f'<path d="M32 {footer_top}H{width - 32}" stroke="{colors["border"]}"/>',
            text(
                32,
                footer_top + 31,
                "Passed = valid / API responses. API errors are separate; 3/3 with 5 errors is an incomplete evaluation.",
                layout["footnote_size"],
                "muted",
            ),
            text(
                32,
                footer_top + 62,
                "Estimated token cost is for this run, including invalid outputs. Missing usage keeps total cost unknown.",
                layout["footnote_size"],
                "muted",
            ),
            text(
                32,
                footer_top + 93,
                "Latency averages API responses only. One request per case does not establish consistency.",
                layout["footnote_size"],
                "muted",
            ),
            text(
                32,
                footer_top + 124,
                "Routes and settings differ. Read the linked method before comparing; this is not production approval.",
                layout["footnote_size"],
                "muted",
            ),
            "</svg>",
        ]
    )
    return "\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--data",
        type=Path,
        action="append",
        help="New aggregate JSON; repeat to concatenate several, without historical additions",
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        content = render(tuple(args.data) if args.data else None).encode()
    except (ValueError, KeyError, OSError) as error:
        parser.error(str(error))
    if args.check:
        if not args.output.is_file() or args.output.read_bytes() != content:
            print(f"Outdated image: {args.output}")
            return 1
        print(f"Current image: {args.output}")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(content)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
