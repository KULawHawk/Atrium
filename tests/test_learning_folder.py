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


class Duck:
    """A gate result shaped like GateResult but not one: what Obsidian returns without importing this library."""

    def __init__(self, passed: object = True, gate: object = "obsidian.learning:gate", human_checked: object = True):
        self.passed, self.gate, self.human_checked = passed, gate, human_checked


def test_duck_typed_gate_result_accepted(root, tmp_path):
    f = LearningFolder(root, "obsidian")
    sha = f.add(item(tmp_path), "P", "obsidian checked copy", "jake", gate=lambda p: Duck())
    assert f.approved() == [sha]
    assert lines(root, "obsidian")[0]["gate"] == "obsidian.learning:gate"


@pytest.mark.parametrize(
    "duck",
    [
        Duck(passed=1),
        Duck(passed="yes"),
        Duck(passed=None),
        Duck(human_checked=1),
        Duck(human_checked="checked"),
        Duck(gate=None),
        Duck(gate=7),
        Duck(gate=""),
        Duck(gate="two\nlines"),
        GateResult(1, "obsidian.learning:gate", human_checked=True),  # a real GateResult still needs real bools
        object(),
    ],
)
def test_badly_shaped_gate_result_refused(root, tmp_path, duck):
    f = LearningFolder(root, "obsidian")
    with pytest.raises(LearningFolderError):
        f.add(item(tmp_path), "P", "obsidian checked copy", "jake", gate=lambda p: duck)
    assert f.approved() == []


def test_duck_typed_refusal_and_unchecked_still_refused(root, tmp_path):
    f = LearningFolder(root, "obsidian")
    with pytest.raises(LearningFolderError, match="refused"):
        f.add(item(tmp_path), "P", "c", "jake", gate=lambda p: Duck(passed=False))
    with pytest.raises(LearningFolderError, match="Decision 38"):
        f.add(item(tmp_path), "P", "c", "jake", gate=lambda p: Duck(human_checked=False))
    assert f.approved() == []


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


# ---- Decision 53: Jake may put back what he removed, for 30 days ------------------------------------------

from datetime import datetime, timedelta, timezone  # noqa: E402

from atrium_learning import ADD_BACK_DAYS, add_back_warning  # noqa: E402


def removed(root, tmp_path, reason="removed_by_jake"):
    f = LearningFolder(root, "obsidian")
    sha = f.add(item(tmp_path), "P", "obsidian copy", "jake", gate=checked)
    f.hold_aside(sha, reason, "jake")
    return f, sha


def removal_time(root, sha):
    row = [r for r in lines(root, "obsidian") if r["sha256"] == sha][-1]
    return datetime.fromisoformat(row["added_at"])


def test_window_is_thirty_days():
    assert ADD_BACK_DAYS == 30


def test_days_left_counts_down_and_closes(root, tmp_path):
    f, sha = removed(root, tmp_path)
    t = removal_time(root, sha)
    assert f.add_back_days_left(sha, t) == 30
    assert f.add_back_days_left(sha, t + timedelta(days=29, hours=1)) == 1
    assert f.add_back_days_left(sha, t + timedelta(days=30)) == 0
    assert f.add_back_days_left(sha, t + timedelta(days=400)) == 0


def test_days_left_none_unless_jake_removed_it(root, tmp_path):
    f, sha = removed(root, tmp_path, reason="identifier_found")
    assert f.add_back_days_left(sha) is None
    assert f.add_back_days_left("0" * 64) is None
    g = LearningFolder(root, "readers-print")
    s2 = g.add(item(tmp_path, body="s"), "S", "synthetic", "jake")
    assert g.add_back_days_left(s2) is None


@pytest.mark.parametrize("stamp", ["not a time", "2026-11-23T10:00:00"])
def test_unreadable_or_zoneless_removal_time_counts_as_closed(root, tmp_path, stamp):
    f, sha = removed(root, tmp_path)
    m = root / "learning" / "obsidian" / "manifest.jsonl"
    rows = [json.loads(x) for x in m.read_text().splitlines()]
    rows[-1]["added_at"] = stamp
    m.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert f.add_back_days_left(sha) == 0
    with pytest.raises(LearningFolderError, match="no longer"):
        f.add_back(sha, "jake", gate=checked)


