"""Test-gap lane: fail-closed behaviour of atrium_check that had line coverage but no assertion.

Every test builds a synthetic suite in tmp_path (the ``suite`` fixture in conftest.py);
nothing here reads the committed registry or a real member checkout.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from atrium_check import __main__ as cli
from atrium_check.check import (
    RegistryError,
    Report,
    apply_repin,
    check,
    load_registry,
    plan_repin,
    resolve_checkouts,
    same_commit,
    sha256_file,
    validate_registry,
)


def _run(reg, root, **kw):
    return check(reg, resolve_checkouts(reg, root), **kw)


def _codes(report):
    return [f.code for f in report.findings]


def _case_sensitive_fs(tmp_path: Path) -> bool:
    probe = tmp_path / "CaseProbe"
    probe.mkdir()
    sensitive = not (tmp_path / "caseprobe").exists()
    probe.rmdir()
    return sensitive


# ----------------------------------------------------------------- missing / malformed inputs


def test_contract_path_that_is_a_directory_is_file_missing(suite):
    reg, _, root = suite
    f = root / "Alpha/contracts/fam.v1.json"
    f.unlink()
    f.mkdir()  # a directory with the contract's name is not the contract
    r = _run(reg, root)
    assert "FILE_MISSING" in _codes(r) and not r.passed


def test_contract_with_utf8_bom_is_json_invalid_not_silently_accepted(suite):
    reg, _, root = suite
    f = root / "Alpha/contracts/fam.v1.json"
    f.write_bytes(b"\xef\xbb\xbf" + f.read_bytes())
    r = _run(reg, root)
    assert {"PIN_DRIFT", "JSON_INVALID"} <= set(_codes(r)) and not r.passed


def test_contract_in_utf16_is_json_invalid_not_a_crash(suite):
    reg, _, root = suite
    f = root / "Alpha/contracts/fam.v1.json"
    f.write_bytes(f.read_text(encoding="utf-8").encode("utf-16"))
    r = _run(reg, root)
    assert "JSON_INVALID" in _codes(r) and not r.passed


def test_empty_contract_file_fails(suite):
    reg, _, root = suite
    (root / "Alpha/contracts/fam.v1.json").write_bytes(b"")
    r = _run(reg, root)
    assert {"PIN_DRIFT", "JSON_INVALID"} <= set(_codes(r)) and not r.passed


def test_unreadable_contract_raises_rather_than_passing(suite, monkeypatch):
    """A permission error is not swallowed into a clean report: the run aborts (CLI exit != 0)."""
    reg, _, root = suite
    real = Path.read_bytes

    def denied(self):
        if self.name == "fam.v1.json":
            raise PermissionError(13, "Permission denied", str(self))
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", denied)
    with pytest.raises(PermissionError):
        _run(reg, root)


def test_mirror_manifest_in_bad_encoding_is_a_warning_not_a_crash(suite):
    reg, _, root = suite
    (root / "beta/vendor_alpha/VENDORED_FROM.json").write_bytes(b"\xff\xfe\x00garbage")
    r = _run(reg, root)
    assert "MIRROR_MANIFEST" in _codes(r)
    assert not _run(reg, root, strict=True).passed


def test_mirror_manifest_that_is_a_list_gives_no_pin(suite):
    reg, _, root = suite
    (root / "beta/vendor_alpha/VENDORED_FROM.json").write_text('["aaaaaaa"]', encoding="utf-8")
    r = _run(reg, root)
    assert "MIRROR_PIN" not in _codes(r) and "MIRROR_MANIFEST" not in _codes(r)


def test_repos_root_that_does_not_exist_reports_every_member_missing(suite, tmp_path):
    reg, _, _ = suite
    r = _run(reg, tmp_path / "nowhere")
    assert _codes(r).count("MEMBER_MISSING") == 2
    assert r.contracts_checked == 0 and not r.passed


def test_override_pointing_at_a_file_is_member_missing(suite, tmp_path):
    reg, _, root = suite
    f = tmp_path / "not_a_dir"
    f.write_text("x", encoding="utf-8")
    checkouts = resolve_checkouts(reg, root, {"alpha": f})
    assert "alpha" not in checkouts  # the override wins even when it is wrong: no fallback to repos_root
    r = check(reg, checkouts)
    assert "MEMBER_MISSING" in _codes(r) and not r.passed


def test_empty_only_examines_nothing_and_fails(suite):
    reg, _, root = suite
    r = _run(reg, root, only=[])
    assert r.contracts_checked == 0 and not r.passed
    assert sorted(r.members_skipped) == ["alpha", "beta"]
    assert "reason=no contract was examined" in r.summary()


def test_only_given_a_bare_string_is_not_read_as_a_member_name(suite):
    reg, _, root = suite
    r = _run(reg, root, only="alpha")  # iterates characters: every one is an unknown member
    assert "UNKNOWN_MEMBER" in _codes(r) and not r.passed


def test_load_registry_with_invalid_utf8_raises_a_valueerror(tmp_path):
    p = tmp_path / "reg.json"
    p.write_bytes(b'{"registry": "\xff"}')
    with pytest.raises(ValueError):  # UnicodeDecodeError, not RegistryError (see report); CLI still exits 2
        load_registry(p)


def test_cli_registry_with_invalid_utf8_exits_2(tmp_path, capsys):
    p = tmp_path / "reg.json"
    p.write_bytes(b'{"registry": "\xff"}')
    assert cli.main(["check", "--registry", str(p), "--repos-root", str(tmp_path)]) == 2
    assert "ATRIUM-CHECK: ERROR" in capsys.readouterr().err


@pytest.mark.parametrize("text", ["", "null", "[]", '"x"', "{} trailing", "{\"registry\": NaN"])
def test_cli_malformed_registry_json_exits_2_never_pass(tmp_path, capsys, text):
    p = tmp_path / "reg.json"
    p.write_text(text, encoding="utf-8")
    assert cli.main(["check", "--registry", str(p)]) == 2
    out = capsys.readouterr()
    assert "PASS" not in out.out + out.err


def test_cli_registry_with_bom_exits_2(suite, capsys):
    reg, path, root = suite
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    assert cli.main(["check", "--registry", str(path), "--repos-root", str(root)]) == 2


def test_cli_registry_that_is_a_directory_exits_2(tmp_path, capsys):
    assert cli.main(["check", "--registry", str(tmp_path)]) == 2


def test_cli_repin_on_malformed_registry_writes_nothing(suite, capsys):
    reg, path, root = suite
    path.write_text("{", encoding="utf-8")
    assert cli.main(["repin", "--registry", str(path), "--repos-root", str(root), "--apply"]) == 2
    assert path.read_text(encoding="utf-8") == "{"


def test_validate_registry_non_ascii_digit_version_is_a_problem_not_a_crash_via_cli(suite, tmp_path, capsys):
    reg, _, root = suite
    reg["contracts"][0]["name"] = "Rec/²"  # superscript two: str.isdigit() is True, int() raises
    p = tmp_path / "r.json"
    p.write_text(json.dumps(reg), encoding="utf-8")
    assert cli.main(["check", "--registry", str(p), "--repos-root", str(root)]) == 2


def test_validate_registry_superscript_version_returns_a_problem(suite):
    reg, _, _ = suite
    reg["contracts"][0]["name"] = "Rec/²"
    assert any("name" in p for p in validate_registry(reg))


# ----------------------------------------------------------------- hash mismatch / line endings


def test_lone_cr_is_not_folded_so_old_mac_line_endings_drift(suite):
    reg, _, root = suite
    f = root / "Alpha/contracts/fam.v1.json"
    f.write_bytes(f.read_bytes().replace(b"\n", b"\r"))
    assert "PIN_DRIFT" in _codes(_run(reg, root))


def test_crlf_and_lf_hash_identically_but_a_content_change_does_not(tmp_path):
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    a.write_bytes(b'{\n  "k": 1\n}\n')
    b.write_bytes(b'{\r\n  "k": 1\r\n}\r\n')
    c.write_bytes(b'{\r\n  "k": 2\r\n}\r\n')
    assert sha256_file(a) == sha256_file(b) != sha256_file(c)


def test_crlf_replica_is_not_stale(suite):
    reg, _, root = suite
    rel = "beta/fixtures/fam.v1.json"
    (root / rel).parent.mkdir(parents=True)
    (root / rel).write_bytes((root / "Alpha/contracts/fam.v1.json").read_bytes().replace(b"\n", b"\r\n"))
    reg["replicas"] = [{"contract": "Fam/1", "in": "beta", "path": "fixtures/fam.v1.json"}]
    r = _run(reg, root)
    assert "REPLICA_STALE" not in _codes(r) and r.mirror_files_compared >= 1


def test_single_byte_change_in_mirror_is_stale(suite):
    reg, _, root = suite
    f = root / "beta/vendor_alpha/contracts/fam.v1.json"
    f.write_bytes(f.read_bytes().replace(b"Fam/1", b"Fam/2"))
    r = _run(reg, root)
    assert "MIRROR_STALE" in _codes(r)
    assert not _run(reg, root, strict=True).passed


def test_plan_repin_ignores_crlf_only_differences(suite):
    reg, _, root = suite
    for rel in ("Alpha/contracts/rec.v1.schema.json", "beta/contracts/req.v2.schema.json"):
        f = root / rel
        f.write_bytes(f.read_bytes().replace(b"\n", b"\r\n"))
    assert plan_repin(reg, resolve_checkouts(reg, root)) == []


# ----------------------------------------------------------------- unregistered / case / backslash paths


def test_unregistered_file_in_a_second_contract_dir(suite):
    reg, _, root = suite
    reg["members"]["alpha"]["contract_dirs"] = ["contracts", "schemas"]
    (root / "Alpha/schemas").mkdir()
    (root / "Alpha/schemas/new.v1.json").write_text("{}", encoding="utf-8")
    r = _run(reg, root)
    msgs = [f.message for f in r.findings if f.code == "UNREGISTERED_FILE"]
    assert msgs == ["schemas/new.v1.json is a contract file the Atrium registry does not name"]
    assert not r.passed


def test_backslash_registry_path_never_passes(suite):
    """A registry written on Windows with backslashes must not pass on any OS.

    POSIX: the file is not found (FILE_MISSING) and the real file is UNREGISTERED_FILE.
    Windows: the file is found, but the as_posix() unregistered scan still flags it.
    """
    reg, _, root = suite
    reg["contracts"][1]["path"] = "contracts\\fam.v1.json"
    r = _run(reg, root)
    assert not r.passed
    assert "UNREGISTERED_FILE" in _codes(r)


def test_case_only_difference_in_registry_path_never_passes(suite):
    """Registry says Fam.v1.json, disk has fam.v1.json: an error on case-sensitive and case-insensitive file systems."""
    reg, _, root = suite
    reg["contracts"][1]["path"] = "contracts/FAM.v1.json"
    r = _run(reg, root)
    assert not r.passed
    assert "UNREGISTERED_FILE" in _codes(r)


@pytest.mark.xfail(
    condition=os.name != "nt",
    strict=True,
    reason="BUG: _check_unregistered globs '*.json' case-sensitively on POSIX, so an unregistered X.JSON passes",
)
def test_unregistered_file_with_uppercase_extension_is_flagged(suite):
    reg, _, root = suite
    (root / "Alpha/contracts/extra.v1.JSON").write_text("{}", encoding="utf-8")
    r = _run(reg, root)
    assert "UNREGISTERED_FILE" in _codes(r)


def test_case_insensitive_checkout_lookup_ignores_files(suite):
    """A regular *file* named like the member's dir is not a checkout."""
    reg, _, root = suite
    tmp = root.parent / "repos2"
    tmp.mkdir()
    (tmp / "alpha").write_text("not a dir", encoding="utf-8")
    assert "alpha" not in resolve_checkouts(reg, tmp)


