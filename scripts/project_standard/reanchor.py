"""`reanchor` — move `path:N` citations to where their definition went.

A line citation rots silently: the file still has a line N, it just holds
something else now, and the reader who follows it believes what they land on.
This finds the definition that enclosed line N at the document's certification
point, finds the same qualified name at HEAD, and moves the number by the same
offset within it.

It never guesses. A citation stays as written, and is reported, when:

- the document has no certification point to read the old file at;
- the line sat at module level, outside every definition;
- the name is missing at HEAD, or defined more than once at either end;
- the citation is a bare file name (`Verdict.tsx:138`) rather than a path;
- the cited text is no longer at the offset and does not occur exactly once
  inside the moved definition — an offset into a rewritten body is a guess.

Dry-run by default; `--write` edits the documents in place.
"""

import difflib
import sys
from dataclasses import dataclass
from pathlib import Path

from . import citations, symbols as S
from .gitio import Git, repo_root

REANCHORED, UNCHANGED, UNRESOLVED, SKIPPED = "re-anchored", "unchanged", "unresolved", "skipped"


@dataclass
class Result:
    doc: str
    line: int
    old: str
    status: str
    new: str = None
    reason: str = ""


def _find(git, ref, path, cache):
    key = (ref, path)
    if key not in cache:
        text = git.file_at(ref, path)
        cache[key] = (text, S.symbols_for(path, text) if text is not None else None)
    return cache[key]


def anchor(git, cite, ref, cache, head="HEAD"):
    """-> (status, new citation text or None, reason) for one citation."""
    if "/" not in cite.path and not (git.repo / cite.path).is_file():
        # `Verdict.tsx:138` names a file, not a path; picking one of several
        # same-named files would be the guess this command exists not to make.
        return SKIPPED, None, "a bare file name, not a repo-relative path"
    if ref is None:
        return UNRESOLVED, None, "document has no certification point"
    old_text, before = _find(git, ref, cite.path, cache)
    if old_text is None:
        return UNRESOLVED, None, f"not in the tree at {ref}"
    if before is None:
        kind = SKIPPED if not cite.path.endswith(S.PY_SUFFIXES + S.TS_SUFFIXES) else UNRESOLVED
        return kind, None, f"no definitions readable at {ref}"
    start, end = cite.start, cite.end or cite.start
    found = S.enclosing(before, start)
    if found is None:
        return UNRESOLVED, None, "module level, outside every definition"
    name, (bs, be) = found
    if not bs <= end <= be:
        return UNRESOLVED, None, f"range runs past `{name}`"
    if len(before[name]) != 1:
        return UNRESOLVED, None, f"`{name}` is defined more than once at {ref}"
    new_text, after = _find(git, head, cite.path, cache)
    if new_text is None or after is None:
        return UNRESOLVED, None, f"file missing or unreadable at {head}"
    ranges = after.get(name, [])
    if len(ranges) != 1:
        return UNRESOLVED, None, (f"`{name}` not found at {head}" if not ranges
                                  else f"`{name}` is not unique at {head}")
    hs, he = ranges[0]
    old_lines, new_lines = old_text.splitlines(), new_text.splitlines()
    block = [ln.strip() for ln in old_lines[start - 1:end]]
    span = end - start

    def fits(at):
        return hs <= at and at + span <= he and \
            [ln.strip() for ln in new_lines[at - 1:at + span]] == block

    target = hs + (start - bs)
    if not fits(target):
        hits = [at for at in range(hs, he - span + 1) if fits(at)]
        if len(hits) != 1:
            return UNRESOLVED, None, (f"cited text in `{name}` changed" if not hits
                                      else f"cited text occurs {len(hits)}× in `{name}`")
        target = hits[0]
    if target == start:
        return UNCHANGED, None, f"`{name}` did not move"
    suffix = f"{target}-{target + span}" if cite.end and cite.end != cite.start else f"{target}"
    return REANCHORED, f"`{cite.path}:{suffix}`", f"`{name}` moved {target - start:+d}"


def reanchor_doc(repo, rel, text, cache, head="HEAD"):
    git = Git(repo)
    ref = citations.certification_ref(repo, text)
    results, lines, edits = [], text.split("\n"), []
    for cite in citations.parse(text):
        if cite.form != "lines":
            continue
        status, new, reason = anchor(git, cite, ref, cache, head)
        results.append(Result(rel, cite.line, cite.text, status, new, reason))
        if new:
            edits.append((cite.line, cite.col, cite.text, new))
    # Right to left by column, at the span each citation was read from: a
    # replace over the whole line would also rewrite a second citation that
    # happens to read like the first one's new text.
    for no, col, old, new in sorted(edits, reverse=True):
        line = lines[no - 1]
        lines[no - 1] = line[:col] + new + line[col + len(old):]
    return "\n".join(lines), results


def main(args):
    repo = repo_root(Path(args.repo))
    git = Git(repo)
    tracked = git.ls_files()
    docs = args.docs or [p for p in tracked if p.startswith("docs/") and p.endswith(".md")]
    cache, counts, unresolved = {}, {}, []
    for rel in docs:
        path = repo / rel
        if not path.is_file():
            print(f"reanchor: `{rel}` does not exist", file=sys.stderr)
            return 2
        text = path.read_text()
        new, results = reanchor_doc(repo, rel, text, cache)
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
            if r.status == UNRESOLVED:
                unresolved.append(r)
        if new != text:
            if args.write:
                path.write_text(new)
            else:
                sys.stdout.writelines(difflib.unified_diff(
                    text.splitlines(True), new.splitlines(True), f"a/{rel}", f"b/{rel}"))
    for r in unresolved:
        print(f"unresolved  {r.doc}:{r.line}  {r.old} — {r.reason}")
    summary = " · ".join(f"{k} {counts.get(k, 0)}" for k in
                         (REANCHORED, UNCHANGED, UNRESOLVED, SKIPPED))
    print(f"\n{summary}" + ("" if args.write else "  (dry run — `--write` applies)"))
    return 0
