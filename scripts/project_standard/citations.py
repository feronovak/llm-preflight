"""Code citations in prose, and whether a change actually touched one.

A document is stale when something it describes moved — not when any file it
names moved. File-level staleness flags a doc that cites one function because a
different function in the same 2,000-line module changed, and a gate that cries
wolf on most of the corpus at every release gets a bulk restamp in reply.

Four citation forms are read, all backticked, in prose and code samples alike:

    `path`            the whole file
    `path:N`          one line, as numbered at the certification point
    `path:N-M`        a range, likewise
    `path::Symbol`    a definition, by qualified name

Only `path::Symbol` narrows. A bare path cites the whole file whatever the
sentence around it mentions; reading a paragraph's other backticked words as
the claim's scope matched common words to unrelated definitions and marked
documents current while their claim moved. A definition's range includes the
module-level bindings it reads, so `MAX_TRIES = 1 → 5` touches the function
that retries.

Every unresolvable case — the file unreadable at the base, a language with no
symbol reader, a cited symbol that never existed — falls back to file-level,
which reads as touched whenever the file changed. Uncertainty widens the check;
it never narrows it.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from . import symbols as S
from .changes import Insertion
from .docs import AS_OF, STAMP
from .gitio import Git

CODE_SUFFIXES = ("py", "pyi", "ts", "tsx", "js", "jsx", "mjs", "cjs")
CITE = re.compile(
    r"`(?P<path>[A-Za-z0-9_.][A-Za-z0-9_./-]*\.(?:" + "|".join(CODE_SUFFIXES) + r"))"
    r"(?::(?P<start>\d+)(?:[-–](?P<end>\d+))?|::(?P<symbol>[A-Za-z_$][\w$.]*)(?:\(\))?)?`")


@dataclass(frozen=True)
class Citation:
    path: str
    line: int                      # where it sits in the document
    text: str                      # the backticked source, verbatim
    start: Optional[int] = None
    end: Optional[int] = None
    symbol: Optional[str] = None
    col: int = 0                   # where `text` starts in its line

    @property
    def form(self):
        if self.symbol:
            return "symbol"
        if self.start is not None:
            return "lines"
        return "file"


@dataclass(frozen=True)
class Touch:
    touched: bool
    reason: str


def parse(text):
    """Every code citation in `text`, fenced code included: a path in a code
    sample still points at the code, and the doc map's broken-reference check
    reads the same citations this does."""
    out = []
    # split on "\n" alone, as `reanchor` does, so a line number here is
    # the line it rewrites.
    for no, line in enumerate(text.split("\n"), 1):
        for m in CITE.finditer(line):
            start = int(m.group("start")) if m.group("start") else None
            end = int(m.group("end")) if m.group("end") else start
            out.append(Citation(path=m.group("path"), line=no, text=m.group(0),
                                start=start, end=end, symbol=m.group("symbol"),
                                col=m.start()))
    return out


def _symbols_at(repo, ref, path):
    """Symbols of `path` at `ref` (None = the working tree), None when no
    reader applies, or "absent" when the file does not exist there."""
    if ref is not None:
        sha = Git(repo).resolve(ref)
        return _symbols_at_ref(repo, sha, path) if sha else "absent"
    target = Path(repo) / path
    if not target.is_file():
        return "absent"
    return S.symbols_for(path, target.read_text(errors="ignore"))


@lru_cache(maxsize=4096)
def _symbols_at_ref(repo, ref, path):
    # Cached by ref: a committed blob cannot change under a running process.
    source = Git(repo).file_at(ref, path)
    return S.symbols_for(path, source) if source is not None else "absent"


def _reads_at(repo, ref, path):
    sha = Git(repo).resolve(ref)
    return _reads_at_ref(repo, sha, path) if sha else {}


@lru_cache(maxsize=4096)
def _reads_at_ref(repo, ref, path):
    source = Git(repo).file_at(ref, path)
    return (S.reads_for(path, source) or {}) if source is not None else {}


def touched(citation, hunks, base, repo, head="HEAD"):
    """Did the change from `base` to `head` touch what `citation` cites?

    `hunks` is `changes.changed_hunks(repo, base, head)`. `head=None` reads the
    working tree. -> Touch(touched, reason).
    """
    changed = hunks.get(citation.path)
    if changed is None:
        return Touch(False, "file unchanged")
    if citation.form == "lines":
        rng = [(citation.start, citation.end or citation.start)]
        # New text inserted directly before line N now sits where the reader
        # of `path:N` lands.
        before_first = any(isinstance(h, Insertion) and h[1] == citation.start - 1
                           for h in changed)
        return (Touch(True, f"lines {citation.start}-{citation.end} changed")
                if before_first or S.overlaps(rng, changed)
                else Touch(False, "cited lines unchanged"))
    if citation.form == "file":
        return Touch(True, "file changed; a bare path is file-level")

    before = _symbols_at(str(repo), base, citation.path)
    if before == "absent":
        return Touch(True, "file did not exist at the certification point")
    if before is None:
        return Touch(True, "no symbol reader for this file; file-level")

    names = S.lookup(before, citation.symbol)
    if not names:
        return Touch(True, f"`{citation.symbol}` not defined here at the base; file-level")

    after = _symbols_at(str(repo), head, citation.path)
    reads = _reads_at(str(repo), base, citation.path)
    for name in names:
        if S.overlaps(before[name], changed):
            return Touch(True, f"`{name}` changed")
        for dep, ranges in (reads.get(name) or {}).items():
            if S.overlaps(ranges, changed):
                return Touch(True, f"`{dep}`, which `{name}` reads, changed")
        if after in (None, "absent") or name not in after:
            return Touch(True, f"`{name}` removed or renamed")
    return Touch(False, "cited symbol unchanged: " + ", ".join(sorted(names)))


def certification_ref(repo, text):
    """The commit a document was last certified at: its `As of:` tag, else the
    last commit before its `Last reviewed:` date. None when it declares
    neither, or neither resolves."""
    git = Git(repo)
    head = text[:3000]
    asof = AS_OF.search(head)
    if asof:
        for candidate in (f"v{asof.group(1)}", asof.group(1)):
            if git.commit_exists(candidate):
                return candidate
    stamp = STAMP.search(head)
    if stamp:
        return git.commit_before(stamp.group(1))
    return None
