"""Required artifacts, resolved as slots rather than filenames.

A slot is a question the repo must answer; several filenames may answer it.
`CLAUDE.md` or `AGENTS.md`. `DEVELOPMENT_FLOW.md` or `RELEASING.md`. Mandating
a specific filename is how a standard tells its best incumbent to rewrite
itself for a parser's convenience.
"""

from dataclasses import dataclass, field
from pathlib import Path

from . import findings as F
from .detect import DOCS, LIBRARY, PRODUCT

DIRECTION_NAMES = (
    "docs/NORTH_STAR.md", "NORTH_STAR.md",
    "docs/MISSION.md", "MISSION.md",
    "docs/VISION.md", "VISION.md",
)


# Slots a public repository may legitimately keep out of git, and the contract
# key that declares it. Internal prioritisation and release mechanics do not
# belong in a published repository; the standard should not force them there.
#
# The agent contract is deliberately absent from this map. It is the machine
# interface every check reads, a contributor cloning the repo needs it, and the
# declaration saying "the contract is local" would otherwise have to live
# inside the untracked contract nobody reads.
LOCAL_ALLOWED = {
    "roadmap": "next-steps",
    "release flow": "release-flow",
}


@dataclass
class Slot:
    name: str
    candidates: tuple
    severity: str = F.ERROR
    describes: str = ""
    satisfied_by: str = None
    local: bool = False
    declared_local: bool = False


def required_for(resolved, contract):
    """The slots this repo owes, given its profile and capabilities."""
    profile = resolved.profile
    slots = [
        Slot("agent contract", ("CLAUDE.md", "AGENTS.md"),
             describes="what this repo is, how to run it, its rules"),
        Slot("README", ("README.md",), describes="human entry point"),
        Slot("docmap", ("docs/DOCMAP.md",), describes="generated index"),
    ]
    if profile == DOCS:
        return slots

    slots += [
        Slot("code map", ("docs/PROJECT_MAP.md",)),
        Slot("product map", ("docs/FEATURE_MAP.md",)),
        # One canonical name, deliberately. `ROADMAP.md` and `TODO.md` are
        # reconciled by renaming, not by widening this list: two conformant
        # repositories with differently named roadmaps defeat the point of
        # having a standard, and unlike CLAUDE.md/AGENTS.md there is no
        # external constraint forcing the second spelling.
        Slot("roadmap", ("docs/NEXT_STEPS.md",)),
        Slot("release flow", ("docs/DEVELOPMENT_FLOW.md", "RELEASING.md",
                              "docs/RELEASING.md")),
        Slot("changelog", ("CHANGELOG.md", "docs/CHANGELOG.md")),
        Slot("direction", DIRECTION_NAMES,
             severity=F.WARN if profile == LIBRARY else F.ERROR,
             describes="mission, vision, north star"),
    ]
    if resolved.http_api:
        slots.append(Slot("api reference", ("docs/API_REFERENCE.md",)))
    if profile == LIBRARY:
        slots += [
            Slot("contributing", ("CONTRIBUTING.md",)),
            Slot("security", ("SECURITY.md",)),
        ]
    return slots


def resolve_slots(ctx):
    """Mark each slot satisfied or not.

    Tracked files only, except for the slots a repository has explicitly
    declared local — those are satisfied by a file on disk, and reported as
    local rather than passing silently.
    """
    tracked = set(ctx.tracked)
    slots = required_for(ctx.resolved, ctx.contract)
    for slot in slots:
        for cand in slot.candidates:
            if cand in tracked:
                slot.satisfied_by = cand
                break
        if slot.satisfied_by:
            continue
        key = LOCAL_ALLOWED.get(slot.name)
        if key and str(ctx.contract.raw.get(key, "")).strip() == "local":
            slot.declared_local = True
            for cand in slot.candidates:
                if (Path(ctx.repo) / cand).is_file():
                    slot.satisfied_by = cand
                    slot.local = True
                    break
    return slots