def test_plain_add_of_a_removed_item_is_refused_with_days_left(root, tmp_path):
    f, sha = removed(root, tmp_path)
    with pytest.raises(LearningFolderError, match="30 more days"):
        f.add(item(tmp_path), "P", "obsidian copy", "jake", gate=checked)
    assert f.approved() == []


def test_add_back_within_window_moves_the_same_copy_back(root, tmp_path):
    f, sha = removed(root, tmp_path)
    d = root / "learning" / "obsidian"
    words = f.add_back(sha, "jake", gate=checked)
    assert words == add_back_warning(30)
    assert f.approved() == [sha]
    assert (d / "approved" / f"{sha}.txt").is_file() and not list((d / "held-aside").iterdir())
    row = lines(root, "obsidian")[-1]
    assert row["event"] == "added" and row["added_by"] == "jake" and row["gate"] == "obsidian_checked_copy"
    audit = [json.loads(x) for x in (d / "audit.jsonl").read_text().splitlines()]
    assert audit[-1]["event"] == "added_back" and audit[-1]["days_left"] == 30 and audit[-1]["sha256"] == sha
    # it can be removed again, which starts a fresh 30 days
    f.hold_aside(sha, "removed_by_jake", "jake")
    assert f.add_back_days_left(sha) == 30


def test_add_back_after_window_is_permanent(root, tmp_path):
    f, sha = removed(root, tmp_path)
    late = removal_time(root, sha) + timedelta(days=30, seconds=1)
    with pytest.raises(LearningFolderError, match="more than 30 days"):
        f.add_back(sha, "jake", gate=checked, now=late)
    assert f.approved() == []


def test_plain_add_after_window_is_refused(root, tmp_path, monkeypatch):
    f, sha = removed(root, tmp_path)
    late = removal_time(root, sha) + timedelta(days=31)
    real = f.add_back_days_left
    monkeypatch.setattr(f, "add_back_days_left", lambda s, now=None: real(s, late))
    with pytest.raises(LearningFolderError, match="can no longer be added back"):
        f.add(item(tmp_path), "P", "obsidian copy", "jake", gate=checked)


def test_add_back_never_by_auto(root, tmp_path):
    f, sha = removed(root, tmp_path)
    with pytest.raises(LearningFolderError, match="automatic"):
        f.add_back(sha, "auto", gate=checked)
    assert f.approved() == []


def test_add_back_only_for_jakes_removals(root, tmp_path):
    f, sha = removed(root, tmp_path, reason="identifier_found")
    with pytest.raises(LearningFolderError, match="not removed by Jake"):
        f.add_back(sha, "jake", gate=checked)


def test_add_back_runs_the_fresh_check(root, tmp_path):
    f, sha = removed(root, tmp_path)
    with pytest.raises(LearningFolderError, match="Decision 38"):
        f.add_back(sha, "jake", gate=unchecked)
    with pytest.raises(LearningFolderError, match="refused"):
        f.add_back(sha, "jake", gate=refuses)
    with pytest.raises(LearningFolderError, match="its aim's own gate"):
        f.add_back(sha, "jake")
    assert f.approved() == [] and f.add_back_days_left(sha) == 30


def test_add_back_refuses_a_changed_copy(root, tmp_path):
    f, sha = removed(root, tmp_path)
    (root / "learning" / "obsidian" / "held-aside" / f"{sha}.txt").write_text("changed")
    with pytest.raises(LearningFolderError, match="changed on disk"):
        f.add_back(sha, "jake", gate=checked)


def test_add_back_refuses_when_approved_already_has_the_file(root, tmp_path):
    f, sha = removed(root, tmp_path)
    (root / "learning" / "obsidian" / "approved" / f"{sha}.txt").write_text("stray")
    with pytest.raises(LearningFolderError, match="already holds"):
        f.add_back(sha, "jake", gate=checked)
    assert (root / "learning" / "obsidian" / "held-aside" / f"{sha}.txt").is_file()


def test_automatic_adding_never_puts_back_a_held_aside_item(root, tmp_path):
    for reason in ("removed_by_jake", "identifier_found"):
        r = tmp_path / reason
        make_aim(r, "obsidian")
        f, sha = removed(r, tmp_path, reason)
        f.set_auto_add(True, "jake")
        with pytest.raises(LearningFolderError, match="automatic adding never"):
            f.offer(item(tmp_path), "P", "obsidian copy", gate=checked)
        assert f.approved() == []


def test_warning_words():
    assert "1 more day;" in add_back_warning(1)
    assert "12 more days;" in add_back_warning(12)
