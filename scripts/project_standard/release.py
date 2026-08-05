"""Version source, tag resolution, and the three-way release gate.

Two rules here exist because a flat version of each got the real fleet wrong:

  - Tag resolution is by ancestry, never by sorting. One repo renumbered
    downward and carries v2.2.0 above its current v1.7.x line; sorting reads
    the wrong tag as latest and invents a three-major discrepancy.
  - The version source is whichever manifest the tags corroborate. A flat
    "npm wins" rule picks 5.0.0 in a Flask+npm repo whose every tag says
    0.13.2 — the one number nothing agrees with.
"""

import json
import re
from pathlib import Path

from . import findings as F
from .gitio import parse_tag

CHANGELOG_NAMES = ("CHANGELOG.md", "docs/CHANGELOG.md")
UNRELEASED = re.compile(r"^##\s*\[?unreleased\]?", re.I | re.M)
BUMP_WORDS = ("major", "minor", "patch")
BREAKING = re.compile(r"breaking|\bbreak(s|ing)?\b|removed|incompatible", re.I)

# Paths that cannot reach a released artifact. A changelog records what changed
# for whoever consumes the release; a commit touching only these changed
# nothing for them, and demanding an entry for it trains people to ignore the
# check. Adopting this standard is itself such a commit.
NOT_SHIPPED = (
    "docs/**", "*.md", "LICENSE", ".github/**",
    "tests/**", "test/**", "spec/**", "e2e/**",
    ".gitignore", ".gitattributes", ".editorconfig",
    "*.tmpl", "examples/**",
)


def candidates(repo):
    """Every manifest that states a version, with its value."""
    repo = Path(repo)
    out = []
    pkg = repo / "package.json"
    if pkg.is_file():
        try:
            v = json.loads(pkg.read_text(errors="ignore")).get("version")
            if v:
                out.append(("package.json", str(v)))
        except ValueError:
            pass
    pyp = repo / "pyproject.toml"
    if pyp.is_file():
        m = re.search(r'^version\s*=\s*"([^"]+)"',
                      pyp.read_text(errors="ignore"), re.M)
        if m:
            out.append(("pyproject.toml", m.group(1)))
    ver = repo / "VERSION"
    if ver.is_file():
        v = ver.read_text(errors="ignore").strip()
        if v:
            out.append(("VERSION", v))
    return out


def version_source(repo, tags):
    """Pick the source the tags corroborate; tie-break to the backend."""
    cands = candidates(repo)
    if not cands:
        return (None, None)
    if len(cands) == 1:
        return cands[0]

    tagged = set()
    for t in tags or []:
        p = parse_tag(t)
        if p:
            tagged.add(".".join(str(n) for n in p[1]))

    corroborated = [c for c in cands if c[1] in tagged]
    if len(corroborated) == 1:
        return corroborated[0]
    if corroborated:
        return corroborated[0]

    order = {"pyproject.toml": 0, "VERSION": 1, "package.json": 2}
    return sorted(cands, key=lambda c: order.get(c[0], 3))[0]


def changelog_path(tracked):
    for name in CHANGELOG_NAMES:
        if name in tracked:
            return name
    return None


def check(ctx):
    out = []
    if ctx.resolved.profile == "docs":
        return out

    tags = ctx.git.tags()
    cands = candidates(ctx.repo)
    source, version = version_source(ctx.repo, tags)

    if len(cands) > 1:
        chosen = [c for c in cands if c[0] == source]
        others = [c for c in cands if c[0] != source]
        if any(c[1] != version for c in others):
            tagged = {".".join(str(n) for n in p[1])
                      for t in tags if (p := parse_tag(t))}
            why = ("corroborated by the tags" if version in tagged
                   else "chosen by ecosystem precedence — no tag corroborates "
                        "any of them")
            out.append(F.error(
                "5b", "more than one version source disagrees: "
                     + ", ".join(f"{n}={v}" for n, v in cands)
                     + f" — `{source}` is {why}; the others must be brought "
                       f"into line or declared decorative"))

    out += _release_gate(ctx, tags, source, version)
    out += _regressions(ctx, tags)
    out += _unreleased(ctx, tags)
    out += _bump_table(ctx)
    return out