@pytest.mark.xfail(strict=True, reason="BUG: two checkouts differing only by case ('Alpha', 'alpha') are resolved silently to whichever iterdir lists last")
def test_two_checkouts_differing_only_by_case_are_not_silently_resolved(suite, tmp_path):
    if not _case_sensitive_fs(tmp_path):
        pytest.xfail("case-insensitive file system cannot hold both directories")  # still an xfail, never an xpass
    reg, _, root = suite
    twin = root / "alpha"
    (twin / "contracts").mkdir(parents=True)
    for rel in ("contracts/rec.v1.schema.json", "contracts/fam.v1.json"):
        (twin / rel).write_bytes((root / "Alpha" / rel).read_bytes())
    r = _run(reg, root)
    assert not r.passed  # the ambiguity should be an error, not a coin flip


# ----------------------------------------------------------------- heads / pins


@pytest.mark.parametrize(
    "a,b,same",
    [
        ("abcdef1", "abcdef1234567", True),
        ("ABCDEF1", "abcdef1", True),
        ("abcdef", "abcdef", False),  # 6 characters never match
        ("", "", False),
        ("abcdef1", "abcdef2", False),
        ("abcdef12", "abcdef13", False),
    ],
)
def test_same_commit_boundaries(a, b, same):
    assert same_commit(a, b) is same


