"""A JSON object naming a key twice is refused, never read as its last value (hunt 2026-11-24). Synthetic only.

On main 3febbe8 a registry carrying ``"sha256": "000…0"`` and then the real pin for one contract passed
``atrium_check`` (``json.loads`` keeps the last), while a reviewer reading the diff could take the first for the pin.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from atrium_check import __main__ as cli
from atrium_check.check import RegistryError, check, load_registry, resolve_checkouts

from conftest import write_json


def _run(reg, root, **kw):
    kw.setdefault("heads", {m: v["pinned_commit"] for m, v in reg["members"].items()})
    return check(reg, resolve_checkouts(reg, root), **kw)


def _with_shadow_pin(reg_path: Path) -> Path:
    text = reg_path.read_text(encoding="utf-8")
    reg = json.loads(text)
    real = reg["contracts"][0]["sha256"]
    bad = text.replace(f'"sha256": "{real}"', f'"sha256": "{"0" * 64}", "sha256": "{real}"', 1)
    assert bad != text
    out = reg_path.with_name("shadow.json")
    out.write_text(bad, encoding="utf-8")
    return out


def test_a_registry_naming_a_key_twice_is_refused(suite):
    _, reg_path, _ = suite
    with pytest.raises(RegistryError, match="appears twice"):
        load_registry(_with_shadow_pin(reg_path))


def test_the_cli_exits_2_on_such_a_registry(suite, capsys):
    _, reg_path, root = suite
    rc = cli.main(["check", "--registry", str(_with_shadow_pin(reg_path)), "--repos-root", str(root)])
    assert rc == 2


def test_the_real_registry_still_loads(suite):
    reg, reg_path, _ = suite
    assert load_registry(reg_path) == reg


def test_a_contract_document_naming_a_key_twice_is_json_invalid(suite):
    reg, _, root = suite
    p = root / "Alpha/contracts/fam.v1.json"
    p.write_text('{"contract": "Other/1", "contract": "Fam/1", "families": {}}', encoding="utf-8")
    reg["contracts"][1]["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
    report = _run(reg, root, only=["alpha"])
    assert [f.code for f in report.findings] == ["JSON_INVALID"]
    assert "appears twice" in report.findings[0].message


def test_a_mirror_manifest_naming_a_key_twice_is_warned(suite):
    reg, _, root = suite
    write_json(root / "beta/vendor_alpha/VENDORED_FROM.json", {})
    (root / "beta/vendor_alpha/VENDORED_FROM.json").write_text(
        '{"upstream_commit": "fffffff", "upstream_commit": "aaaaaaa"}', encoding="utf-8")
    report = _run(reg, root)
    assert any(f.code == "MIRROR_MANIFEST" and "appears twice" in f.message for f in report.findings)
