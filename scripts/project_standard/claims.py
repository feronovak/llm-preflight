"""Enumerate the checkable units in each standard document.

A semantic audit that reads a document and reports what it noticed has recall
proportional to how much it happened to sample, and no way to say what it
skipped. Measured across five runs against one product map carrying ~40
claim-bearing rows: every run found a different subset, none found all of them,
and the ranking was uncorrelated with both model tier and with how forcefully
the instruction demanded thoroughness. The strongest-worded instruction scored
worst, and opened by asserting it had checked every row.

So the fix is a denominator rather than an exhortation. Each document type
yields a list of units, each with a line and a question. The judgement pass
works that list and reports coverage against it, and a unit nobody reached is
reported as unchecked — which is the rule the mechanical half already follows
and the judgement half did not.

**What a unit is differs by document, and so does what verifying one means.**
A product-map row is a claim about the code and is checked against the code. A
PRD states intent, so there is nothing in the code to check it against; what is
checkable is that it is linked, owned and decided. Conflating the two is how a
checklist starts demanding that a proposal be true.
"""

import re
from dataclasses import dataclass
from pathlib import Path

# One markdown table row. Header and separator rows are dropped by the caller.
TABLE_ROW = re.compile(r"^\s*\|(?P<body>.+)\|\s*$")
SEPARATOR = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+(?P<text>\S.*?)\s*$")
HEADING = re.compile(r"^(?P<hashes>#{2,3})\s+(?P<text>.+?)\s*$")
RELEASE = re.compile(r"^##\s*\[?v?(?P<version>\d+\.\d+\.\d+)\]?", re.M)
TODO = re.compile(r"<!--\s*TODO\(project-standard\)", re.I)

PRODUCT_MAP_NAMES = ("FEATURE_MAP.md", "FEATURES.md", "CAPABILITIES.md",
                     "PRODUCT.md")


@dataclass
class Unit:
    doc: str
    line: int
    kind: str
    label: str
    verify: str

    def render(self):
        return f"{self.doc}:{self.line}  [{self.kind}] {self.label}"

    def as_dict(self):
        return {"doc": self.doc, "line": self.line, "kind": self.kind,
                "label": self.label, "verify": self.verify}


def _trim(text, limit=90):
    text = " ".join(str(text).split())
    text = re.sub(r"<!--.*?-->", "", text).strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _table_rows(text):
    """(lineno, [cells]) for every body row of every table."""
    out = []
    seen_separator = False
    for i, line in enumerate(text.splitlines(), start=1):
        if SEPARATOR.match(line):
            seen_separator = True
            continue
        m = TABLE_ROW.match(line)
        if not m:
            seen_separator = False
            continue
        if not seen_separator:
            continue  # header row, or a table with no separator yet
        cells = [c.strip() for c in m.group("body").split("|")]
        if any(c for c in cells):
            out.append((i, cells))
    return out


def _list_items(text, under=None):
    """(lineno, text) for list items, optionally only beneath a heading."""
    out = []
    active = under is None
    for i, line in enumerate(text.splitlines(), start=1):
        h = HEADING.match(line)
        if h:
            active = under is None or under.lower() in h.group("text").lower()
            continue
        m = LIST_ITEM.match(line)
        if m and active:
            out.append((i, m.group("text")))
    return out


# -- per document type -----------------------------------------------------

def product_map_units(rel, text):
    """Every row is a claim about what the product does today."""
    out = []
    for line, cells in _table_rows(text):
        label = _trim(cells[0]) or _trim(" ".join(cells))
        if not label or TODO.search(cells[0]):
            continue
        out.append(Unit(rel, line, "claim", label,
                        "read the implementation this names and confirm it "
                        "does what the row says today"))
    return out


def code_map_units(rel, text):
    out = []
    for line, cells in _table_rows(text):
        label = _trim(cells[0])
        if not label or TODO.search(cells[0]):
            continue
        out.append(Unit(rel, line, "mapping", label,
                        "confirm the path exists and that the responsibility "
                        "described is what lives there"))
    return out


def api_units(rel, text):
    out = []
    for line, cells in _table_rows(text):
        label = _trim(" ".join(cells[:2]))
        if not label or TODO.search(cells[0]):
            continue
        out.append(Unit(rel, line, "endpoint", label,
                        "confirm the route exists and the described behaviour "
                        "matches the handler"))
    return out


def backlog_units(rel, text):
    """Future-only: every item must still be open."""
    out = []
    for line, item in _list_items(text):
        label = _trim(item)
        if not label or TODO.search(item):
            continue
        out.append(Unit(rel, line, "backlog", label,
                        "confirm this is still open — a finished item belongs "
                        "in the changelog, not here"))
    return out