def test_empty_head_string_is_not_pinned(suite):
    reg, _, root = suite
    r = _run(reg, root, heads={"alpha": "", "beta": "bbbbbbb"})
    assert "HEAD_NOT_PINNED" in _codes(r) and not r.passed


def test_head_unknown_is_an_error_unless_allowed(suite):
    reg, _, root = suite
    heads = {"alpha": None, "beta": "bbbbbbb"}
    assert not _run(reg, root, heads=heads).passed
    allowed = _run(reg, root, heads=heads, allow_unpinned_head=True)
    assert allowed.passed and not _run(reg, root, heads=heads, allow_unpinned_head=True, strict=True).passed


# ----------------------------------------------------------------- repin / apply_repin


def test_apply_repin_keeps_the_original_when_the_replace_fails(suite, monkeypatch):
    reg, path, root = suite
    before = path.read_bytes()
    p = root / "Alpha/contracts/rec.v1.schema.json"
    p.write_text(p.read_text(encoding="utf-8") + " ", encoding="utf-8")
    changes = plan_repin(reg, resolve_checkouts(reg, root))

    def boom(self, target):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", boom)
    with pytest.raises(OSError):
        apply_repin(path, reg, changes)
    assert path.read_bytes() == before


def test_apply_repin_unknown_member_commit_writes_nothing(suite):
    reg, path, _ = suite
    before = path.read_bytes()
    with pytest.raises(KeyError):
        apply_repin(path, reg, [], {"ghost": "ccccccc"})
    assert path.read_bytes() == before
    assert not path.with_suffix(".json.tmp").exists()


