"""Document checks: stamps, scaffolding tokens, links, duplicate documents.

The carve-outs below are load-bearing. Without them the duplicate-backlog check
fires on issue templates, archived version directories and `docs/done/` — none
of which is a second live roadmap, all of which the standard elsewhere blesses
as legitimately tracked history.
"""

import re
from fnmatch import fnmatch
from pathlib import Path

from . import findings as F
from .artifacts import resolve_slots

TODO_TOKEN = re.compile(r"<!--\s*TODO\(project-standard\)", re.I)
STAMP = re.compile(r"\*\*Last reviewed:\*\*\s*(\d{4}-\d{2}-\d{2})", re.I)
AS_OF = re.compile(r"\*\*As of:\*\*\s*v?(\d+\.\d+\.\d+)", re.I)
SCAFFOLDED = re.compile(r"\*\*Status:\*\*\s*scaffolded", re.I)
MD_LINK = re.compile(r"\[[^\]]*\]\(\s*([^)\s]+)(?:\s+[\"\'][^)]*)?\)")

# Directories that hold history, templates or archives. Excluded from every
# duplicate-document check.
EXCLUDED = (
    "*/archived/*", "archived/*",
    "*/archive/*", "archives/*", "*/archives/*",
    "docs/done/*", "*/history/*", "history/*",
    ".github/*", "*/.github/*",
    "docs/superpowers/*",
    "*think-day-*/*", "*dev-day-*/*",
    "*/v[0-9]*/*",
)

BACKLOG_NAMES = ("ROADMAP.md", "TODO.md", "BACKLOG.md", "PLAN.md",
                 "IMPLEMENTATION_ROADMAP.md", "NEXT_STEPS.md")
# The direction doc is *allowed* alongside the product map and owns direction —
# listing NORTH_STAR here made a fully conformant repo warn forever.
PRODUCT_TRUTH = ("FEATURE_MAP.md", "FEATURES.md", "CAPABILITIES.md",
                 "PRODUCT.md")
CANONICAL_BACKLOG = "docs/NEXT_STEPS.md"

DONE_MARKERS = re.compile(r"^\s*[-*]\s*\[x\]|~~[^~]+~~|✅", re.M)


def excluded(path):
    return any(fnmatch(path, pat) for pat in EXCLUDED)


def markdown_files(tracked):
    return [f for f in tracked if f.endswith(".md")]


def check(ctx):
    out = []
    tracked = list(ctx.tracked)
    docs = [f for f in markdown_files(tracked) if f.startswith("docs/")]
    required = {s.satisfied_by for s in resolve_slots(ctx) if s.satisfied_by}

    out += _tokens_and_stamps(ctx, tracked, docs, required)
    out += _links(ctx, tracked, required)
    out += _duplicates(ctx, tracked)
    out += _claude_dir(ctx, tracked)
    return out


def _read(ctx, rel):
    try:
        return (Path(ctx.repo) / rel).read_text(errors="ignore")
    except OSError:
        return ""


def _tokens_and_stamps(ctx, tracked, docs, required):
    out = []
    stamped = 0
    for rel in docs:
        text = _read(ctx, rel)
        head = text[:800]
        is_scaffold = bool(SCAFFOLDED.search(head))
        has_stamp = bool(STAMP.search(head))

        if has_stamp:
            stamped += 1
        if is_scaffold and has_stamp:
            out.append(F.error(
                "25", "document is marked scaffolded and also carries a trust "
                      "stamp — a generated skeleton was never read against the code",
                path=rel))

        m = AS_OF.search(head)
        if m and ctx.version and _older(m.group(1), ctx.version):
            out.append(F.warn(
                "13", f"unverified since v{m.group(1)} (current {ctx.version})",
                path=rel))

    # Check 23. The `scaffold` baseline records how many required documents
    # were still skeletons at adoption; at or under it, an unwritten document
    # is debt rather than a regression. Without this the baseline is a
    # documented mechanism that nothing reads, and a freshly scaffolded repo
    # exits 1 with no way to absorb it — the exact failure it exists to prevent.
    scaffolded = []
    for rel in sorted(required):
        if rel == "docs/DOCMAP.md":
            continue  # generated; its tokens come from the documents it indexes
        text = _read(ctx, rel)
        hit = TODO_TOKEN.search(text)
        if hit:
            scaffolded.append((rel, text[:hit.start()].count("\n") + 1))

    baseline = _scaffold_baseline(ctx)
    for rel, line in scaffolded:
        if baseline is not None and len(scaffolded) <= baseline:
            out.append(F.warn(
                "23", f"still scaffolded — within the declared baseline of "
                      f"{baseline}, so this is debt rather than a regression",
                path=rel, line=line))
        else:
            out.append(F.error(
                "23", "required document still carries an unresolved "
                      "TODO(project-standard) token — scaffolded, not written"
                      + (f"; {len(scaffolded)} scaffolded documents exceeds the "
                         f"declared baseline of {baseline}"
                         if baseline is not None else ""),
                path=rel, line=line))

    if docs:
        out.append(F.warn(
            "12", f"trust stamps: {stamped}/{len(docs)} documents under docs/ "
                  f"carry `Last reviewed:`"))

    # Check 24 — a code map that names paths which do not exist.
    if "docs/PROJECT_MAP.md" in required:
        text = _read(ctx, "docs/PROJECT_MAP.md")
        missing = [p for p in _backticked_paths(text)
                   if not (Path(ctx.repo) / p).exists()]
        if missing:
            # A warn, not an error. Hand-auditing this check against a real code
            # map found most hits were legitimate prose: a sentence asserting a
            # directory does NOT exist, entries in an indented tree diagram
            # whose real path is nested, a proposed future layout, and a
            # deliberate cross-repository reference. Backtick position cannot
            # distinguish those from a genuinely stale path.
            out.append(F.warn(
                "24", f"{len(missing)} path(s) named in the code map do not "
                      f"resolve: " + ", ".join(f"`{p}`" for p in missing[:5])
                      + (" …" if len(missing) > 5 else "")
                      + " (prose and tree diagrams produce false hits — needs "
                        "a human eye)",
                path="docs/PROJECT_MAP.md"))
    return out