def check(ctx):
    out = []
    slots = resolve_slots(ctx)

    for slot in slots:
        if slot.satisfied_by:
            if slot.local:
                out.append(F.warn(
                    "1", f"{slot.name} is declared local and satisfied by an "
                         f"untracked `{slot.satisfied_by}` — deliberate, but "
                         f"invisible to anyone who clones this repository",
                    path=slot.satisfied_by))
            continue
        if slot.name == "direction" and _direction_declared(ctx):
            continue
        if slot.declared_local:
            # Declared local and not on disk: this is a clone, and a clone
            # cannot see it. Skipped, not missing — a check that could not run
            # must never read as one that failed.
            out.append(F.skipped(
                "1", f"{slot.name} is declared local; a clone cannot see it, "
                     f"so this cannot be answered here"))
            continue
        expected = " or ".join(f"`{c}`" for c in slot.candidates[:2])
        check_id = "30" if slot.name == "direction" else "1"
        out.append(F.Finding(
            check_id, slot.severity,
            f"missing {slot.name}: expected {expected}"
            + (f" — {slot.describes}" if slot.describes else "")))

    out += _contract_sections(ctx)
    return out


def _direction_declared(ctx):
    """`direction:` names the slot; `inherit` points at a parent product.

    A companion repo — a browser extension beside the web app it serves —
    has no separate mission. Demanding its own vision statement would
    manufacture a second place where one product's direction is stated.
    """
    declared = ctx.contract.direction
    if not declared:
        return False
    if str(declared).strip() == "inherit":
        return True
    target = Path(ctx.repo) / str(declared)
    return target.is_file() or str(declared) in set(ctx.tracked)


def _contract_sections(ctx):
    """Check 2 — the contract carries what the checks and a reader need."""
    out = []
    c = ctx.contract
    if not c.path:
        # Surface why, rather than the bare fact. "exists but is not tracked"
        # is actionable; "no agent contract to read" beside a file the user can
        # see on disk reads as a bug in the checker.
        return [F.error("2", f"contract: {msg}") for msg in c.errors] or \
            [F.error("2", "no agent contract to read")]

    for msg in c.errors:
        out.append(F.error("2", f"contract: {msg}", path=c.path))

    if str(c.raw.get("agent-contract", "")).strip() == "local":
        out.append(F.error(
            "2", "the agent contract cannot be declared local: it is the "
                 "interface every check reads, and the declaration saying so "
                 "would live in the file nobody reads", path=c.path))

    if c.critical_paths is None:
        out.append(F.error(
            "2", "contract declares no `critical-paths` — it may be empty, "
                 "but not absent; it marks where a wrong call ships a "
                 "fabricated result",
            path=c.path))
    if not c.adopted:
        out.append(F.error(
            "2", "contract declares no `adopted` baseline commit — without it "
                 "attribution rules cannot distinguish new commits from history",
            path=c.path))
    elif not ctx.git.commit_exists(c.adopted):
        # A shallow clone genuinely does not contain the commit, and saying it
        # "is not a commit in this repo" is a fabricated result — the failure
        # this whole tool is built against. The skip machinery exists for this.
        if not (ctx.profile == "ci" and not ctx.git.has_history()):
            out.append(F.error(
                "2", f"`adopted: {c.adopted}` is not a commit in this repo",
                path=c.path))

    body = (c.body or "").lower()
    for label, needles in (
        # Broad on purpose: a tool that only recognises npm and python tells
        # entire ecosystems their contract is wrong.
        ("how to run/test/build", (
            "## run", "## usage", "## development", "## getting started",
            "npm run", "npm test", "yarn ", "pnpm ", "bun ",
            "make ", "makefile", "just ",
            "pytest", "python3 -m", "python -m", "tox", "poetry ", "uv run",
            "cargo ", "go run", "go test", "go build",
            "gradle", "mvn ", "bundle exec", "rake ", "mix ", "dotnet ",
            "docker compose", "docker run", "./gradlew",
        )),
        ("the git-hygiene rules", ("co-authored", "attribution", "local-only",
                                   "contributor")),
        ("a pointer to DOCMAP", ("docmap",)),
    ):
        if not any(n in body for n in needles):
            out.append(F.error(
                "2", f"contract does not state {label}", path=c.path))

    # Only a declaration that actually contradicts detection is an override.
    # Firing on mere key presence made `init` — which is told to record its
    # answers as declarations — report three errors on a conformant repo, with
    # a message that was simply false: nothing had been overridden.
    overridden = {key for key, _, _ in ctx.resolved.overridden}
    for key in c.missing_reasons:
        if key in overridden:
            out.append(F.error(
                "2", f"`{key}` contradicts what detection found, with no "
                     f"`reason:` given", path=c.path))

    if c.critical_paths:
        for p in c.critical_paths:
            if not (Path(ctx.repo) / str(p).rstrip("/")).exists():
                out.append(F.warn(
                    "20", f"declared critical path `{p}` no longer exists",
                    path=c.path))
    return out
