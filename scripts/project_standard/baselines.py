"""Check 42 — a declared baseline may never loosen.

The baselines are the whole reason a repo can adopt this standard on day one
and pay its documentation debt down over weeks instead of facing a permanently
red gate. That bargain only holds while they move in one direction.

Comparing a baseline against today's contract answers nothing, because the
commit that removes the documentation can edit the number that would have
caught it. The comparison has to be against what the repository has already
recorded — the extreme reached across the contract's own history, not the
value sitting in the file right now.

Direction is per baseline, and they do not all point the same way:

  - `api-coverage` counts endpoints documented. It is a floor, so its ratchet
    is the highest figure ever recorded.
  - `scaffold` counts required documents still holding TODO tokens. It is an
    allowance, so its ratchet is the lowest figure ever recorded.
  - `adopted` marks where attribution errors begin. Walking it forward
    grandfathers in every violation it steps over, so it may only stay put or
    move back.
"""

import re

from . import contract as contract_mod
from . import findings as F

CHECK = "42"

# `adopted` is compared only between two resolved commit ids. A placeholder
# like `HEAD` or `<commit>` is a real thing people write while adopting, and
# `HEAD` resolves as an ancestor of anything — replacing it with the actual
# commit is a correction, not a baseline being walked forward.
SHA = re.compile(r"^[0-9a-f]{7,40}$")


def check(ctx):
    out = []
    path = ctx.contract.path
    if not path:
        return out

    recorded = _recorded(ctx, path)
    if not recorded:
        # Nothing committed to compare against — the contract is new in the
        # working tree. There is no ratchet to violate yet.
        return out

    out += _count(ctx, recorded, "api-coverage", floor=True)
    out += _count(ctx, recorded, "scaffold", floor=False)
    out += _adopted(ctx, recorded, path)
    return out


def _recorded(ctx, path):
    """Every committed version of the contract, oldest first.

    Bounded by `commits_touching`: a contract with hundreds of edits is not
    worth hundreds of `git show` calls, and the extremes of the recent history
    are what a regression would have to clear anyway.
    """
    out = []
    for sha in reversed(ctx.git.commits_touching(path)):
        text = ctx.git.file_at(sha, path)
        if text is None:
            continue
        out.append((sha, contract_mod.parse_contract(text, path=path)))
    return out


def _as_count(raw):
    """`35/40` and `35` both mean 35. Anything else means nothing."""
    if raw is None:
        return None
    try:
        return int(str(raw).split("/")[0].strip())
    except (TypeError, ValueError):
        return None


def _count(ctx, recorded, key, floor):
    declared = _as_count(ctx.contract.raw.get(key))
    if declared is None:
        return []

    seen = [(sha, _as_count(c.raw.get(key))) for sha, c in recorded]
    seen = [(sha, v) for sha, v in seen if v is not None]
    if not seen:
        return []

    if floor:
        sha, best = max(seen, key=lambda p: p[1])
        if declared >= best:
            return []
        moved, verb = "lowered", "documented"
    else:
        sha, best = min(seen, key=lambda p: p[1])
        if declared <= best:
            return []
        moved, verb = "raised", "still scaffolded"

    return [F.error(
        CHECK,
        f"`{key}` was {moved} from {best} to {declared}; the repository "
        f"already recorded {best} {verb} in {sha[:8]}. A baseline records "
        f"progress that was actually made — editing it to absorb a regression "
        f"is how the gate stops meaning anything. Fix the regression, or "
        f"explain the reset in the commit that makes it.",
        path=ctx.contract.path)]


def _adopted(ctx, recorded, path):
    declared = ctx.contract.adopted
    if not declared:
        return []

    if not (SHA.match(str(declared)) and ctx.git.commit_exists(declared)):
        return []
    # The earliest baseline that actually resolves — skipping the placeholders
    # a repo carries while adopting, which would otherwise poison the
    # comparison for the life of the repository.
    first = next((c.adopted for _, c in recorded
                  if c.adopted and SHA.match(str(c.adopted))
                  and ctx.git.commit_exists(c.adopted)), None)
    if not first or first == declared:
        return []
    # Only a move *forward* grandfathers anything. Moving the baseline back
    # widens what the attribution rule audits, which is strictly stricter.
    if not ctx.git.is_ancestor(first, declared):
        return []

    return [F.error(
        CHECK,
        f"`adopted` moved forward from `{first[:8]}` to `{declared[:8]}`, "
        f"which grandfathers in every attribution breach between them. The "
        f"adoption baseline is a historical fact about when this repository "
        f"took the standard on; it does not move to make a check pass.",
        path=path)]