def prd_units(rel, text):
    """A PRD is intent, so nothing here is checked against the code.

    What is checkable is that it is decided, linked and owned. Asking whether a
    proposal is true of the code would reject every PRD worth writing.
    """
    out = []
    lines = text.splitlines()
    for i, line in enumerate(lines, start=1):
        m = re.match(r"^\*\*(Status|Backlog|Owner):\*\*\s*(?P<v>.*)$", line.strip())
        if m:
            field = m.group(1)
            value = _trim(m.group("v"))
            out.append(Unit(rel, i, "prd-header", f"{field}: {value or '(empty)'}",
                            "confirm this is filled and current — a PRD with no "
                            "status, backlog link or owner is a proposal nobody owns"))
    for i, line in enumerate(lines, start=1):
        h = HEADING.match(line)
        if h and h.group("hashes") == "##":
            body = "\n".join(lines[i:i + 12])
            if TODO.search(body) or not body.strip():
                out.append(Unit(rel, i, "prd-section",
                                _trim(h.group("text")),
                                "this section is still a skeleton — write it or "
                                "drop the heading"))
    return out


def decision_units(rel, text):
    """One unit per decision. Verifying means asking whether it still holds.

    Not whether it was right — a decision that turned out badly is still a
    true record of what was decided. A decision that no longer governs the
    code is superseded, and saying so is a new entry, never an edit to the old
    one.
    """
    out = []
    for i, line in enumerate(text.splitlines(), start=1):
        h = HEADING.match(line)
        if not h or h.group("hashes") != "##":
            continue
        label = _trim(h.group("text"))
        if not label or TODO.search(line):
            continue
        out.append(Unit(rel, i, "decision", label,
                        "confirm this still governs the code — if it does "
                        "not, supersede it with a new entry rather than "
                        "editing this one"))
    return out


def changelog_units(rel, text):
    out = []
    for m in RELEASE.finditer(text):
        line = text[:m.start()].count("\n") + 1
        out.append(Unit(rel, line, "release", f"v{m.group('version')}",
                        "confirm a tag exists for this version and the entry "
                        "describes what actually shipped"))
    return out


def flow_units(rel, text):
    out = []
    for line, cells in _table_rows(text):
        label = _trim(cells[0])
        if not label or TODO.search(cells[0]):
            continue
        out.append(Unit(rel, line, "bump-rule", label,
                        "confirm this names a real consumer and a real "
                        "consequence, not generic semver"))
    return out


def units_for(rel, text):
    """Dispatch on the document's slot, by filename."""
    name = Path(rel).name
    if name in PRODUCT_MAP_NAMES:
        return product_map_units(rel, text)
    if name == "PROJECT_MAP.md":
        return code_map_units(rel, text)
    if name == "API_REFERENCE.md":
        return api_units(rel, text)
    if name in ("NEXT_STEPS.md", "ROADMAP.md", "TODO.md", "BACKLOG.md"):
        return backlog_units(rel, text)
    if name in ("CHANGELOG.md",):
        return changelog_units(rel, text)
    if name == "DECISIONS.md" or name.startswith("ADR-") \
            or Path(rel).parent.name in ("adr", "adrs", "decisions"):
        return decision_units(rel, text)
    if name in ("DEVELOPMENT_FLOW.md", "RELEASING.md"):
        return flow_units(rel, text)
    if "/prds/" in rel or Path(rel).parent.name == "prds" \
            or name.startswith("PRD-"):
        return prd_units(rel, text)
    return []


# Documents that hold no enumerable unit, and why. Saying so is the point: a
# document absent from the worklist must not read as a document with nothing
# to check.
NOT_ENUMERABLE = {
    "NORTH_STAR.md": "direction is a judgement about where the product is "
                     "going; there is no unit to count",
    "MISSION.md": "direction — no countable unit",
    "VISION.md": "direction — no countable unit",
    "README.md": "prose for humans; the slots it must cover are check 1",
    "CLAUDE.md": "the contract block is parsed by check 2",
    "AGENTS.md": "the contract block is parsed by check 2",
    "DOCMAP.md": "generated; check 3 compares it byte for byte",
}


def scope(ctx):
    """The documents the standard owns — not every markdown file in the tree.

    A worklist that counts every README in every subdirectory has a denominator
    nobody can act on, which defeats the point of having one.
    """
    from .artifacts import resolve_slots

    out = {s.satisfied_by for s in resolve_slots(ctx) if s.satisfied_by}
    for rel in ctx.tracked:
        if not rel.endswith(".md"):
            continue
        parent = Path(rel).parent.name
        if parent == "prds" or Path(rel).name.startswith("PRD-"):
            out.add(rel)
        if parent in ("adr", "adrs", "decisions") \
                or Path(rel).name.startswith("ADR-"):
            out.add(rel)
    return {r for r in out if r in set(ctx.tracked)}


def enumerate_repo(ctx):
    """-> ({doc: [Unit]}, {doc: reason}) over the standard's own documents."""
    units, skipped = {}, {}
    for rel in sorted(scope(ctx)):
        name = Path(rel).name
        found = units_for(rel, _read(ctx.repo, rel))
        if found:
            units[rel] = found
        elif name in NOT_ENUMERABLE:
            skipped[rel] = NOT_ENUMERABLE[name]
        else:
            skipped[rel] = ("no countable unit was extracted — either the "
                            "document is prose, or its shape does not match "
                            "what this slot expects")
    return units, skipped


def _read(repo, rel, limit=400_000):
    p = Path(repo) / rel
    try:
        if p.is_file() and p.stat().st_size <= limit:
            return p.read_text(errors="ignore")
    except OSError:
        pass
    return ""
