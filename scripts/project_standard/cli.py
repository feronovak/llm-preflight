"""Command line surface.

The fast half of the standard should run constantly — in CI, from a hook, from
a shell, on a whim — so the surface is built for selective use: one repo, one
concern, or the whole fleet.
"""

import argparse
import json
import sys
from pathlib import Path

from . import VERSION
from . import defaults, docmap, routes as routes_mod, runner
from .findings import ERROR, SKIPPED, WARN


def build_parser():
    p = argparse.ArgumentParser(
        prog="project-standard",
        description="Validate a project's documentation, release flow and git "
                    "hygiene against one standard.")
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("check", help="validate a repo (default)")
    c.add_argument("--repo", action="append", default=[],
                   help="repo path, or a name under the fleet root")
    c.add_argument("--only", action="append", default=[],
                   help="narrow to one concern; repeatable")
    c.add_argument("--fleet", action="store_true",
                   help="every git repo under the fleet root "
                        "($PROJECT_STANDARD_FLEET, else the parent of this repo)")
    c.add_argument("--json", action="store_true", help="machine-readable")
    c.add_argument("--profile", choices=(runner.DEV, runner.CI),
                   default=runner.DEV,
                   help="ci skips checks a runner cannot answer")

    g = sub.add_parser("generate", help="write docs/DOCMAP.md")
    g.add_argument("--repo", default=".")
    g.add_argument("--stdout", action="store_true")

    i = sub.add_parser("install-hooks",
                       help="install the authorship guards and point "
                            "core.hooksPath at them")
    i.add_argument("--repo", default=".")
    i.add_argument("--global", dest="globally", action="store_true",
                   help="configure for every repository, not just this one")

    r = sub.add_parser("routes", help="write docs/api/routes.json from the app")
    r.add_argument("--repo", default=".")
    r.add_argument("--app", help="import path, e.g. app:create_app")
    return p


def resolve_repos(args):
    fleet = defaults.fleet_root()
    if getattr(args, "fleet", False):
        if not fleet.is_dir():
            return []
        return sorted(p for p in fleet.iterdir() if (p / ".git").exists())
    if args.repo:
        out = []
        for name in args.repo:
            path = Path(name)
            if not path.exists() and (fleet / name).exists():
                path = fleet / name
            out.append(path)
        return out
    return [Path.cwd()]


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.command == "generate":
        return _generate(args)
    if args.command == "routes":
        return routes_mod.main(args)
    if args.command == "install-hooks":
        return _install_hooks(args)

    repos = resolve_repos(args)
    if not repos:
        print("no repositories to check", file=sys.stderr)
        return 2

    if getattr(args, "fleet", False):
        # Say what is about to be swept. The fallback root is the parent of the
        # enclosing repository, which can quietly include repositories the user
        # did not mean to scan.
        root = defaults.fleet_root()
        print(f"fleet root: {root}  ({len(repos)} repositories)", file=sys.stderr)
        print("  " + ", ".join(r.name for r in repos), file=sys.stderr)
        print("  set PROJECT_STANDARD_FLEET to scan somewhere else\n",
              file=sys.stderr)

    payload, worst = [], 0
    for repo in repos:
        report = runner.run(repo, profile=args.profile, only=args.only)
        worst = max(worst, report.exit_code)
        if args.json:
            payload.append({"repo": str(repo),
                            "findings": [f.as_dict() for f in report.ranked()]})
        else:
            _print_report(repo, report, multi=len(repos) > 1)

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return worst


def _print_report(repo, report, multi):
    label = repo.name if multi else str(repo)
    head = getattr(report, "summary", "")
    print(f"\n=== {label}" + (f"  ({head})" if head else ""))
    if not report.findings:
        print("  no findings")
        return

    icons = {ERROR: "ERROR ", WARN: "warn  ", SKIPPED: "skip  "}
    for f in report.ranked():
        print(f"  {icons[f.severity]}{f.render()}")

    print(f"  -- {len(report.errors)} error(s), {len(report.warns)} warn(s), "
          f"{len(report.skips)} skipped")


def _install_hooks(args):
    import shutil
    import subprocess

    source = Path(__file__).resolve().parents[2] / "hooks"
    if not source.is_dir():
        print(f"hook sources not found at {source}", file=sys.stderr)
        return 2

    target = Path.home() / ".config" / "git" / "project-standard-hooks" \
        if args.globally else Path(args.repo).resolve() / ".githooks"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("pre-commit", "commit-msg"):
        dest = target / name
        shutil.copy2(source / name, dest)
        dest.chmod(0o755)

    scope = ["--global"] if args.globally else ["-C", str(Path(args.repo))]
    cmd = ["git", *scope, "config", "core.hooksPath", str(target)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stderr.strip(), file=sys.stderr)
        return 2

    print(f"installed pre-commit and commit-msg in {target}")
    print(f"core.hooksPath set {'globally' if args.globally else 'for this repo'}")
    print("\nNote: setting core.hooksPath replaces any other hooks directory. "
          "If you already had one, merge its hooks into the new location.")
    return 0


def _generate(args):
    repo = Path(args.repo)
    ctx = runner.build_ctx(repo)
    text = docmap.render(ctx)
    if args.stdout:
        print(text)
        return 0
    target = repo / docmap.HEADER
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
