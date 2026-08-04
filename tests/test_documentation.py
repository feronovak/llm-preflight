import re
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_docs_home_and_mcp_guide_are_first_class_entry_points():
    readme = (ROOT / "README.md").read_text()

    assert "## MCP for coding agents" in readme
    assert "docs/index.md" in readme
    assert (ROOT / "docs/index.md").is_file()
    assert (ROOT / "docs/automation/mcp.md").is_file()


def test_local_markdown_links_resolve_after_docs_reorganization():
    for page in (ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))):
        for target in re.findall(r"\]\(([^)]+)\)", page.read_text()):
            target = target.split("#", 1)[0]
            if not target or "://" in target:
                continue
            assert (page.parent / target).is_file(), f"{page}: {target}"
