"""Parse the agent contract's machine-readable block.

Stdlib has no YAML parser and this package takes no dependencies, so we parse a
deliberately tiny subset — the only shapes the contract is allowed to use:

    key: scalar
    key: [a, b]
    key:
      - item
    key: scalar
      reason: why the override is legitimate

Anything else becomes a parse error reported as a finding. The parser never
raises: a malformed contract must degrade into a finding, not a traceback.
"""

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

HEADING = re.compile(r"^##\s+project-standard\s*$", re.M)
FENCE = re.compile(r"^```(?:yaml|yml)?\s*$", re.M)

KEY = re.compile(r"^(?P<key>[A-Za-z][\w-]*):\s*(?P<value>.*)$")
ITEM = re.compile(r"^\s+-\s+(?P<item>.+?)\s*$")
SUB = re.compile(r"^\s+(?P<key>[A-Za-z][\w-]*):\s*(?P<value>.+?)\s*$")

CONTRACT_NAMES = ("CLAUDE.md", "AGENTS.md")

BOOLS = {"yes": True, "no": False, "true": True, "false": False}

# Keys that mean "I am overriding what detection found" and therefore owe a
# reason. A silent override is how a validator gets quietly disarmed.
OVERRIDE_KEYS = ("profile", "http-api", "channels")

# The grammar is closed: if a check reads it, it is a key, and nothing else is
# admissible. An open grammar cannot tell a future extension from a typo, and
# the typo is far more common — `chanels:` parsed clean, the typed accessor
# returned None, and the override the author believed in never took effect.
KNOWN_KEYS = (
    "adopted", "profile", "http-api", "channels", "direction", "prds",
    "critical-paths", "api-coverage", "scaffold", "local-only",
    "track-anyway", "ai-attribution", "agent-contract", "next-steps",
    "release-flow",
)


@dataclass
class Contract:
    path: str = None
    raw: dict = field(default_factory=dict)
    reasons: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    body: str = ""

    # -- typed accessors ---------------------------------------------------

    @property
    def adopted(self):
        return self.raw.get("adopted")

    @property
    def profile(self):
        return self.raw.get("profile")

    @property
    def http_api(self):
        return self.raw.get("http-api")

    @property
    def channels(self):
        v = self.raw.get("channels")
        return v if isinstance(v, list) else ([v] if v else None)

    @property
    def direction(self):
        return self.raw.get("direction")

    @property
    def prds(self):
        return self.raw.get("prds")

    @property
    def critical_paths(self):
        v = self.raw.get("critical-paths")
        if v is None:
            return None
        return v if isinstance(v, list) else [v]

    @property
    def baselines(self):
        return {k: self.raw[k] for k in
                ("api-coverage", "scaffold") if k in self.raw}

    @property
    def missing_reasons(self):
        return [k for k in OVERRIDE_KEYS
                if k in self.raw and not self.reasons.get(k)]

    @property
    def has_block(self):
        return bool(self.raw) or "no `## project-standard` block" not in \
            " ".join(self.errors)


def find_contract(repo, tracked):
    """Return the agent contract path, preferring CLAUDE.md.

    Both filenames satisfy the slot. Some projects use AGENTS.md deliberately
    to stay neutral across assistants, and hardcoding CLAUDE.md would break
    them.
    """
    tracked = set(tracked)
    present = [n for n in CONTRACT_NAMES if n in tracked]
    if present:
        return present[0]
    # Untracked but on disk: report it as absent, because every other check
    # reads tracked files. Two checks disagreeing about whether the contract
    # exists is worse than either answer.
    return None


def extract_block(text):
    """The first fenced block following the `## project-standard` heading."""
    m = HEADING.search(text or "")
    if not m:
        return None
    rest = text[m.end():]
    fences = list(FENCE.finditer(rest))
    if len(fences) < 2:
        return None
    return rest[fences[0].end():fences[1].start()].strip("\n")


def parse_contract(text, path=None):
    c = Contract(path=path, body=text or "")
    block = extract_block(text)
    if block is None:
        c.errors.append("no `## project-standard` block with a fenced body")
        return c

    last_key = None
    for lineno, line in enumerate(block.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        m = ITEM.match(line)
        if m:
            if last_key is None:
                c.errors.append(f"line {lineno}: list item before any key")
                continue
            c.raw.setdefault(last_key, [])
            if not isinstance(c.raw[last_key], list):
                c.raw[last_key] = []
            c.raw[last_key].append(_scalar(m.group("item")))
            continue

        m = SUB.match(line)
        if m and m.group("key") == "reason":
            if last_key is None:
                c.errors.append(f"line {lineno}: reason before any key")
            else:
                # A reason is free prose to a human. Stripping a `#` from it
                # truncates "see issue #42 for why" to "see issue".
                c.reasons[last_key] = m.group("value").strip()
            continue

        m = KEY.match(line)
        if m:
            last_key = m.group("key")
            if last_key not in KNOWN_KEYS:
                near = difflib.get_close_matches(last_key, KNOWN_KEYS, n=1)
                c.errors.append(
                    f"line {lineno}: unknown key `{last_key}`"
                    + (f" — did you mean `{near[0]}`?" if near else
                       f" (known keys: {', '.join(KNOWN_KEYS)})"))
            value = m.group("value").strip()
            c.raw[last_key] = _value(value) if value else []
            continue

        c.errors.append(f"line {lineno}: cannot parse {line.strip()!r}")

    return c


def load(repo, tracked):
    """Read and parse the repo's agent contract."""
    name = find_contract(repo, tracked)
    if not name:
        c = Contract()
        untracked = [n for n in CONTRACT_NAMES if (Path(repo) / n).is_file()]
        if untracked:
            c.errors.append(
                f"`{untracked[0]}` exists but is not tracked — every check reads "
                f"tracked files, so it cannot serve as the contract")
        else:
            c.errors.append("no agent contract (CLAUDE.md or AGENTS.md)")
        return c
    text = (Path(repo) / name).read_text(errors="ignore")
    return parse_contract(text, path=name)


def _strip_comment(raw):
    """Remove a trailing ` # ...` comment, respecting quotes.

    Every documented example annotates keys this way, and without stripping,
    `http-api: no  # ...` parses to a non-empty string — which is truthy, so a
    declared `no` silently became a yes.

    A regex lookbehind cannot express "not inside a quoted span"; an earlier
    attempt anchored on the whitespace instead and mangled both
    `direction: "a b.md" # why` and `reason: see issue #42`. Scanning once with
    a quote flag is the only correct way, and it is four lines.
    """
    raw = raw or ""
    quote = None
    for i, ch in enumerate(raw):
        if quote:
            if ch == quote:
                quote = None
        elif ch == '"':
            # Only double quotes open a span. Treating an apostrophe as a quote
            # made `it's-doc.md # why` swallow the comment.
            quote = ch
        elif ch == "#" and (i == 0 or raw[i - 1].isspace()):
            return raw[:i].strip()
    return raw.strip()


def _value(raw):
    raw = _strip_comment(raw)
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return [_scalar(p) for p in inner.split(",") if p.strip()] if inner else []
    return _scalar(raw)


def _scalar(raw):
    s = _strip_comment(raw).strip('"').strip("'")
    low = s.lower()
    if low in BOOLS:
        return BOOLS[low]
    return s
