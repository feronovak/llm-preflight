"""Compatibility metadata for installers with an older setuptools backend."""

import re
from pathlib import Path

from setuptools import find_packages, setup

_VERSION_FILE = Path(__file__).parent / "llm_preflight" / "__init__.py"
_VERSION_MATCH = re.search(
    r'^__version__ = "([^"]+)"$', _VERSION_FILE.read_text(), re.MULTILINE
)
if _VERSION_MATCH is None:
    raise RuntimeError("could not read the package version")
PACKAGE_VERSION = _VERSION_MATCH.group(1)

setup(
    name="llm-preflight",
    version=PACKAGE_VERSION,
    description="Local, cross-provider preflight checks for an LLM model switch",
    packages=find_packages(include=["llm_preflight", "llm_preflight.*"]),
    python_requires=">=3.10",
    entry_points={
        "console_scripts": [
            "llm-preflight=llm_preflight.__main__:main",
            "llm-preflight-mcp=llm_preflight.mcp:main",
        ]
    },
)
