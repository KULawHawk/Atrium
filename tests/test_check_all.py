"""scripts/check_all.py: which checkout does the atrium_check step examine?"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_all", ROOT / "scripts" / "check_all.py")
check_all = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_all)


class FakePopen:
    def __init__(self, *a, **k):
        self.stdout = iter(["1 passed in 0.01s\n"])

    def wait(self):
        return 0


def run_main(monkeypatch, tmp_path, argv):
    seen = []

    def fake_run(cmd, **k):
        if cmd[0] == "git":
            return subprocess.CompletedProcess(cmd, 0, "", "")
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "ATRIUM-CHECK: PASS\n", "")

    monkeypatch.setattr(check_all.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(check_all.subprocess, "run", fake_run)
    monkeypatch.setattr(check_all, "_have", lambda kind, name: True)
    rc = check_all.main(argv)
    return rc, seen


def test_atrium_check_examines_the_checkout_whose_tests_ran(monkeypatch, tmp_path):
    worktree = tmp_path / "wt" / "locutus"  # a feature-branch worktree, not <repos-root>/locutus
    worktree.mkdir(parents=True)
    (worktree / "pyproject.toml").write_text("")
    primary_root = tmp_path / "repos"
    primary_root.mkdir()
    rc, seen = run_main(monkeypatch, tmp_path, ["--repo-dir", str(worktree), "--repos-root", str(primary_root)])
    assert rc == 0
    (cmd,) = seen
    assert "--repo" in cmd and f"locutus={worktree.resolve()}" in cmd


def test_atrium_itself_adds_no_repo_override(monkeypatch, tmp_path):
    here = tmp_path / "atrium"
    here.mkdir()
    (here / "pyproject.toml").write_text("")
    rc, seen = run_main(monkeypatch, tmp_path, ["--repo-dir", str(here)])
    assert rc == 0 and "--repo" not in seen[0]


def _popen_env(monkeypatch, tmp_path, name):
    here = tmp_path / name
    here.mkdir(parents=True)
    (here / "pyproject.toml").write_text("")
    envs = []

    class RecordingPopen(FakePopen):
        def __init__(self, *a, **k):
            envs.append(k["env"])
            super().__init__(*a, **k)

    monkeypatch.setattr(check_all.subprocess, "Popen", RecordingPopen)
    monkeypatch.setattr(check_all.subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(cmd, 0, "ATRIUM-CHECK: PASS\n", ""))
    monkeypatch.setattr(check_all, "_have", lambda kind, n: True)
    monkeypatch.delenv("SEQUOIA_REQUIRE_Z3", raising=False)
    check_all.main(["--repo-dir", str(here)])
    (env,) = envs
    return env


def test_sequoia_tests_run_with_z3_required(monkeypatch, tmp_path):
    assert _popen_env(monkeypatch, tmp_path, "sequoia").get("SEQUOIA_REQUIRE_Z3") == "1"


def test_other_members_do_not_get_the_sequoia_switch(monkeypatch, tmp_path):
    for name in ("locutus", "obsidian", "atrium"):
        assert "SEQUOIA_REQUIRE_Z3" not in _popen_env(monkeypatch, tmp_path / name, name)