def _scaffold_baseline(ctx):
    raw = ctx.contract.raw.get("scaffold")
    if raw is None:
        return None
    try:
        return int(str(raw).split("/")[0])
    except (TypeError, ValueError):
        return None


def _backticked_paths(text):
    out = []
    for m in re.finditer(r"`([A-Za-z0-9_./-]+/[A-Za-z0-9_./-]*)`", text or ""):
        cand = m.group(1)
        if cand.startswith(("http", "//", "/")) or " " in cand:
            continue  # a leading slash is a URL path, not a file path
        out.append(cand.rstrip("/"))
    return sorted(set(out))


def _links(ctx, tracked, required):
    """Broken links error inside required docs, warn everywhere else."""
    out = []
    tracked_set = set(tracked)
    for rel in markdown_files(tracked):
        if excluded(rel):
            continue
        text = _read(ctx, rel)
        base = Path(rel).parent
        for m in MD_LINK.finditer(text):
            target = m.group(1).strip()
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            if target.startswith("/"):
                # Site-relative, not a file path. Joining it would resolve
                # against the checker's filesystem root, so `/tmp` would
                # "exist" and a real content route would not — link validation
                # must not depend on the machine it runs on.
                continue
            target = target.split("#")[0].strip()
            if not target:
                continue
            # Resolve against the repository, never against the process's
            # working directory. `base` is repo-relative, so resolving it bare
            # anchored the link at wherever the checker happened to be invoked
            # from — the same repository reported 0 errors or 62 depending on
            # the caller's cwd.
            root = Path(ctx.repo).resolve()
            try:
                resolved = str((root / base / target).resolve()
                               .relative_to(root))
            except (ValueError, OSError):
                resolved = str(Path(*(base / target).parts)).replace("\\", "/")
            exists = resolved in tracked_set or (root / resolved).exists()
            if exists:
                continue
            line = text[:m.start()].count("\n") + 1
            if rel in required:
                out.append(F.error("4", f"broken link to `{target}`",
                                   path=rel, line=line))
            else:
                out.append(F.warn("19", f"broken link to `{target}`",
                                  path=rel, line=line))
    return out


def _duplicates(ctx, tracked):
    out = []
    live = [f for f in markdown_files(tracked) if not excluded(f)]

    backlogs = [f for f in live if Path(f).name in BACKLOG_NAMES]
    others = [f for f in backlogs if f != CANONICAL_BACKLOG]
    if CANONICAL_BACKLOG in backlogs and others:
        for f in others:
            out.append(F.error(
                "26", f"second backlog beside `{CANONICAL_BACKLOG}` — merge it in; "
                      f"two roadmaps disagreeing is worse than none", path=f))
    elif len(others) > 1:
        incumbent = sorted(others)[0]
        for f in sorted(others)[1:]:
            out.append(F.error(
                "26", f"more than one backlog document and no canonical "
                      f"`{CANONICAL_BACKLOG}`; treating `{incumbent}` as the "
                      f"incumbent — merge this one into it, or rename the "
                      f"incumbent", path=f))

    truth = [f for f in live if Path(f).name in PRODUCT_TRUTH]
    if len(truth) > 1:
        out.append(F.warn(
            "18", "more than one document asserts product truth: "
                  + ", ".join(f"`{t}`" for t in sorted(truth))))

    if CANONICAL_BACKLOG in tracked:
        text = _read(ctx, CANONICAL_BACKLOG)
        hits = len(DONE_MARKERS.findall(text))
        if hits:
            out.append(F.warn(
                "28", f"{hits} line(s) look like completed items — the roadmap is "
                      f"future-only; done rows are deleted, not kept "
                      f"(pattern matching, needs a human eye)",
                path=CANONICAL_BACKLOG))

    prds = [f for f in tracked if f.startswith("docs/prds/") and f.endswith(".md")]
    for rel in prds:
        if Path(rel).name in ("README.md",):
            continue
        text = _read(ctx, rel)
        if not re.search(r"\*\*Status:\*\*", text, re.I):
            out.append(F.error("33", "PRD carries no `Status:` header", path=rel))
        if re.search(r"implementation[-_ ]status|current state", Path(rel).name,
                     re.I):
            out.append(F.warn(
                "36", "a state-asserting document inside docs/prds/ will be read "
                      "as current and will drift — it belongs in FEATURE_MAP.md",
                path=rel))

    stray = [f for f in tracked
             if re.search(r"(^|/)PRDs?[-_./]", f, re.I)
             and not f.startswith("docs/prds/") and not excluded(f)
             and f.endswith(".md")]
    for f in stray:
        out.append(F.error(
            "32", "PRD lives outside `docs/prds/`", path=f))
    return out


def _claude_dir(ctx, tracked):
    out = []
    repo = Path(ctx.repo)
    for d in (".claude/agents", ".claude/skills"):
        if (repo / d).is_dir() and not any(f.startswith(d + "/") for f in tracked):
            out.append(F.warn(
                "22", f"`{d}/` exists but nothing in it is tracked — project "
                      f"agents and skills are project knowledge"))
    return out


def _older(a, b):
    def parts(v):
        return tuple(int(x) for x in re.findall(r"\d+", v)[:3] or [0])
    return parts(a) < parts(b)
