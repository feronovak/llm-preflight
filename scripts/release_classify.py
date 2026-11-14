"""Decide whether a release changes only model data.

Usage: ``release_classify.py --base <tag> --head <sha>``.

Prints one JSON object ``{qualifies, base, head, version, reasons}`` and exits
0 when the range qualifies as an automatic maintenance release, 1 when it does
not, 2 on an error (unreadable range, unparsable source, bad arguments).

The check is mechanical and conservative: every changed path must fall into a
known class, and Python data files must be identical to the base once their
data tables are blanked. A wrong "no" costs one manual tag; a wrong "yes" would
publish unreviewed logic. Run this script from the base tag, never from the
head, so a range cannot approve itself.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess  # nosec B404
import sys
from datetime import date
from typing import Any

# Python files whose module-level data tables may change, and only those.
DATA_TABLES: dict[str, tuple[str, ...]] = {
    "llm_preflight/pricing.py": (
        "PUBLIC_PRICING",
        "_PROVIDER_PRICING_PAGES",
        "_MODEL_PRICING_PAGES",
        "PUBLIC_PRICING_CHANGES",
        "PUBLIC_PRICING_DETAILS",
    ),
    "llm_preflight/retirements.py": (
        "_ANTHROPIC",
        "_OPENAI",
        "_GEMINI",
        "_REVIEWED",
        "ANTHROPIC_DEPRECATIONS_URL",
        "OPENAI_DEPRECATIONS_URL",
        "GEMINI_DEPRECATIONS_URL",
    ),
}
# Functions a table value may call. Their definitions stay in the skeleton.
BUILDERS: dict[str, tuple[str, ...]] = {
    "llm_preflight/pricing.py": ("date",),
    "llm_preflight/retirements.py": ("_row", "_anthropic", "_openai"),
}

PYPROJECT = "pyproject.toml"
INIT = "llm_preflight/__init__.py"
JSON_VERSION_FILES = (
    "server.json",
    "plugins/llm-preflight/.codex-plugin/plugin.json",
)
VERSION_FILES = (PYPROJECT, INIT, *JSON_VERSION_FILES)
CHANGELOG = "CHANGELOG.md"

# Any change qualifies.
DATA_DOC_PATTERNS = (
    r"docs/data/.*",
    r"docs/images/measured-models-[^/]*\.svg",
    r"docs/guides/observed-model-comparison\.md",
    r"docs/guides/current-snapshots\.md",
    r"docs/development/visual-assets\.md",
    r"docs/DOCMAP\.md",
    r"docs/index\.md",
    r"README\.md",
    r"tests/test_pricing\.py",
    r"tests/test_retirements\.py",
    r"tests/test_model_updates\.py",
    r"tests/test_documentation\.py",
    r"tests/test_package\.py",
)
# Only a substitution of the previous release's version qualifies.
PIN_PATTERNS = (
    r"action\.yml",
    r"examples/.*",
    r"docs/.*\.md",
    r"tests/test_distribution\.py",
)

_VERSION = re.compile(r"\d+\.\d+\.\d+")
_TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
_PYPROJECT_VERSION = re.compile(r'^version = "(\d+\.\d+\.\d+)"$', re.MULTILINE)
_PLAIN_CONSTANTS = (str, int, float, bool, type(None))
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


class ClassifierError(Exception):
    """The range cannot be read or parsed; the CLI exits 2."""


def _git(*args: str) -> bytes:
    try:
        done = subprocess.run(  # nosec B603 B607
            ["git", *args], capture_output=True, check=True, timeout=60
        )
    except (OSError, subprocess.SubprocessError) as error:
        detail = getattr(error, "stderr", b"") or b""
        raise ClassifierError(
            f"git {args[0]} failed: {detail.decode(errors='replace').strip()}"
        ) from error
    return done.stdout


def _show(rev: str, path: str) -> str:
    try:
        return _git("show", f"{rev}:{path}").decode("utf-8")
    except UnicodeDecodeError as error:
        raise ClassifierError(f"{path} at {rev} is not UTF-8") from error


def _parse(source: str, label: str) -> ast.Module:
    try:
        return ast.parse(source)
    except (SyntaxError, ValueError) as error:
        raise ClassifierError(f"{label} does not parse: {error}") from error


def _changes(base: str, head: str) -> list[tuple[str, list[str]]]:
    raw = _git("diff", "--name-status", "-M", "-z", base, head).decode("utf-8")
    parts = raw.split("\0")
    changes: list[tuple[str, list[str]]] = []
    index = 0
    while index < len(parts) and parts[index]:
        status = parts[index]
        count = 2 if status[0] in "RC" else 1
        changes.append((status, parts[index + 1 : index + 1 + count]))
        index += 1 + count
    return changes


# --- Python data files ---------------------------------------------------------


def _table_name(stmt: ast.stmt, tables: tuple[str, ...]) -> str | None:
    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
        target = stmt.targets[0]
    elif isinstance(stmt, ast.AnnAssign):
        target = stmt.target
    else:
        return None
    if isinstance(target, ast.Name) and target.id in tables:
        return target.id
    return None


def _table_statements(
    tree: ast.Module, tables: tuple[str, ...]
) -> dict[str, list[ast.stmt]]:
    found: dict[str, list[ast.stmt]] = {name: [] for name in tables}
    for stmt in tree.body:
        name = _table_name(stmt, tables)
        if name:
            found[name].append(stmt)
    return found


def _skeleton(tree: ast.Module, tables: tuple[str, ...]) -> str:
    body: list[ast.stmt] = []
    for stmt in tree.body:
        if _table_name(stmt, tables) is None:
            body.append(stmt)
        elif isinstance(stmt, ast.AnnAssign):
            body.append(ast.AnnAssign(stmt.target, stmt.annotation, None, stmt.simple))
        else:
            assert isinstance(stmt, ast.Assign)
            body.append(ast.Assign(stmt.targets, ast.Constant(None)))
    return ast.dump(ast.Module(body, []))


def _blank_iters(node: ast.AST) -> str:
    clone = ast.parse(ast.unparse(node), mode="eval").body
    for sub in ast.walk(clone):
        if isinstance(sub, _COMPREHENSIONS):
            for generator in sub.generators:
                generator.iter = ast.Constant(None)
    return ast.dump(clone)


def _is_literal_sequence(node: ast.expr) -> bool:
    return isinstance(node, (ast.Tuple, ast.List)) and all(
        isinstance(item, ast.Constant) and isinstance(item.value, _PLAIN_CONSTANTS)
        for item in node.elts
    )


class _ValueChecker:
    """Allow only literal data in a table value (see module docstring)."""

    def __init__(
        self, tables: tuple[str, ...], builders: tuple[str, ...], base: ast.AST
    ):
        self.tables = tables
        self.builders = builders
        self.shapes: set[str] = set()
        self.iters: set[str] = set()
        for node in ast.walk(base):
            if isinstance(node, _COMPREHENSIONS):
                self.shapes.add(_blank_iters(node))
                self.iters.update(ast.dump(g.iter) for g in node.generators)

    def problems(self, node: ast.AST | None) -> list[str]:
        if node is None:  # the key of a "**" unpacking
            return []
        if isinstance(node, ast.Constant):
            ok = isinstance(node.value, _PLAIN_CONSTANTS)
            return [] if ok else [f"constant {node.value!r}"]
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return self._all(node.elts)
        if isinstance(node, ast.Dict):
            return self._all([*node.keys, *node.values])
        if isinstance(node, ast.UnaryOp):
            numeric = isinstance(node.operand, ast.Constant) and isinstance(
                node.operand.value, (int, float)
            )
            return [] if isinstance(node.op, ast.USub) and numeric else ["unary op"]
        if isinstance(node, ast.Name):
            return [] if node.id in self.tables else [f"name {node.id}"]
        if isinstance(node, ast.Call):
            return self._call(node)
        if isinstance(node, _COMPREHENSIONS):
            return self._comprehension(node)
        return [type(node).__name__]

    def _all(self, nodes: list[Any]) -> list[str]:
        return [reason for node in nodes for reason in self.problems(node)]

    def _call(self, node: ast.Call) -> list[str]:
        if not (isinstance(node.func, ast.Name) and node.func.id in self.builders):
            return ["call of a non-builder"]
        keywords = [keyword.value for keyword in node.keywords]
        if any(keyword.arg is None for keyword in node.keywords):
            return ["** argument"]
        return self._all([*node.args, *keywords])

    def _comprehension(self, node: ast.AST) -> list[str]:
        if _blank_iters(node) not in self.shapes:
            return ["comprehension differs from the base"]
        for sub in ast.walk(node):
            if not isinstance(sub, _COMPREHENSIONS):
                continue
            for generator in sub.generators:
                unchanged = ast.dump(generator.iter) in self.iters
                if not (unchanged or _is_literal_sequence(generator.iter)):
                    return ["comprehension source is not a literal"]
        return []


def _data_file_reasons(path: str, base: str, head: str) -> list[str]:
    tables = DATA_TABLES[path]
    base_tree = _parse(_show(base, path), f"{path} at {base}")
    head_tree = _parse(_show(head, path), f"{path} at {head}")
    reasons = [
        f"{path}: {name} is assigned {len(stmts)} times, not once"
        for name, stmts in _table_statements(head_tree, tables).items()
        if len(stmts) != 1
    ]
    if reasons:
        return reasons
    if _skeleton(base_tree, tables) != _skeleton(head_tree, tables):
        return [f"{path}: code outside the data tables changed"]
    checker = _ValueChecker(tables, BUILDERS[path], base_tree)
    for name, (stmt,) in _table_statements(head_tree, tables).items():
        assert isinstance(stmt, (ast.Assign, ast.AnnAssign))
        reasons += [
            f"{path}: {name} contains {problem}"
            for problem in checker.problems(stmt.value)
        ]
    return reasons


# --- Version files -------------------------------------------------------------


def _strip_json_versions(document: Any) -> tuple[Any, list[str]]:
    """Drop the top-level and per-package ``version`` keys; return them."""
    if not isinstance(document, dict):
        return document, []
    stripped = dict(document)
    versions = [str(stripped.pop("version", ""))]
    packages = stripped.get("packages")
    if isinstance(packages, list):
        stripped["packages"] = []
        for package in packages:
            if isinstance(package, dict):
                package = dict(package)
                versions.append(str(package.pop("version", "")))
            stripped["packages"].append(package)
    return stripped, versions


def _json_versions(path: str, base: str, head: str) -> tuple[list[str], list[str]]:
    try:
        before = json.loads(_show(base, path))
        after = json.loads(_show(head, path))
    except json.JSONDecodeError as error:
        raise ClassifierError(f"{path} is not valid JSON: {error}") from error
    stripped_before, _ = _strip_json_versions(before)
    stripped_after, versions = _strip_json_versions(after)
    reasons = (
        []
        if stripped_before == stripped_after
        else [f"{path}: non-version key changed"]
    )
    return reasons, versions


def _init_version(source: str, label: str) -> tuple[str, str]:
    tree = _parse(source, label)
    version = ""
    body: list[ast.stmt] = []
    for stmt in tree.body:
        is_version = (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and stmt.targets[0].id == "__version__"
        )
        if is_version:
            assert isinstance(stmt, ast.Assign)
            value = stmt.value
            version = value.value if isinstance(value, ast.Constant) else ""
            stmt = ast.Assign(stmt.targets, ast.Constant(None))
        body.append(stmt)
    return str(version), ast.dump(ast.Module(body, []))


def _pyproject_reasons(base: str, head: str) -> tuple[list[str], list[str]]:
    before, after = _show(base, PYPROJECT), _show(head, PYPROJECT)
    found = _PYPROJECT_VERSION.findall(after)
    if len(_PYPROJECT_VERSION.findall(before)) != 1 or len(found) != 1:
        return [f"{PYPROJECT}: version line not found once"], []
    blank = _PYPROJECT_VERSION.sub('version = ""', before)
    if blank != _PYPROJECT_VERSION.sub('version = ""', after):
        return [f"{PYPROJECT}: a line other than version changed"], found
    return [], found


def _version_reasons(
    base: str, head: str, base_version: str
) -> tuple[list[str], str | None]:
    reasons, found = _pyproject_reasons(base, head)
    _, skeleton_before = _init_version(_show(base, INIT), INIT)
    init_after, skeleton_after = _init_version(_show(head, INIT), INIT)
    if skeleton_before != skeleton_after:
        reasons.append(f"{INIT}: code other than __version__ changed")
    found.append(init_after)
    for path in JSON_VERSION_FILES:
        problems, versions = _json_versions(path, base, head)
        reasons += problems
        found += versions
    distinct = set(found)
    if len(distinct) != 1:
        return [*reasons, f"version files disagree: {sorted(distinct)}"], None
    (version,) = distinct
    if _VERSION.fullmatch(version) is None:
        return [*reasons, f"version {version!r} is not X.Y.Z"], None
    major, minor, patch = (int(part) for part in base_version.split("."))
    if version != f"{major}.{minor}.{patch + 1}":
        reasons.append(f"version {version} is not a patch bump of {base_version}")
    if _git("for-each-ref", f"refs/tags/v{version}"):
        reasons.append(f"tag v{version} already exists")
    return reasons, version


def _changelog_reasons(head: str, version: str) -> list[str]:
    heading = re.compile(
        rf"^## {re.escape(version)} - (\d{{4}}-\d{{2}}-\d{{2}})$", re.MULTILINE
    )
    match = heading.search(_show(head, CHANGELOG))
    if match is None:
        return [f"{CHANGELOG}: no '## {version} - <date>' heading"]
    try:
        date.fromisoformat(match.group(1))
    except ValueError:
        return [f"{CHANGELOG}: invalid date {match.group(1)}"]
    return []


# --- Previous-release pin ------------------------------------------------------


def _pin_reasons(path: str, base: str, head: str, base_version: str) -> list[str]:
    try:
        before = _show(base, path).splitlines()
        after = _show(head, path).splitlines()
    except ClassifierError:
        return [f"{path}: cannot be compared as text"]
    if len(before) != len(after):
        return [f"{path}: lines added or removed"]
    for old, new in zip(before, after):
        if old == new:
            continue
        if _VERSION.sub("<v>", old) != _VERSION.sub("<v>", new):
            return [f"{path}: change is not a version substitution"]
        pairs = zip(_VERSION.findall(old), _VERSION.findall(new))
        if any(a != b and b != base_version for a, b in pairs):
            return [f"{path}: pin is not the previous release {base_version}"]
    return []


# --- Classification ------------------------------------------------------------


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(re.fullmatch(pattern, path) for pattern in patterns)


def _path_reasons(
    status: str, paths: list[str], base: str, head: str, base_version: str
) -> list[str]:
    reasons: list[str] = []
    for path in paths:
        guarded = path in DATA_TABLES or path in VERSION_FILES or _is_pin(path)
        if guarded and status != "M":
            reasons.append(f"{path}: status {status[0]} is not a modification")
        elif path in DATA_TABLES:
            reasons += _data_file_reasons(path, base, head)
        elif path in VERSION_FILES or path == CHANGELOG:
            continue  # checked once, together, in classify()
        elif _matches(path, DATA_DOC_PATTERNS):
            continue
        elif _is_pin(path):
            reasons += _pin_reasons(path, base, head, base_version)
        else:
            reasons.append(f"{path}: not an allowed path")
    return reasons


def _is_pin(path: str) -> bool:
    return _matches(path, PIN_PATTERNS) and not _matches(path, DATA_DOC_PATTERNS)


def classify(base: str, head: str) -> dict[str, Any]:
    """Return the verdict for the range ``base..head``."""
    match = _TAG.fullmatch(base)
    if match is None:
        raise ClassifierError(f"base {base!r} is not a vX.Y.Z tag")
    base_version = ".".join(match.groups())
    head_sha = _git("rev-parse", "--verify", f"{head}^{{commit}}").decode().strip()
    changes = _changes(base, head_sha)
    reasons: list[str] = []
    if not changes:
        reasons.append("no changes since the base tag")
    for status, paths in changes:
        reasons += _path_reasons(status, paths, base, head_sha, base_version)
    try:
        version_reasons, version = _version_reasons(base, head_sha, base_version)
    except ClassifierError:
        if not reasons:
            raise
        version_reasons, version = [], None
    reasons += version_reasons
    if version:
        reasons += _changelog_reasons(head_sha, version)
    return {
        "qualifies": not reasons,
        "base": base,
        "head": head_sha,
        "version": version,
        "reasons": reasons,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="previous release tag, vX.Y.Z")
    parser.add_argument("--head", required=True, help="release-prep commit")
    args = parser.parse_args(argv)
    try:
        verdict = classify(args.base, args.head)
    except ClassifierError as error:
        print(json.dumps({"error": str(error)}))
        return 2
    print(json.dumps(verdict, indent=2))
    return 0 if verdict["qualifies"] else 1


if __name__ == "__main__":
    sys.exit(main())
