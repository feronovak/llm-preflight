"""Where each definition in a source file starts and ends.

Shared by the citation check and the re-anchorer, which ask the same question
from opposite ends: "did this definition's lines change?" and "where did this
definition's lines go?". Both answer None for a file they cannot read — a
caller then falls back to the whole file, never to "untouched".

Python is read with `ast`, so qualified names are exact (`Class.method`,
`outer.inner`) and a range includes its decorators. TypeScript has no parser in
the standard library, so a deliberately conservative regex finds top-level
declarations only, each running to the line before the next one. The range
over-reaches — it swallows trailing comments and blank lines — which can only
make a citation read as touched when it was not, never the reverse.

A definition's behaviour also lives in the module-level names it reads: a
constant, an import, a helper. `reads_for` answers which, transitively, so a
citation of `fetch` is touched when `MAX_TRIES` moves.
"""

import ast
import re

PY_SUFFIXES = (".py", ".pyi")
TS_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")

WORD = re.compile(r"[A-Za-z_$][\w$]*")
TS_DECL = re.compile(
    r"^(?:export\s+(?:default\s+)?)?(?:declare\s+)?(?:async\s+)?"
    r"(?:abstract\s+class|class|function\*?|const|let|var|interface|type|enum|namespace)"
    r"\s+([A-Za-z_$][\w$]*)", re.M)


def symbols_for(path, source):
    """-> {qualified name: [(start, end), ...]}, or None when unreadable.

    A list per name, because a name can be defined twice — a property and its
    setter, a TYPE_CHECKING branch — and a caller that kept one range would
    certify the other unseen.
    """
    if source is None:
        return None
    if path.endswith(PY_SUFFIXES):
        return python_symbols(source)
    if path.endswith(TS_SUFFIXES):
        return ts_symbols(source)
    return None


def python_symbols(source):
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    out = {}

    def add(name, start, end):
        out.setdefault(name, []).append((start, end))

    def visit(body, prefix):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + node.name
                start = min([node.lineno] + [d.lineno for d in node.decorator_list])
                add(name, start, node.end_lineno)
                visit(node.body, name + ".")
            elif not prefix and isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        add(target.id, node.lineno, node.end_lineno)
            elif isinstance(node, (ast.If, ast.Try)) and not prefix:
                # `if TYPE_CHECKING:` / `try: import x` blocks define real
                # module-level names; skipping them would call those unknown.
                for part in ("body", "orelse", "finalbody"):
                    visit(getattr(node, part, []) or [], prefix)
                for handler in getattr(node, "handlers", []) or []:
                    visit(handler.body, prefix)

    visit(tree.body, "")
    return out


def ts_symbols(source):
    lines = source.splitlines()
    starts = [(source.count("\n", 0, m.start()) + 1, m.group(1))
              for m in TS_DECL.finditer(source)]
    out = {}
    for i, (start, name) in enumerate(starts):
        end = (starts[i + 1][0] - 1) if i + 1 < len(starts) else len(lines)
        while end > start and not lines[end - 1].strip():
            end -= 1
        out.setdefault(name, []).append((start, end))
    return out


def lookup(symbols, token):
    """Qualified names a citation's symbol may mean: exact; else, for a
    dotted token only, a suffix (`Inner.run` → `Outer.Inner.run`) or the head
    (`Foo.bar` → `Foo` where only top-level names are known).

    A bare word never suffix-matches. `get`, `price` and `main` are defined
    somewhere in most large files, and resolving one to an unrelated method
    narrows a citation to code the claim is not about.
    """
    if not symbols or not token:
        return []
    if token in symbols:
        return [token]
    if "." not in token:
        return []
    suffixed = [q for q in symbols if q.endswith("." + token)]
    if suffixed:
        return suffixed
    head = token.split(".", 1)[0]
    return [head] if head in symbols else []


def reads_for(path, source):
    """-> {qualified name: {module-level name: [(start, end), ...]}} — every
    module-level binding a definition reads, directly or through another
    such binding. None when unreadable."""
    if source is None:
        return None
    if path.endswith(PY_SUFFIXES):
        return _python_reads(source)
    if path.endswith(TS_SUFFIXES):
        return _ts_reads(source)
    return None


def _closure(direct, bindings, ranges):
    out = {}
    for name, seed in direct.items():
        seen, todo = set(), [d for d in seed if d in bindings]
        while todo:
            dep = todo.pop()
            if dep in seen:
                continue
            seen.add(dep)
            todo += [d for d in bindings[dep] if d in bindings and d not in seen]
        seen.discard(name)
        out[name] = {d: ranges[d] for d in sorted(seen)}
    return out


def _python_reads(source):
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None

    def loads(node):
        return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)
                and isinstance(n.ctx, ast.Load)}

    bindings, ranges = {}, {}

    def bind(name, node):
        bindings.setdefault(name, set()).update(loads(node))
        ranges.setdefault(name, []).append((node.lineno, node.end_lineno))

    def top(body):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bind(node.name, node)
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    for n in ast.walk(target):
                        if isinstance(n, ast.Name):
                            bind(n.id, node)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    bind(alias.asname or alias.name.split(".")[0], node)
            elif isinstance(node, (ast.If, ast.Try)):
                for part in ("body", "orelse", "finalbody"):
                    top(getattr(node, part, []) or [])
                for handler in getattr(node, "handlers", []) or []:
                    top(handler.body)

    top(tree.body)
    direct = {}

    def visit(body, prefix):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + node.name
                direct.setdefault(name, set()).update(loads(node))
                visit(node.body, name + ".")
            elif isinstance(node, (ast.If, ast.Try)) and not prefix:
                for part in ("body", "orelse", "finalbody"):
                    visit(getattr(node, part, []) or [], prefix)

    visit(tree.body, "")
    for name in bindings:
        direct.setdefault(name, set()).update(bindings[name])
    return _closure(direct, bindings, ranges)


def _ts_reads(source):
    """Top-level names a declaration's text mentions — a word match, which
    over-reaches into comments and strings and so can only widen."""
    decls = ts_symbols(source)
    lines = source.splitlines()
    words = {name: {w for s, e in rs for w in WORD.findall("\n".join(lines[s - 1:e]))}
             for name, rs in decls.items()}
    return _closure(words, words, decls)


def enclosing(symbols, line):
    """The innermost definition containing `line`, as (name, (start, end)).

    None when the line is at module level — outside every definition — or
    when two definitions of the same size both contain it, which is a guess.
    """
    best = []
    for name, ranges in (symbols or {}).items():
        for start, end in ranges:
            if start <= line <= end:
                best.append((end - start, name, (start, end)))
    if not best:
        return None
    best.sort()
    if len(best) > 1 and best[0][0] == best[1][0]:
        return None
    return best[0][1], best[0][2]


def overlaps(ranges, hunks):
    return any(s <= he and hs <= e for s, e in ranges for hs, he in hunks)
