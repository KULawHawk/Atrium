"""Learning folders (design learning-folders/DESIGN_learning_folders_2026-11-22.md). Synthetic data only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atrium_learning import (
    AIMS,
    SUBFOLDERS,
    GateResult,
    LearningFolder,
    LearningFolderError,
    find_install_root,
)
from atrium_learning.folder import manual_oks, record_manual_ok


def make_aim(root: Path, aim: str) -> Path:
    d = root / "learning" / aim
    for s in SUBFOLDERS:
        (d / s).mkdir(parents=True, exist_ok=True)
    (d / "manifest.jsonl").touch()
    return d


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for aim in AIMS:
        make_aim(tmp_path, aim)
    return tmp_path


def item(tmp_path: Path, name: str = "key.txt", body: str = "synthetic answer key 1") -> Path:
    p = tmp_path / "src" / name
    p.parent.mkdir(exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def checked(path: Path) -> GateResult:
    return GateResult(True, "obsidian_checked_copy", human_checked=True)


def unchecked(path: Path) -> GateResult:
    return GateResult(True, "obsidian_draft_copy", human_checked=False)


def refuses(path: Path) -> GateResult:
    return GateResult(False, "obsidian_checked_copy")


def lines(root: Path, aim: str) -> list[dict]:
    text = (root / "learning" / aim / "manifest.jsonl").read_text(encoding="utf-8")
    return [json.loads(x) for x in text.splitlines() if x]


# ---- install root ---------------------------------------------------------------------------------


def test_install_root_from_adastra_json(tmp_path):
    (tmp_path / "adastra.json").write_text(json.dumps({"install_root": "C:/AdAstra", "envs": [], "part": "x"}))
    assert find_install_root(tmp_path) == Path("C:/AdAstra")


def test_install_root_default_prefix_missing_refuses(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.prefix", str(tmp_path))
    with pytest.raises(LearningFolderError, match="LEARNING: FAIL no adastra.json"):
        find_install_root()


@pytest.mark.parametrize("body", ["{not json", json.dumps(["x"]), json.dumps({"install_root": ""}), json.dumps({})])
def test_install_root_bad_marker_refuses(tmp_path, body):
    (tmp_path / "adastra.json").write_text(body)
    with pytest.raises(LearningFolderError):
        find_install_root(tmp_path)


# ---- opening a folder -----------------------------------------------------------------------------


def test_bad_aim_name_refuses(root):
    with pytest.raises(LearningFolderError, match="not a folder name"):
        LearningFolder(root, "../escape")


def test_missing_folder_refuses_and_is_never_created(tmp_path):
    with pytest.raises(LearningFolderError, match="run the AdAstra installer"):
        LearningFolder(tmp_path, "obsidian")
    assert not (tmp_path / "learning").exists()


def test_new_aim_needs_only_its_folder(tmp_path):
    make_aim(tmp_path, "new-aim")
    assert LearningFolder(tmp_path, "new-aim").approved() == []


# ---- class S --------------------------------------------------------------------------------------


def test_add_synthetic_item(root, tmp_path):
    f = LearningFolder(root, "readers-print")
    sha = f.add(item(tmp_path), "S", "synthetic: calibration kit", "jake")
    assert f.approved() == [sha]
    assert (root / "learning" / "readers-print" / "approved" / f"{sha}.txt").read_text() == "synthetic answer key 1"
    row = lines(root, "readers-print")[0]
    assert set(row) == {"sha256", "class", "source", "added_at", "added_by", "gate", "event"}
    assert row["event"] == "added" and row["gate"] == "provenance" and row["class"] == "S"
    assert "key.txt" not in json.dumps(row)


def test_odd_suffix_dropped(root, tmp_path):
    f = LearningFolder(root, "readers-print")
    sha = f.add(item(tmp_path, "page.Weird_Suffix!"), "S", "synthetic", "jake")
    assert (root / "learning" / "readers-print" / "approved" / sha).is_file()


def test_s_with_extra_gate_records_its_name(root, tmp_path):
    f = LearningFolder(root, "handwriting")
    f.add(item(tmp_path), "S", "public: NIST SD19", "jake", gate=lambda p: GateResult(True, "licence_noted"))
    assert lines(root, "handwriting")[0]["gate"] == "licence_noted"


@pytest.mark.parametrize("name", [".env", "credentials.json", "API key.txt", "my_token.txt", "vault.kdbx", "x.pem"])
def test_secret_named_files_refused(root, tmp_path, name):
    with pytest.raises(LearningFolderError, match="SEC-3"):
        LearningFolder(root, "readers-print").add(item(tmp_path, name), "S", "synthetic", "jake")


def test_not_a_file_refused(root, tmp_path):
    with pytest.raises(LearningFolderError, match="not a file"):
        LearningFolder(root, "readers-print").add(tmp_path, "S", "synthetic", "jake")


def test_bad_class_refused(root, tmp_path):
    with pytest.raises(LearningFolderError, match="class"):
        LearningFolder(root, "readers-print").add(item(tmp_path), "X", "synthetic", "jake")


@pytest.mark.parametrize("source", ["", "  ", "two\nlines", "x" * 201, None])
def test_bad_source_refused(root, tmp_path, source):
    with pytest.raises(LearningFolderError):
        LearningFolder(root, "readers-print").add(item(tmp_path), "S", source, "jake")


def test_duplicate_refused(root, tmp_path):
    f = LearningFolder(root, "readers-print")
    f.add(item(tmp_path), "S", "synthetic", "jake")
    with pytest.raises(LearningFolderError, match="already in approved"):
        f.add(item(tmp_path), "S", "synthetic", "jake")


# ---- class M --------------------------------------------------------------------------------------


def test_manual_item_needs_jakes_ok(root, tmp_path):
    f = LearningFolder(root, "formulas-tables")
    with pytest.raises(LearningFolderError, match="LF-3"):
        f.add(item(tmp_path), "M", "WISC-V 2014", "jake")
    record_manual_ok(root, "WISC-V 2014", "jake")
    assert manual_oks(root) == {"WISC-V 2014"}
    f.add(item(tmp_path), "M", "WISC-V 2014", "jake")
    assert lines(root, "formulas-tables")[0]["gate"] == "manual_ok"


def test_withdrawing_manual_ok_moves_its_items_aside_everywhere(root, tmp_path):
    record_manual_ok(root, "WISC-V 2014", "jake")
    a = LearningFolder(root, "formulas-tables")
    b = LearningFolder(root, "readers-print")
    sa = a.add(item(tmp_path, body="m1"), "M", "WISC-V 2014", "jake")
    sb = b.add(item(tmp_path, body="m2"), "M", "WISC-V 2014", "jake")
    keep = b.add(item(tmp_path, body="s1"), "S", "synthetic", "jake")
    other = b.add(item(tmp_path, body="m3"), "M", "WISC-V 2014", "jake")
    b.hold_aside(other, "removed_by_jake", "jake")
    (root / "learning" / "not a folder name").mkdir()
    moved = record_manual_ok(root, "WISC-V 2014", "jake", ok=False)
    assert sorted(moved) == sorted([sa, sb])
    assert manual_oks(root) == set()
    assert a.approved() == [] and b.approved() == [keep]
    assert lines(root, "formulas-tables")[-1]["reason"] == "manual_ok_withdrawn"


def test_manual_ok_needs_installed_tree(tmp_path):
    with pytest.raises(LearningFolderError, match="installer"):
        record_manual_ok(tmp_path, "WISC-V 2014", "jake")


# ---- class P (Decision 38 = A) ---------------------------------------------------------------------


def test_real_report_item_needs_gate(root, tmp_path):
    with pytest.raises(LearningFolderError, match="its aim's own gate"):
        LearningFolder(root, "obsidian").add(item(tmp_path), "P", "obsidian checked copy", "jake")


def test_real_report_item_needs_human_check(root, tmp_path):
    with pytest.raises(LearningFolderError, match="Decision 38"):
        LearningFolder(root, "obsidian").add(item(tmp_path), "P", "obsidian copy", "jake", gate=unchecked)


def test_gate_refusal_is_loud(root, tmp_path):
    with pytest.raises(LearningFolderError, match="gate obsidian_checked_copy refused"):
        LearningFolder(root, "obsidian").add(item(tmp_path), "P", "obsidian copy", "jake", gate=refuses)


def test_gate_must_return_gateresult(root, tmp_path):
    with pytest.raises(LearningFolderError, match="GateResult"):
        LearningFolder(root, "obsidian").add(item(tmp_path), "P", "obsidian copy", "jake", gate=lambda p: True)


def test_checked_real_report_item_added(root, tmp_path):
    f = LearningFolder(root, "obsidian")
    sha = f.add(item(tmp_path), "P", "obsidian checked copy", "jake", gate=checked)
    assert f.approved() == [sha]
    assert lines(root, "obsidian")[0]["gate"] == "obsidian_checked_copy"


# ---- automatic switch (off by default) -------------------------------------------------------------


def test_switch_off_by_default_offer_adds_nothing(root, tmp_path):
    f = LearningFolder(root, "readers-print")
    assert f.auto_add is False
    assert f.offer(item(tmp_path), "S", "synthetic") is None
    assert f.approved() == []


def test_switch_on_adds_as_auto_and_is_audited(root, tmp_path):
    f = LearningFolder(root, "readers-print")
    f.set_auto_add(True, "jake")
    assert f.auto_add is True
    sha = f.offer(item(tmp_path), "S", "synthetic")
    assert lines(root, "readers-print")[0]["added_by"] == "auto" and f.approved() == [sha]
    f.set_auto_add(False, "jake")
    audit = (root / "learning" / "readers-print" / "audit.jsonl").read_text().splitlines()
    assert [json.loads(x)["value"] for x in audit] == [True, False]


def test_auto_real_report_only_checked_copies(root, tmp_path):
    f = LearningFolder(root, "obsidian")
    f.set_auto_add(True, "jake")
    with pytest.raises(LearningFolderError, match="Decision 38"):
        f.offer(item(tmp_path, body="draft"), "P", "obsidian copy", gate=unchecked)
    assert f.offer(item(tmp_path, body="checked"), "P", "obsidian copy", gate=checked)


def test_switch_value_must_be_bool(root):
    with pytest.raises(LearningFolderError, match="true or false"):
        LearningFolder(root, "readers-print").set_auto_add("yes", "jake")


@pytest.mark.parametrize("body", ["{bad", json.dumps({"auto_add": "yes"}), json.dumps([1])])
def test_unreadable_switch_refuses(root, body):
    (root / "learning" / "readers-print" / "settings.json").write_text(body)
    with pytest.raises(LearningFolderError):
        LearningFolder(root, "readers-print").auto_add


# ---- hold aside, never delete ------------------------------------------------------------------------


def test_hold_aside_moves_and_logs(root, tmp_path):
    f = LearningFolder(root, "obsidian")
    sha = f.add(item(tmp_path), "P", "obsidian copy", "jake", gate=checked)
    f.hold_aside(sha, "identifier_found", "jake")
    d = root / "learning" / "obsidian"
    assert not list((d / "approved").iterdir()) and (d / "held-aside" / f"{sha}.txt").is_file()
    row = lines(root, "obsidian")[-1]
    assert row["event"] == "held_aside" and row["reason"] == "identifier_found" and row["class"] == "P"
    assert f.approved() == []
    # it may come back by a fresh add
    f.add(item(tmp_path), "P", "obsidian copy", "jake", gate=checked)
    assert f.approved() == [sha]


def test_hold_aside_bad_reason(root):
    with pytest.raises(LearningFolderError, match="reason"):
        LearningFolder(root, "obsidian").hold_aside("0" * 64, "because", "jake")


def test_hold_aside_unknown_item(root):
    with pytest.raises(LearningFolderError, match="not in approved"):
        LearningFolder(root, "obsidian").hold_aside("0" * 64, "removed_by_jake", "jake")


# ---- copy for the connector ----------------------------------------------------------------------------


def test_items_for_copy_rechecks(root, tmp_path):
    f = LearningFolder(root, "obsidian")
    a = f.add(item(tmp_path, body="a"), "P", "obsidian copy", "jake", gate=checked)
    b = f.add(item(tmp_path, body="b"), "P", "obsidian copy", "jake", gate=checked)
    f.hold_aside(b, "removed_by_jake", "jake")
    assert [p.name for p in f.items_for_copy(gate=checked)] == [f"{a}.txt"]
    with pytest.raises(LearningFolderError, match="refused"):
        f.items_for_copy(gate=refuses)


def test_items_for_copy_detects_changed_file(root, tmp_path):
    f = LearningFolder(root, "readers-print")
    sha = f.add(item(tmp_path), "S", "synthetic", "jake")
    (root / "learning" / "readers-print" / "approved" / f"{sha}.txt").write_text("changed")
    with pytest.raises(LearningFolderError, match="changed on disk"):
        f.items_for_copy()


def test_items_for_copy_missing_file(root, tmp_path):
    f = LearningFolder(root, "readers-print")
    sha = f.add(item(tmp_path), "S", "synthetic", "jake")
    (root / "learning" / "readers-print" / "approved" / f"{sha}.txt").unlink()
    with pytest.raises(LearningFolderError, match="expected 1"):
        f.items_for_copy()


# ---- manifest problems are loud ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    ["{bad json", json.dumps([1]), json.dumps({"event": "added"}), json.dumps({"sha256": "x", "event": "gone"})],
)
def test_bad_manifest_line_refuses(root, line):
    (root / "learning" / "obsidian" / "manifest.jsonl").write_text("\n" + line + "\n")
    with pytest.raises(LearningFolderError):
        LearningFolder(root, "obsidian").state()
