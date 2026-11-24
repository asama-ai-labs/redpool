# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""The documentation link checker catches a missing file, heading and repository path."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_doc_links.py"
_spec = importlib.util.spec_from_file_location("check_doc_links", SCRIPT)
assert _spec and _spec.loader
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)


def _check(tmp_path, monkeypatch, files, target):
    monkeypatch.setattr(checker, "REPO_ROOT", tmp_path)
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return checker.check_file(tmp_path / target, {})


def test_valid_links_and_paths_pass(tmp_path, monkeypatch):
    files = {
        "README.md": "See [guide](docs/G.md#the-heading) and `docs/G.md`.\n",
        "docs/G.md": "# The heading\n",
    }
    assert _check(tmp_path, monkeypatch, files, "README.md") == []


def test_missing_link_target_is_reported(tmp_path, monkeypatch):
    files = {"README.md": "See [guide](docs/Missing.md).\n"}
    problems = _check(tmp_path, monkeypatch, files, "README.md")
    assert len(problems) == 1 and "link target does not exist" in problems[0]


def test_missing_heading_is_reported(tmp_path, monkeypatch):
    files = {"README.md": "See [x](docs/G.md#nope).\n", "docs/G.md": "# Real\n"}
    problems = _check(tmp_path, monkeypatch, files, "README.md")
    assert len(problems) == 1 and "no heading for anchor" in problems[0]


def test_missing_backticked_path_is_reported(tmp_path, monkeypatch):
    files = {"README.md": "Run `scripts/gone.py` first.\n"}
    problems = _check(tmp_path, monkeypatch, files, "README.md")
    assert len(problems) == 1 and "path does not exist: scripts/gone.py" in problems[0]


def test_code_blocks_urls_and_placeholders_are_ignored(tmp_path, monkeypatch):
    files = {
        "README.md": (
            "```\nrun scripts/gone.py and [x](nope.md)\n```\n"
            "[site](https://example.com/a.md) `fixtures/<Vendor>/<Model>/x.json`\n"
        )
    }
    assert _check(tmp_path, monkeypatch, files, "README.md") == []


def test_heading_slug_matches_github():
    assert checker.slug("Adding a New Vendor") == "adding-a-new-vendor"
    assert checker.slug("The `redpool` key (v1)") == "the-redpool-key-v1"