def _release_gate(ctx, tags, source, version):
    """Check 5 — tag, version source and changelog agree."""
    out = []
    head_tags = [t for t in ctx.git.tags_at_head() if parse_tag(t)]
    if not head_tags or not version:
        return out

    chlog = changelog_path(ctx.tracked)
    text = ""
    if chlog:
        text = (Path(ctx.repo) / chlog).read_text(errors="ignore")

    for tag in head_tags:
        channel, nums, pre = parse_tag(tag)
        base = ".".join(str(n) for n in nums)
        if base != version:
            out.append(F.error(
                "5", f"tag `{tag}` and {source}={version} disagree"))
        if pre:
            continue  # a pre-release cut released nothing
        if chlog and not re.search(rf"^##\s*\[?{re.escape(base)}\]?", text, re.M):
            out.append(F.error(
                "5", f"tag `{tag}` has no `{base}` section in {chlog}",
                path=chlog))
    return out


def _regressions(ctx, tags):
    """Checks 15 and 38 — one fact pattern, split on the adoption baseline."""
    out = []
    adopted = ctx.contract.adopted
    adopted_ok = bool(adopted) and ctx.git.commit_exists(adopted)

    per_channel = {}
    for t in ctx.git.tags_by_history():
        p = parse_tag(t)
        if not p or p[2]:
            continue
        per_channel.setdefault(p[0], []).append((t, p[1]))

    for channel, entries in sorted(per_channel.items()):
        for (prev_tag, prev), (tag, cur) in zip(entries, entries[1:]):
            if cur >= prev:
                continue
            msg = (f"release `{tag}` is lower than the earlier `{prev_tag}` "
                   f"on channel `{channel}`")
            after = adopted_ok and _tag_after(ctx, adopted, tag)
            if after:
                out.append(F.error("38", msg))
            else:
                out.append(F.warn("15", msg + " (before the adoption baseline)"))

    current = version_source(ctx.repo, tags)[1]
    if current:
        cur_nums = tuple(int(x) for x in re.findall(r"\d+", current)[:3] or [0])
        higher = sorted({t for t in tags
                         if (p := parse_tag(t)) and not p[2] and p[1] > cur_nums})
        if higher:
            out.append(F.warn(
                "15", "tags sort above the current version and will mislead any "
                      "tool that resolves 'latest' by sorting: "
                      + ", ".join(f"`{t}`" for t in higher)))
    return out


def _tag_after(ctx, adopted, tag):
    out = ctx.git._run("merge-base", "--is-ancestor", adopted, tag)
    return out is not None


def _unreleased(ctx, tags):
    """Check 29 — work landing with nothing recorded for the next release."""
    out = []
    chlog = changelog_path(ctx.tracked)
    if not chlog:
        return out
    latest = ctx.git.describe()
    if not latest:
        return out
    # Only commits that change something a consumer could observe. Counting
    # every commit means this fires the moment anyone edits a document — and
    # adopting this standard *is* a documentation change, so it would nag every
    # repository immediately after onboarding. A changelog records what changed
    # for the reader, and a docs-only run of commits changed nothing for them.
    count = ctx.git._run("rev-list", "--count", f"{latest}..HEAD", "--",
                         ".", *(f":(exclude){p}" for p in NOT_SHIPPED))
    if not count or int(count) == 0:
        return out
    text = (Path(ctx.repo) / chlog).read_text(errors="ignore")
    if not UNRELEASED.search(text):
        out.append(F.warn(
            "29", f"{count} commit(s) since `{latest}` but no `[Unreleased]` "
                  f"section — changes are landing with nothing recorded for "
                  f"the next release", path=chlog))
    return out


def _bump_table(ctx):
    """Checks 37 / 37b — the flow doc names a real consumer."""
    out = []
    flow = next((p for p in ("docs/DEVELOPMENT_FLOW.md", "RELEASING.md",
                             "docs/RELEASING.md") if p in ctx.tracked), None)
    if not flow:
        return out
    text = (Path(ctx.repo) / flow).read_text(errors="ignore").lower()
    if not all(w in text for w in BUMP_WORDS):
        out.append(F.error(
            "37", "release flow has no bump table covering major, minor and patch",
            path=flow))
        return out
    if not any(w in text for w in ("consumer", "caller", "buyer", "user",
                                   "importer", "adapt")):
        out.append(F.warn(
            "37b", "the bump table restates generic semver without naming who "
                   "this product's consumer is (needs a human eye)", path=flow))
    return out