def test_apply_repin_output_is_lf_terminated_utf8_and_round_trips(suite):
    reg, path, _ = suite
    reg["members"]["alpha"]["repo"] = "X/Alphä"  # non-ASCII survives unescaped
    apply_repin(path, reg, [])
    raw = path.read_bytes()
    assert raw.endswith(b"}\n") and not raw.endswith(b"\n\n") and b"\r" not in raw
    assert "Alphä".encode("utf-8") in raw
    assert load_registry(path) == reg


def test_apply_repin_over_a_crlf_registry_rewrites_it_as_lf(suite):
    reg, path, _ = suite
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    apply_repin(path, load_registry(path), [])
    assert b"\r" not in path.read_bytes()


def test_apply_repin_registry_without_json_suffix(suite, tmp_path):
    reg, path, _ = suite
    other = tmp_path / "registry"
    other.write_bytes(path.read_bytes())
    apply_repin(other, reg, [], {"alpha": "ddddddd"})
    assert load_registry(other)["members"]["alpha"]["pinned_commit"] == "ddddddd"
    assert not (tmp_path / "registry.json.tmp").exists()


def test_cli_repin_apply_then_check_passes(suite, capsys, monkeypatch):
    reg, path, root = suite
    monkeypatch.setattr(cli, "_git_head", lambda p: None)
    p = root / "Alpha/contracts/fam.v1.json"
    p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n").replace(b"{}", b'{"x": {}}'))
    for m in ("beta/vendor_alpha/contracts/fam.v1.json",):
        (root / m).write_bytes(p.read_bytes())
    assert cli.main(["repin", "--registry", str(path), "--repos-root", str(root), "--apply"]) == 0
    capsys.readouterr()
    reg2 = load_registry(path)
    assert check(reg2, resolve_checkouts(reg2, root)).passed


# ----------------------------------------------------------------- report verdict


def test_report_with_only_notes_passes_but_zero_contracts_never(suite):
    r = Report(contracts_checked=1)
    r.add("note", "X", "s", "m")
    assert r.passed
    r0 = Report()
    assert not r0.passed and "ATRIUM-CHECK: FAIL" in r0.summary()


def test_report_one_error_among_many_contracts_fails():
    r = Report(contracts_checked=1000)
    r.add("error", "PIN_DRIFT", "s", "m")
    assert not r.passed and r.to_json()["passed"] is False


def test_report_strict_turns_a_single_warning_into_fail():
    r = Report(contracts_checked=1, strict=True)
    r.add("warn", "MIRROR_STALE", "s", "m")
    assert not r.passed
    r.strict = False
    assert r.passed


def test_registry_error_is_a_valueerror_so_the_cli_catches_it():
    assert issubclass(RegistryError, ValueError)  # the CLI's except clause relies on this
