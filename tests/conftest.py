"""Fixtures: a tiny fake APEX suite (two members, one mirror) built in tmp_path."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

ROSTER = ["alpha", "beta", "hub"]


def _schema(home: str, filename: str, contract: str, tool_enum: list[str] | None = None) -> dict:
    props: dict = {"contract": {"const": contract}}
    if tool_enum is not None:
        props["tool"] = {"enum": tool_enum}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://apex-suite/{home}/contracts/{filename}",
        "type": "object",
        "additionalProperties": False,
        "properties": props,
    }


def write_json(path: Path, doc) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture
def suite(tmp_path: Path):
    """Return (registry_dict, registry_path, repos_root) for a consistent suite."""
    root = tmp_path / "repos"
    alpha = root / "Alpha"
    beta = root / "beta"  # lower-case on disk; registry says "Beta"
    s1 = write_json(alpha / "contracts/rec.v1.schema.json", _schema("alpha", "rec.v1.schema.json", "Rec/1", ROSTER))
    s2 = write_json(alpha / "contracts/fam.v1.json", {"contract": "Fam/1", "families": {}})
    s3 = write_json(beta / "contracts/req.v2.schema.json", _schema("beta", "req.v2.schema.json", "Req/2", ["alpha", "beta"]))
    # beta vendors alpha's contracts byte for byte
    mirror = beta / "vendor_alpha"
    (mirror / "contracts").mkdir(parents=True)
    for rel in ("contracts/rec.v1.schema.json", "contracts/fam.v1.json"):
        (mirror / rel).write_bytes((alpha / rel).read_bytes())
    write_json(mirror / "VENDORED_FROM.json", {"upstream_commit": "aaaaaaa"})

    reg = {
        "registry": "AtriumContractRegistry/1",
        "owner": "Atrium",
        "tool_roster": ROSTER,
        "members": {
            "alpha": {"repo": "X/Alpha", "dir": "Alpha", "pinned_commit": "aaaaaaa", "contract_dirs": ["contracts"]},
            "beta": {"repo": "X/Beta", "dir": "Beta", "pinned_commit": "bbbbbbb", "contract_dirs": ["contracts"]},
        },
        "contracts": [
            {"name": "Rec/1", "home": "alpha", "path": "contracts/rec.v1.schema.json", "kind": "json_schema",
             "const_pointer": "/properties/contract/const", "sha256": s1},
            {"name": "Fam/1", "home": "alpha", "path": "contracts/fam.v1.json", "kind": "data",
             "const_pointer": "/contract", "sha256": s2},
            {"name": "Req/2", "home": "beta", "path": "contracts/req.v2.schema.json", "kind": "json_schema",
             "const_pointer": "/properties/contract/const", "sha256": s3},
        ],
        "tool_enums": [
            {"contract": "Rec/1", "pointer": "/properties/tool/enum", "expect": "roster"},
            {"contract": "Req/2", "pointer": "/properties/tool/enum", "expect": ["alpha", "beta"], "why": "hub never asks"},
        ],
        "mirrors": [{"home": "alpha", "in": "beta", "root": "vendor_alpha", "manifest": "VENDORED_FROM.json"}],
    }
    reg_path = tmp_path / "registry.json"
    write_json(reg_path, reg)
    return copy.deepcopy(reg), reg_path, root
