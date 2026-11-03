"""The committed registry, checked against real member checkouts.

Set ATRIUM_REPOS_ROOT to the folder that holds the member repos (Conclave,
Locutus, Obsidian, Sequoia) to run it; it is skipped otherwise, and says so.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from atrium_check.__main__ import DEFAULT_REGISTRY
from atrium_check.check import check, load_registry, resolve_checkouts

ROOT = os.environ.get("ATRIUM_REPOS_ROOT")


def test_committed_registry_is_well_formed():
    reg = load_registry(DEFAULT_REGISTRY)
    names = [c["name"] for c in reg["contracts"]]
    assert len(names) == len(set(names))
    assert set(reg["members"]) >= {"conclave", "locutus", "obsidian", "sequoia"}


@pytest.mark.skipif(not ROOT, reason="ATRIUM_REPOS_ROOT not set: live member check NOT run")
def test_committed_registry_matches_member_checkouts():
    reg = load_registry(DEFAULT_REGISTRY)
    report = check(reg, resolve_checkouts(reg, Path(ROOT)))
    assert report.passed, "\n".join(f.line() for f in report.findings) + "\n" + report.summary()
    assert report.members_skipped == []


def test_markdown_table_names_the_same_contracts():
    import re

    reg = load_registry(DEFAULT_REGISTRY)
    md = (DEFAULT_REGISTRY.parents[1] / "CONTRACTS_REGISTRY.md").read_text(encoding="utf-8")
    table = set(re.findall(r"^\| `([A-Za-z]+/\d+)` \|", md, flags=re.M))
    assert table == {c["name"] for c in reg["contracts"]}
