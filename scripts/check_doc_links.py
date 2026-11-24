#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Fail when a Markdown file points at a repository path or heading that does not exist.

  uv run python scripts/check_doc_links.py

Checked, in every tracked ``*.md`` file outside third_party/ and fixtures/:

  link   a relative ``[text](target)`` link, and its ``#heading`` anchor when it has one
  path   a backticked repository path such as ``docs/FIXTURES.md`` or ``scripts/x.py``

External URLs are not fetched. A backticked path is skipped when it holds a placeholder
(``<``, ``{``, ``*``, ``$``) or is listed in ALLOWED_MISSING, which names files a command
creates. Exit status 0 means no findings, 1 means findings.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parent.parent
SKIP_PREFIXES = ("third_party/", "fixtures/")
# Files a documented command writes, so they do not exist in a clean checkout.
ALLOWED_MISSING = frozenset({"dist/", "build/"})

_LINK_RE = re.compile(r"(?<!\!)\[[^\]\n]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
_PATH_RE = re.compile(
    r"^(?:\./)?[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.(?:md|py|yaml|yml|json|html|toml|sh|service|target)$"
)
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def tracked_markdown() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [
        REPO_ROOT / p
        for p in out
        if not p.startswith(SKIP_PREFIXES) and (REPO_ROOT / p).is_file()
    ]


def slug(heading: str) -> str:
    """GitHub's anchor for a heading."""
    text = re.sub(r"`([^`]*)`", r"\1", heading.strip().lower())
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    found: set[str] = set()
    counts: dict[str, int] = {}
    in_fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        m = None if in_fence else re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if m:
            base = slug(m.group(1))
            n = counts.get(base, 0)
            counts[base] = n + 1
            found.add(base if n == 0 else f"{base}-{n}")
    return found


def prose_lines(path: Path):
    """(line number, text) for lines outside fenced code blocks."""
    in_fence = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield number, line


def check_file(path: Path, anchor_cache: dict[Path, set[str]]) -> list[str]:
    rel = path.relative_to(REPO_ROOT)
    problems: list[str] = []
    for number, line in prose_lines(path):
        for target in _LINK_RE.findall(line):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("//"):
                continue  # URL or mailto
            file_part, _, fragment = target.partition("#")
            dest = (
                path if not file_part else (path.parent / unquote(file_part)).resolve()
            )
            if file_part and not dest.exists():
                problems.append(f"{rel}:{number}: link target does not exist: {target}")
                continue
            if fragment and dest.suffix == ".md" and dest.is_file():
                if dest not in anchor_cache:
                    anchor_cache[dest] = anchors(dest)
                if unquote(fragment).lower() not in anchor_cache[dest]:
                    problems.append(f"{rel}:{number}: no heading for anchor: {target}")
        for span in _CODE_SPAN_RE.findall(line):
            token = span.strip()
            if not _PATH_RE.match(token) or "/" not in token:
                continue
            if token in ALLOWED_MISSING:
                continue
            candidates = [
                REPO_ROOT / token.removeprefix("./"),
                (path.parent / token).resolve(),
            ]
            if not any(c.exists() for c in candidates):
                problems.append(f"{rel}:{number}: path does not exist: {token}")
    return problems


def main() -> int:
    anchor_cache: dict[Path, set[str]] = {}
    problems: list[str] = []
    for path in tracked_markdown():
        problems.extend(check_file(path, anchor_cache))
    for line in problems:
        print(line)
    print(f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
