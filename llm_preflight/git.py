"""Git invocations that never run a command the inspected repository configures."""

from __future__ import annotations

import os
import shutil

# run_git uses an absolute executable and argument arrays.
import subprocess  # nosec B404
from pathlib import Path

# A hook or wrapper that exports these would point Git at another repository,
# work tree or index than the path being inspected.
_REDIRECTING_VARIABLES = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
)
# Repository configuration travels with a copied checkout, so it is untrusted.
# Command-line settings override it, and Git hands them to the processes it
# starts in submodules.
_HARDENING = (
    # Skip optional index writes. Git diff still rewrites the index when a
    # file's stat data changed but its content did not; keeping that refresh
    # lists only files whose content changed.
    "--no-optional-locks",
    # The file-system monitor hook is an arbitrary command.
    "-c",
    "core.fsmonitor=false",
    # An index rewrite runs the post-index-change hook. The null device cannot
    # hold a hook on any platform, so no repository hook runs.
    "-c",
    f"core.hooksPath={os.devnull}",
    # No transport at all, so a partial clone cannot fetch a missing object
    # through a configured SSH command or remote helper.
    "-c",
    "protocol.allow=never",
)


def run_git(
    repository: Path, *arguments: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run Git in repository with every command its configuration names disabled.

    Raises FileNotFoundError when Git is not installed, CalledProcessError when
    Git fails and check is true, and ValueError when a configured filter driver
    cannot be disabled.
    """
    executable = shutil.which("git")
    if executable is None:
        raise FileNotFoundError("git is not installed")
    command = [
        str(Path(executable).resolve()),
        *_HARDENING,
        "-C",
        str(repository),
    ]
    environment = _environment()
    overrides = _filter_overrides(command, environment)
    # No shell is used; callers pass fixed arguments or a validated reference.
    return subprocess.run(  # nosec B603
        [*command, *overrides, *arguments],
        check=check,
        text=True,
        capture_output=True,
        env=environment,
    )


def _environment() -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in _REDIRECTING_VARIABLES
    }
    # Global and system configuration stay in effect. They belong to the person
    # running the command, not to the inspected repository, and hold the
    # safe.directory exceptions and core.excludesFile that Git must respect.
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GIT_NO_LAZY_FETCH"] = "1"
    return environment


def _filter_overrides(command: list[str], environment: dict[str, str]) -> list[str]:
    """Settings that disable every configured filter driver.

    Git runs a clean filter when it re-reads a work-tree file whose stat data
    changed, and no single setting turns filters off, so each configured
    driver is disabled by name.
    """
    # No shell is used and every argument is fixed.
    listed = subprocess.run(  # nosec B603
        [*command, "config", "-z", "--name-only", "--get-regexp", r"^filter\."],
        check=False,
        text=True,
        capture_output=True,
        env=environment,
    )
    # Exit status 1 means that no filter driver is configured.
    if listed.returncode not in (0, 1):
        raise subprocess.CalledProcessError(
            listed.returncode, listed.args, listed.stdout, listed.stderr
        )
    drivers = []
    for name in listed.stdout.split("\0"):
        driver, dot, _ = name.removeprefix("filter.").rpartition(".")
        # An empty driver name is valid: [filter ""] with "filter=" attributes.
        if dot and driver not in drivers:
            drivers.append(driver)
    overrides = []
    for driver in drivers:
        if "=" in driver:
            # "-c name=value" splits at the first "=", so such a driver cannot
            # be disabled; refuse to run Git rather than let it run.
            raise ValueError(
                "a configured Git filter driver has a name that cannot be disabled"
            )
        for key in ("clean", "smudge", "process"):
            overrides.extend(["-c", f"filter.{driver}.{key}="])
        overrides.extend(["-c", f"filter.{driver}.required=false"])
    return overrides
