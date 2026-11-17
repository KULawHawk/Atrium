"""Test-gap lane: scripts/check_all.py must never print CHECK-ALL: PASS unless every step ran and passed.

pytest and atrium_check are faked (no child processes); each test builds a synthetic
member folder in tmp_path.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check_all_gaps", ROOT / "scripts" / "check_all.py")
check_all = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_all)


def _member(tmp_path: Path, name: str = "locutus") -> Path:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "pyproject.toml").write_text("", encoding="utf-8")
    return d


def _drive(monkeypatch, capsys, tmp_path, *, pytest_out="5 passed in 0.1s\n", pytest_rc=0,
           ac_out="ATRIUM-CHECK: PASS errors=0\n", ac_err="", ac_rc=0, have=True, name="locutus", extra=()):
    repo = _member(tmp_path, name)

    class FakePopen:
        def __init__(self, *a, **k):
            self.stdout = iter(pytest_out.splitlines(keepends=True))

        def wait(self):
            return pytest_rc

    def fake_run(cmd, **k):
        if cmd[0] == "git":
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, ac_rc, ac_out, ac_err)

    monkeypatch.setattr(check_all.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(check_all.subprocess, "run", fake_run)
    monkeypatch.setattr(check_all, "_have", (lambda k, n: have) if isinstance(have, bool) else have)
    rc = check_all.main(["--repo-dir", str(repo), *extra])
    out = capsys.readouterr().out
    final = [l for l in out.splitlines() if l.startswith("CHECK-ALL:")]
    assert len(final) == 1, out
    return rc, final[0], out


def test_baseline_all_green_is_pass(monkeypatch, capsys, tmp_path):
    rc, line, _ = _drive(monkeypatch, capsys, tmp_path)
    assert rc == 0 and line.startswith("CHECK-ALL: PASS") and "tests=5 passed/0 skipped" in line


@pytest.mark.parametrize(
    "out,rc,needle",
    [
        ("no tests ran in 0.01s\n", 5, "(NO TESTS RAN)"),          # nothing collected
        ("", 0, "(NO TESTS RAN)"),                                 # rc 0 but no summary line at all
        ("3 skipped in 0.01s\n", 0, "(NO TESTS RAN)"),             # everything skipped
        ("2 deselected in 0.01s\n", 0, "(NO TESTS RAN)"),          # everything deselected
        ("1 xfailed in 0.01s\n", 0, "(NO TESTS RAN)"),             # only expected failures
        ("1 failed, 5 passed in 0.1s\n", 1, "/1 failed"),
        ("5 passed, 2 errors in 0.1s\n", 1, "/2 failed"),          # errors count as failures
        ("1 error in 0.1s\n", 2, "/1 failed"),                     # collection error, interrupted
        ("5 passed in 0.1s\n", 3, "5 passed"),                     # internal error with a stale-looking line
        ("5 passed in 0.1s\n", 4, "5 passed"),                     # usage error
        ("5 passed in 0.1s\n", -9, "5 passed"),                    # killed by a signal
        ("Traceback (most recent call last):\n  boom\n", 1, "0 passed"),  # pytest itself crashed
    ],
)
def test_tests_not_clean_is_never_pass(monkeypatch, capsys, tmp_path, out, rc, needle):
    code, line, _ = _drive(monkeypatch, capsys, tmp_path, pytest_out=out, pytest_rc=rc)
    assert code == 1 and line.startswith("CHECK-ALL: FAIL"), line
    assert needle in line


@pytest.mark.xfail(strict=True, reason="BUG: check_all.py prints CHECK-ALL: PASS when pytest exits 0 but reports failed/error tests")
@pytest.mark.parametrize(
    "out",
    ["1 failed, 5 passed in 0.1s\n", "5 passed, 1 error in 0.1s\n"],
)
def test_failures_reported_with_exit_0_are_still_fail(monkeypatch, capsys, tmp_path, out):
    """A plugin or pytest_args (e.g. a suppress-failed-exit-code option) can make pytest exit 0 with failures."""
    code, line, _ = _drive(monkeypatch, capsys, tmp_path, pytest_out=out, pytest_rc=0)
    assert code == 1 and line.startswith("CHECK-ALL: FAIL"), line


def test_summary_is_the_last_matching_line_not_an_earlier_echo(monkeypatch, capsys, tmp_path):
    out = "test output: 99 passed in 1s ===\n=== 1 failed in 0.2s ===\n"
    code, line, _ = _drive(monkeypatch, capsys, tmp_path, pytest_out=out, pytest_rc=1)
    assert code == 1 and "tests=0 passed/0 skipped/1 failed" in line


@pytest.mark.parametrize(
    "ac_rc,ac_out,ac_err",
    [
        (1, "ERROR PIN_DRIFT              Rec/1: drift\nATRIUM-CHECK: FAIL errors=1\n", ""),
        (2, "", "ATRIUM-CHECK: ERROR registry: 'owner' must be 'Atrium'\n"),        # unusable registry
        (1, "", "Traceback (most recent call last):\nModuleNotFoundError: atrium_check\n"),  # crashed
        (1, "", ""),                                                               # died silently
    ],
)
def test_atrium_check_not_green_is_fail(monkeypatch, capsys, tmp_path, ac_rc, ac_out, ac_err):
    code, line, _ = _drive(monkeypatch, capsys, tmp_path, ac_rc=ac_rc, ac_out=ac_out, ac_err=ac_err)
    assert code == 1 and line.startswith("CHECK-ALL: FAIL") and "atrium_check=FAIL" in line


def test_first_error_is_named_on_the_final_line(monkeypatch, capsys, tmp_path):
    out = "ERROR PIN_DRIFT              Rec/1: a:b sha 1 != 2\nERROR FILE_MISSING Fam/1: x\nATRIUM-CHECK: FAIL errors=2\n"
    _, line, _ = _drive(monkeypatch, capsys, tmp_path, ac_rc=1, ac_out=out)
    assert line.endswith("first_error=PIN_DRIFT Rec/1")
    assert "atrium_check=FAIL (FAIL errors=2)" in line


def test_atrium_check_launch_failure_raises_and_prints_no_verdict(monkeypatch, capsys, tmp_path):
    repo = _member(tmp_path)

    class FakePopen:
        def __init__(self, *a, **k):
            self.stdout = iter(["5 passed in 0.1s\n"])

        def wait(self):
            return 0

    def fake_run(cmd, **k):
        if cmd[0] == "git":
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise OSError("python vanished")

    monkeypatch.setattr(check_all.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(check_all.subprocess, "run", fake_run)
    monkeypatch.setattr(check_all, "_have", lambda k, n: True)
    with pytest.raises(OSError):
        check_all.main(["--repo-dir", str(repo)])
    assert "CHECK-ALL: PASS" not in capsys.readouterr().out


def test_pytest_launch_failure_raises_and_prints_no_verdict(monkeypatch, capsys, tmp_path):
    repo = _member(tmp_path)

    def broken_popen(*a, **k):
        raise OSError("no interpreter")

    monkeypatch.setattr(check_all.subprocess, "Popen", broken_popen)
    monkeypatch.setattr(check_all.subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(cmd, 0, "", ""))
    with pytest.raises(OSError):
        check_all.main(["--repo-dir", str(repo)])
    assert "CHECK-ALL:" not in capsys.readouterr().out


def test_skip_atrium_check_is_incomplete_never_pass(monkeypatch, capsys, tmp_path):
    code, line, _ = _drive(monkeypatch, capsys, tmp_path, extra=["--skip-atrium-check"])
    assert code == 3 and line.startswith("CHECK-ALL: INCOMPLETE") and "atrium_check=SKIPPED" in line


def test_skip_atrium_check_with_failing_tests_is_fail(monkeypatch, capsys, tmp_path):
    code, line, _ = _drive(monkeypatch, capsys, tmp_path, pytest_out="1 failed in 0.1s\n", pytest_rc=1,
                           extra=["--skip-atrium-check"])
    assert code == 1 and line.startswith("CHECK-ALL: FAIL")


def test_missing_hard_dependency_is_incomplete(monkeypatch, capsys, tmp_path):
    code, line, out = _drive(monkeypatch, capsys, tmp_path, name="obsidian", have=lambda k, n: n != "tesseract")
    assert code == 3 and line.startswith("CHECK-ALL: INCOMPLETE") and "missing=tesseract" in line
    assert "NOTE: could not run here" in out


def test_missing_hard_dependency_and_failing_tests_is_fail_with_a_caveat(monkeypatch, capsys, tmp_path):
    code, line, out = _drive(monkeypatch, capsys, tmp_path, name="obsidian", have=lambda k, n: n != "spacy",
                             pytest_out="1 failed, 2 passed in 0.1s\n", pytest_rc=1)
    assert code == 1 and line.startswith("CHECK-ALL: FAIL")
    assert "re-run on a machine that has them" in out


def test_missing_soft_dependency_still_passes_with_a_note(monkeypatch, capsys, tmp_path):
    code, line, out = _drive(monkeypatch, capsys, tmp_path, name="sequoia", have=lambda k, n: n != "z3")
    assert code == 0 and line.startswith("CHECK-ALL: PASS")
    assert "NOTE: optional, not installed: z3" in out


def test_strict_pins_omits_the_allow_unpinned_flag(monkeypatch, capsys, tmp_path):
    seen = []
    repo = _member(tmp_path)

    class FakePopen:
        def __init__(self, *a, **k):
            self.stdout = iter(["1 passed in 0.1s\n"])

        def wait(self):
            return 0

    def fake_run(cmd, **k):
        if cmd[0] != "git":
            seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "ATRIUM-CHECK: PASS\n", "")

    monkeypatch.setattr(check_all.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(check_all.subprocess, "run", fake_run)
    monkeypatch.setattr(check_all, "_have", lambda k, n: True)
    check_all.main(["--repo-dir", str(repo), "--strict-pins"])
    check_all.main(["--repo-dir", str(repo)])
    capsys.readouterr()
    assert "--allow-unpinned-head" not in seen[0] and "--allow-unpinned-head" in seen[1]


# ----------------------------------------------------------------- start-up refusals (exit 2)


def test_folder_that_is_not_a_member_exits_2(monkeypatch, capsys, tmp_path):
    d = tmp_path / "Conclave"
    d.mkdir()
    (d / "pyproject.toml").write_text("", encoding="utf-8")
    assert check_all.main(["--repo-dir", str(d)]) == 2
    io = capsys.readouterr()
    assert "CHECK-ALL: ERROR" in io.err and "PASS" not in io.out


def test_member_folder_without_pyproject_exits_2(monkeypatch, capsys, tmp_path):
    d = tmp_path / "locutus"
    d.mkdir()
    assert check_all.main(["--repo-dir", str(d)]) == 2
    assert "PASS" not in capsys.readouterr().out


def test_member_name_is_matched_case_insensitively(monkeypatch, capsys, tmp_path):
    rc, line, _ = _drive(monkeypatch, capsys, tmp_path, name="Sequoia")
    assert rc == 0 and "repo=sequoia" in line


@pytest.mark.parametrize("folder,expected", [("LOCUTUS", "locutus"), ("Atrium", "atrium"), ("conclave", None), ("", None)])
def test_find_repo_name(folder, expected, tmp_path):
    assert check_all.find_repo_name(tmp_path / folder if folder else Path("")) == expected


# ----------------------------------------------------------------- _counts parser


@pytest.mark.parametrize(
    "text,expected",
    [
        ("12607 passed, 3 skipped, 5 xfailed in 600s", {"passed": 12607, "skipped": 3, "xfailed": 5}),
        ("===== 1 failed, 2 errors in 1.0s =====", {"failed": 1, "error": 2}),
        ("1 passed, 1 xpassed in 0.1s", {"passed": 1, "xpassed": 1}),
        ("5 passed, 2 warnings in 0.1s", {"passed": 5}),
        ("collected 5 items", {}),
        ("", {}),
        ("5 passed", {}),  # no ' in ' and no '=': not a pytest summary
    ],
)
def test_counts_parser(text, expected):
    assert check_all._counts(text) == expected
