"""Fail when a local Markdown link points to a missing file."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\]\(([^)]+)\)")
SKIP_PARTS = {".git", ".venv", "node_modules", ".pytest_cache", ".mypy_cache"}


def _is_ignored(path: Path) -> bool:
    return any(part in SKIP_PARTS or part.startswith(".venv-") for part in path.parts)


def main() -> int:
    missing: list[str] = []
    files = sorted(path for path in ROOT.rglob("*.md") if not _is_ignored(path))
    for document in files:
        text = document.read_text(encoding="utf-8")
        for match in LINK.finditer(text):
            raw = match.group(1).strip()
            target = raw.split(maxsplit=1)[0].strip("<>")
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            local = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if local and not (document.parent / local).resolve().exists():
                missing.append(f"{document.relative_to(ROOT)} -> {local}")

    if missing:
        print("link-check: missing local targets", file=sys.stderr)
        for item in missing:
            print(f"  {item}", file=sys.stderr)
        return 1
    print(f"link-check: {len(files)} Markdown files checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
