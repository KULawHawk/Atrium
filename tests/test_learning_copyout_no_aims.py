"""Copy-out over no aim at all is a FAIL, never a PASS (hunt 2026-11-24). Synthetic data only.

On main 3febbe8 an install root whose learning folder held no aim folder printed ``LEARNING-COPY: PASS aims=0``:
nothing was examined and nothing was sent, yet the run read as a pass.
"""

from __future__ import annotations

from pathlib import Path

from atrium_learning.copyout import main
from test_learning_copyout import PASS_GUARD, guard_file


def test_no_aim_folders_is_a_fail(tmp_path: Path, capsys):
    root = tmp_path / "root"
    (root / "learning").mkdir(parents=True)
    guard = guard_file(tmp_path, PASS_GUARD)
    rc = main(["--dest", str(tmp_path / "share"), "--guard", str(guard), "--root", str(root)])
    out = capsys.readouterr().out
    assert rc == 1 and out.strip().endswith("LEARNING-COPY: FAIL aims=0 failed=0")
    assert "no aim folder was found" in out
    assert not (tmp_path / "share").exists()
