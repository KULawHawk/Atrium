"""Unit tests for atrium_check.check: each finding code has a positive and a negative case."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atrium_check.check import (
    Finding,
    RegistryError,
    apply_repin,
    check,
    load_registry,
    plan_repin,
    resolve_checkouts,
    resolve_pointer,
    validate_registry,
)

from conftest import write_json


def codes(report):
    return sorted(f.code for f in report.findings)


def run(reg, root, **kw):
    return check(reg, resolve_checkouts(reg, root), **kw)


# ----------------------------------------------------------------- baseline


def test_consistent_suite_passes(suite):
    reg, _, root = suite
    r = run(reg, root)
    assert r.findings == []
    assert r.passed
    assert (r.contracts_checked, r.files_hashed, r.enums_compared, r.mirror_files_compared) == (3, 3, 2, 2)
    assert r.members_examined == ["alpha", "beta"]
    assert r.summary().startswith("ATRIUM-CHECK: PASS errors=0")
    assert "NOT_EXAMINED" not in r.summary()


def test_checkout_lookup_is_case_insensitive_and_overrides_win(suite, tmp_path):
    reg, _, root = suite
    found = resolve_checkouts(reg, root)
    assert found == {"alpha": root / "Alpha", "beta": root / "beta"}
    other = tmp_path / "elsewhere"
    other.mkdir()
    assert resolve_checkouts(reg, root, {"alpha": other})["alpha"] == other
    # an override that does not exist drops the member rather than falling back
    assert "alpha" not in resolve_checkouts(reg, root, {"alpha": tmp_path / "nope"})
    assert resolve_checkouts(reg, None) == {}
    assert resolve_checkouts(reg, tmp_path / "missing-root") == {}


# ----------------------------------------------------------------- population


def test_missing_member_is_an_error_not_a_skip(suite):
    reg, _, root = suite
    r = check(reg, {"alpha": root / "Alpha"})
    assert codes(r) == ["MEMBER_MISSING"]
    assert not r.passed
    assert r.members_skipped == ["beta"]
    assert "NOT_EXAMINED=beta" in r.summary()


def test_only_narrows_explicitly_and_reports_it(suite):
    reg, _, root = suite
    r = run(reg, root, only=["beta"])
    assert r.passed
    assert r.members_examined == ["beta"]
    assert r.members_skipped == ["alpha"]
    assert r.contracts_checked == 1
    assert "NOT_EXAMINED=alpha" in r.summary()


def test_unknown_member_in_only(suite):
    reg, _, root = suite
    r = run(reg, root, only=["gamma", "alpha"])
    assert "UNKNOWN_MEMBER" in codes(r)


def test_zero_contracts_examined_never_passes(suite):
    reg, _, root = suite
    r = check(reg, {}, only=[])
    assert r.findings == []
    assert not r.passed
    assert "reason=no contract was examined" in r.summary()


# ----------------------------------------------------------------- contract files


def test_pin_drift(suite):
    reg, _, root = suite
    p = root / "Alpha/contracts/rec.v1.schema.json"
    p.write_text(p.read_text() + " ", encoding="utf-8")
    r = run(reg, root)
    assert "PIN_DRIFT" in codes(r)
    # the mirror still carries the old bytes, which equal the registry pin: no stale warning
    assert "MIRROR_STALE" not in codes(r)


def test_file_missing(suite):
    reg, _, root = suite
    (root / "beta/contracts/req.v2.schema.json").unlink()
    r = run(reg, root)
    assert "FILE_MISSING" in codes(r)
    assert r.enums_compared == 1  # Req/2's enum cannot be compared without the file


def test_json_invalid(suite):
    reg, _, root = suite
    p = root / "Alpha/contracts/fam.v1.json"
    p.write_text("{not json", encoding="utf-8")
    reg["contracts"][1]["sha256"] = __import__("hashlib").sha256(p.read_bytes()).hexdigest()
    assert codes(run(reg, root, only=["alpha"])) == ["JSON_INVALID"]


def test_const_mismatch_and_missing(suite):
    reg, _, root = suite
    reg["contracts"][1]["const_pointer"] = "/nope"
    reg["contracts"][2]["name"] = "Req/3"
    reg["contracts"][2]["path"] = "contracts/req.v2.schema.json"
    reg["tool_enums"][1]["contract"] = "Req/3"
    c = codes(run(reg, root))
    assert "CONST_MISSING" in c
    assert "CONST_MISMATCH" in c
    assert "VERSION_FILENAME" in c


def test_null_const_pointer_skips_the_const_check(suite):
    reg, _, root = suite
    reg["contracts"][0]["const_pointer"] = None
    assert run(reg, root).passed


def _rewrite(reg, idx, root, home_dir, mutate):
    c = reg["contracts"][idx]
    p = root / home_dir / c["path"]
    doc = json.loads(p.read_text())
    mutate(doc)
    c["sha256"] = write_json(p, doc)


def test_dialect_and_id(suite):
    reg, _, root = suite

    def bad(doc):
        doc["$schema"] = "http://json-schema.org/draft-07/schema#"
        doc["$id"] = "https://example.com/rec.json"

    _rewrite(reg, 0, root, "Alpha", bad)
    reg["mirrors"] = []
    c = codes(run(reg, root))
    assert c == ["DIALECT", "ID_MISMATCH"]


def test_schema_must_be_an_object(suite):
    reg, _, root = suite
    reg["contracts"][2]["sha256"] = write_json(root / "beta/contracts/req.v2.schema.json", ["Req/2"])
    reg["contracts"][2]["const_pointer"] = "/0"
    reg["tool_enums"] = reg["tool_enums"][:1]
    assert codes(run(reg, root)) == ["SCHEMA_NOT_OBJECT"]


def test_unregistered_file_and_missing_dir(suite):
    reg, _, root = suite
    write_json(root / "Alpha/contracts/new.v1.schema.json", {})
    reg["members"]["beta"]["contract_dirs"].append("gone")
    c = codes(run(reg, root))
    assert c == ["CONTRACT_DIR_MISSING", "UNREGISTERED_FILE"]


# ----------------------------------------------------------------- tool enums


def test_enum_mismatch_unknown_and_duplicate(suite):
    reg, _, root = suite
    reg["mirrors"] = []
    _rewrite(reg, 0, root, "Alpha", lambda d: d["properties"]["tool"].update(enum=["alpha", "alpha", "zeta"]))
    c = codes(run(reg, root))
    assert c == ["ENUM_DUPLICATE", "ENUM_MISMATCH", "ENUM_UNKNOWN_TOOL"]
    msg = next(f.message for f in run(reg, root).findings if f.code == "ENUM_MISMATCH")
    assert "missing ['beta', 'hub']" in msg and "unexpected ['zeta']" in msg


def test_enum_pointer_missing_or_not_a_list(suite):
    reg, _, root = suite
    reg["tool_enums"][0]["pointer"] = "/properties/nope/enum"
    reg["tool_enums"][1]["pointer"] = "/properties/contract/const"
    assert codes(run(reg, root)) == ["ENUM_POINTER_MISSING", "ENUM_POINTER_MISSING"]


def test_declared_subset_must_match_exactly(suite):
    reg, _, root = suite
    reg["tool_enums"][1]["expect"] = ["alpha"]
    assert codes(run(reg, root)) == ["ENUM_MISMATCH"]


# ----------------------------------------------------------------- mirrors


def test_mirror_stale_is_a_warning_and_strict_fails(suite):
    reg, _, root = suite
    p = root / "beta/vendor_alpha/contracts/rec.v1.schema.json"
    p.write_text(p.read_text() + " ", encoding="utf-8")
    r = run(reg, root)
    assert codes(r) == ["MIRROR_STALE"]
    assert r.passed
    assert not run(reg, root, strict=True).passed


def test_mirror_pin_note_then_warn_when_stale(suite):
    reg, _, root = suite
    write_json(root / "beta/vendor_alpha/VENDORED_FROM.json", {"upstream_commit": "0123456"})
    r = run(reg, root)
    assert [(f.severity, f.code) for f in r.findings] == [("note", "MIRROR_PIN")]
    assert r.passed and run(reg, root, strict=True).passed
    p = root / "beta/vendor_alpha/contracts/fam.v1.json"
    p.write_text("{}", encoding="utf-8")
    sev = {f.code: f.severity for f in run(reg, root).findings}
    assert sev == {"MIRROR_STALE": "warn", "MIRROR_PIN": "warn"}


def test_mirror_same_commit_different_lengths_is_quiet(suite):
    reg, _, root = suite
    write_json(root / "beta/vendor_alpha/VENDORED_FROM.json", {"upstream_commit": "AAAAAAA" + "0" * 33})
    assert run(reg, root).findings == []


def test_mirror_subset_missing_dir_and_manifest_problems(suite):
    reg, _, root = suite
    (root / "beta/vendor_alpha/contracts/fam.v1.json").unlink()
    r = run(reg, root)
    assert [(f.severity, f.code) for f in r.findings] == [("note", "MIRROR_SUBSET")]
    (root / "beta/vendor_alpha/VENDORED_FROM.json").write_text("{bad", encoding="utf-8")
    assert "MIRROR_MANIFEST" in codes(run(reg, root))
    write_json(root / "beta/vendor_alpha/VENDORED_FROM.json", ["not", "an", "object"])
    assert "MIRROR_MANIFEST" not in codes(run(reg, root))
    (root / "beta/vendor_alpha/VENDORED_FROM.json").unlink()
    assert "MIRROR_MANIFEST" in codes(run(reg, root))
    reg["mirrors"][0]["root"] = "nowhere"
    assert codes(run(reg, root)) == ["MIRROR_MISSING"]


def test_mirror_skipped_when_its_holder_is_not_examined(suite):
    reg, _, root = suite
    r = run(reg, root, only=["alpha"])
    assert r.mirror_files_compared == 0 and r.passed


# ----------------------------------------------------------------- pointer + registry


@pytest.mark.parametrize(
    "pointer,expected",
    [("", {"a/b": [1, {"~x": 2}]}), ("/a~1b/0", 1), ("/a~1b/1/~0x", 2)],
)
def test_resolve_pointer(pointer, expected):
    assert resolve_pointer({"a/b": [1, {"~x": 2}]}, pointer) == expected


@pytest.mark.parametrize("pointer", ["a", "/zz", "/a~1b/9", "/a~1b/x", "/a~1b/0/deeper"])
def test_resolve_pointer_failures(pointer):
    with pytest.raises(KeyError):
        resolve_pointer({"a/b": [1]}, pointer)


def test_validate_registry_accepts_fixture(suite):
    reg, path, _ = suite
    assert validate_registry(reg) == []
    assert load_registry(path) == reg


def test_validate_registry_subset_must_stay_inside_roster(suite):
    reg, _, _ = suite
    reg["tool_enums"][1]["expect"] = ["alpha", "zeta"]
    assert validate_registry(reg) == ["tool_enums[1].expect: not in tool_roster: ['zeta']"]
    reg["tool_roster"] = []  # a broken roster is reported once, not per subset
    assert validate_registry(reg) == ["tool_roster: must be a non-empty list of strings"]


def test_validate_registry_not_object():
    assert validate_registry([]) == ["registry: not a JSON object"]


def test_validate_registry_reports_every_problem(suite):
    reg, _, _ = suite
    bad = copy.deepcopy(reg)
    bad["registry"] = "Other/1"
    bad["owner"] = "Someone"
    bad["tool_roster"] = ["a", "a"]
    bad["members"]["alpha"] = {"repo": "", "contract_dirs": "x"}
    bad["members"]["beta"] = "nope"
    bad["contracts"] = [
        "nope",
        {"name": "Rec/01", "home": "zeta", "path": "", "kind": "other", "const_pointer": 3, "sha256": "XYZ"},
        {"name": "Ok/1", "home": "alpha", "path": "p", "kind": "data", "const_pointer": None, "sha256": "a" * 64},
        {"name": "Ok/1", "home": "alpha", "path": "p", "kind": "data", "const_pointer": None, "sha256": "a" * 64},
    ]
    bad["tool_enums"] = ["x", {"contract": "Missing/1", "pointer": 3, "expect": ["a"]}, {"contract": "Ok/1", "pointer": "/", "expect": 5}]
    bad["mirrors"] = ["x", {"home": "zeta", "in": "zeta", "root": "", "manifest": None}]
    problems = validate_registry(bad)
    for needle in [
        "'registry' must be",
        "'owner' must be",
        "tool_roster: duplicate",
        "members.alpha.repo",
        "members.alpha.dir",
        "members.alpha.contract_dirs",
        "members.beta: must be an object",
        "contracts[0]: must be an object",
        "contracts[1].name",
        "contracts[1].home",
        "contracts[1].path",
        "contracts[1].kind",
        "contracts[1].const_pointer",
        "contracts[1].sha256",
        "contracts[3].name: duplicate",
        "tool_enums[0]: must be an object",
        "tool_enums[1].contract",
        "tool_enums[1].pointer",
        "tool_enums[1].why",
        "tool_enums[2].expect",
        "mirrors[0]: must be an object",
        "mirrors[1].home",
        "mirrors[1].in",
        "mirrors[1].root",
        "mirrors[1].manifest",
    ]:
        assert any(needle in p for p in problems), needle


def test_validate_registry_wrong_container_types():
    problems = validate_registry({"tool_roster": [], "members": [], "contracts": {}, "tool_enums": {}, "mirrors": {}})
    for needle in ["tool_roster: must be", "members: must be", "contracts: must be", "tool_enums: must be", "mirrors: must be"]:
        assert any(needle in p for p in problems), needle


def test_load_registry_errors(tmp_path):
    with pytest.raises(RegistryError):
        load_registry(tmp_path / "missing.json")
    p = tmp_path / "bad.json"
    p.write_text("{", encoding="utf-8")
    with pytest.raises(RegistryError):
        load_registry(p)
    p.write_text("{}", encoding="utf-8")
    with pytest.raises(RegistryError, match="'registry' must be"):
        load_registry(p)


# ----------------------------------------------------------------- repin + report


def test_plan_and_apply_repin(suite):
    reg, path, root = suite
    p = root / "Alpha/contracts/rec.v1.schema.json"
    p.write_text(p.read_text() + " ", encoding="utf-8")
    (root / "beta/contracts/req.v2.schema.json").unlink()
    checkouts = resolve_checkouts(reg, root)
    del checkouts["beta"]
    changes = plan_repin(reg, resolve_checkouts(reg, root))
    assert [c[0] for c in changes] == ["Rec/1"]
    assert plan_repin(reg, checkouts) == changes
    apply_repin(path, reg, changes, {"alpha": "ccccccc"})
    again = load_registry(path)
    assert again["contracts"][0]["sha256"] == changes[0][2]
    assert again["members"]["alpha"]["pinned_commit"] == "ccccccc"
    assert not path.with_suffix(".json.tmp").exists()
    (root / "beta/contracts/req.v2.schema.json").write_text("{}", encoding="utf-8")
    assert "PIN_DRIFT" not in [f.code for f in run(again, root, only=["alpha"]).findings]


def test_report_json_and_finding_line(suite):
    reg, _, root = suite
    (root / "beta/contracts/req.v2.schema.json").unlink()
    r = run(reg, root)
    data = r.to_json()
    assert data["passed"] is False
    assert data["findings"][0]["code"] == "FILE_MISSING"
    line = Finding("error", "FILE_MISSING", "Req/2", "gone").line()
    assert line.startswith("ERROR FILE_MISSING") and line.endswith("Req/2: gone")
