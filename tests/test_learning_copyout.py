"""Copy-out of approved learning items (design §5). Synthetic data only; the guard is a stand-in script."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from atrium_learning import GateResult, LearningFolder, LearningFolderError
from atrium_learning.copyout import copy_out, load_gate, main, run_guard
from test_learning_folder import checked, item, make_aim

PASS_GUARD = "print('PATIENT-RUN-GUARD: PASS - 0 run(s) found')\n"
STOP_GUARD = "import sys\nprint('PATIENT-RUN-GUARD: STOP - nothing may be copied')\nsys.exit(2)\n"
LIAR_GUARD = "print('all good')\n"  # exit 0 but no PASS line: must not count as a pass
SILENT_GUARD = "import sys\nsys.exit(2)\n"


def guard_file(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "guard.py"
    p.write_text(body)
    return p


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "root"
    for aim in ("readers-print", "obsidian"):
        make_aim(r, aim)
    LearningFolder(r, "readers-print").add(item(tmp_path, body="s1"), "S", "synthetic", "jake")
    LearningFolder(r, "obsidian").add(item(tmp_path, body="p1"), "P", "obsidian copy", "jake", gate=checked)
    return r


def ok_guard(folder: Path) -> tuple[bool, str]:
    return True, "PATIENT-RUN-GUARD: PASS"


@pytest.mark.parametrize(
    "body,expected", [(PASS_GUARD, True), (STOP_GUARD, False), (LIAR_GUARD, False), (SILENT_GUARD, False)]
)
def test_run_guard_needs_exit0_and_pass_line(tmp_path, body, expected):
    ok, _ = run_guard(guard_file(tmp_path, body))(tmp_path)
    assert ok is expected


def test_copy_out_all_aims(root, tmp_path):
    dest = tmp_path / "share"
    result = copy_out(root, dest, ok_guard, {"obsidian": checked}, run_id="r1")
    assert result == {"obsidian": "PASS n=1", "readers-print": "PASS n=1"}
    assert len(list((dest / "obsidian").iterdir())) == 2  # item + manifest
    report = json.loads((root / "learning" / "_outbox" / "r1.json").read_text())
    assert report["aims"] == result


def test_real_report_aim_without_gate_fails_alone(root, tmp_path):
    result = copy_out(root, tmp_path / "share", ok_guard, {}, run_id="r1")
    assert result["readers-print"] == "PASS n=1"
    assert result["obsidian"].startswith("FAIL") and "own gate" in result["obsidian"]
    assert not (tmp_path / "share" / "obsidian").exists()


def test_guard_stop_blocks_the_aim(root, tmp_path):
    result = copy_out(root, tmp_path / "share", lambda f: (False, ""), {"obsidian": checked}, ["obsidian"], "r1")
    assert result["obsidian"] == "FAIL LEARNING: FAIL patient-run guard did not pass: no output"
    assert not (tmp_path / "share").exists()


def test_copy_out_default_run_id_and_missing_tree(root, tmp_path):
    assert copy_out(root, tmp_path / "share", ok_guard, {"obsidian": checked}, ["readers-print"])
    with pytest.raises(LearningFolderError, match="installer"):
        copy_out(tmp_path / "nowhere", tmp_path / "share", ok_guard, {})


def test_load_gate(monkeypatch):
    mod = types.ModuleType("fake_gates")
    mod.gate = checked
    mod.not_callable = 3
    monkeypatch.setitem(sys.modules, "fake_gates", mod)
    assert load_gate("fake_gates:gate") is checked
    for bad in ("nocolon", "fake_gates:missing", "no_such_module_xyz:gate", "fake_gates:not_callable"):
        with pytest.raises(LearningFolderError):
            load_gate(bad)


def test_main_pass(root, tmp_path, monkeypatch, capsys):
    mod = types.ModuleType("fake_gates2")
    mod.gate = checked
    monkeypatch.setitem(sys.modules, "fake_gates2", mod)
    guard = guard_file(tmp_path, PASS_GUARD)
    rc = main(["--dest", str(tmp_path / "share"), "--guard", str(guard), "--root", str(root),
               "--gate", "obsidian=fake_gates2:gate"])
    out = capsys.readouterr().out
    assert rc == 0 and out.strip().endswith("LEARNING-COPY: PASS aims=2 failed=0")


def test_main_aim_failure_is_fail(root, tmp_path, capsys):
    guard = guard_file(tmp_path, PASS_GUARD)
    rc = main(["--dest", str(tmp_path / "share"), "--guard", str(guard), "--root", str(root)])
    assert rc == 1 and "LEARNING-COPY: FAIL aims=2 failed=1" in capsys.readouterr().out


@pytest.mark.parametrize("extra", [["--gate", "obsidian"], ["--guard-missing"]])
def test_main_refusals(root, tmp_path, capsys, extra):
    guard = guard_file(tmp_path, PASS_GUARD)
    args = ["--dest", str(tmp_path / "share"), "--root", str(root)]
    if extra == ["--guard-missing"]:
        args += ["--guard", str(tmp_path / "nope.py")]
    else:
        args += ["--guard", str(guard), *extra]
    assert main(args) == 1
    assert capsys.readouterr().out.strip().endswith("LEARNING-COPY: FAIL")


def test_main_root_from_adastra_json(root, tmp_path, monkeypatch, capsys):
    (tmp_path / "adastra.json").write_text(json.dumps({"install_root": str(root)}))
    monkeypatch.setattr("sys.prefix", str(tmp_path))
    guard = guard_file(tmp_path, PASS_GUARD)
    assert main(["--dest", str(tmp_path / "share"), "--guard", str(guard), "--aim", "readers-print"]) == 0


def test_gateresult_reexported():
    assert GateResult(True, "x").human_checked is False


def test_manual_items_stay_unless_included(root, tmp_path):
    from atrium_learning.folder import record_manual_ok

    record_manual_ok(root, "WISC-V 2014", "jake")
    LearningFolder(root, "readers-print").add(item(tmp_path, body="m1"), "M", "WISC-V 2014", "jake")
    assert copy_out(root, tmp_path / "a", ok_guard, {}, ["readers-print"], "r1")["readers-print"] == "PASS n=1"
    assert copy_out(root, tmp_path / "b", ok_guard, {}, ["readers-print"], "r2", include_manual=True)[
        "readers-print"
    ] == "PASS n=2"
