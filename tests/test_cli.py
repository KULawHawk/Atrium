"""CLI tests for ``python -m atrium_check``."""

from __future__ import annotations

import json
import subprocess

import pytest

from atrium_check import __main__ as cli
from atrium_check.check import load_registry

REAL_GIT_HEAD = cli._git_head
PINS = {"Alpha": "aaaaaaa", "beta": "bbbbbbb"}  # the fixture suite's pinned commits, by checkout folder


@pytest.fixture(autouse=True)
def heads_at_pins(monkeypatch):
    """The fake suite's folders are not git checkouts; report them at their pins."""
    monkeypatch.setattr(cli, "_git_head", lambda p: PINS.get(p.name))


def test_check_head_not_pinned(suite, capsys, monkeypatch):
    _, path, root = suite
    monkeypatch.setattr(cli, "_git_head", lambda p: {"Alpha": "aaaaaaa", "beta": "eeeeeee"}[p.name])
    base = ["check", "--registry", str(path), "--repos-root", str(root)]
    assert cli.main(base) == 1
    assert "HEAD_NOT_PINNED" in capsys.readouterr().out
    assert cli.main(base + ["--allow-unpinned-head"]) == 0
    assert "WARN  HEAD_NOT_PINNED" in capsys.readouterr().out
    monkeypatch.setattr(cli, "_git_head", lambda p: None)
    assert cli.main(base) == 1
    assert "ERROR HEAD_UNKNOWN" in capsys.readouterr().out
    assert cli.main(base + ["--allow-unpinned-head"]) == 0
    assert "WARN  HEAD_UNKNOWN" in capsys.readouterr().out


def test_check_pass_text(suite, capsys):
    _, path, root = suite
    assert cli.main(["check", "--registry", str(path), "--repos-root", str(root)]) == 0
    assert capsys.readouterr().out.strip().startswith("ATRIUM-CHECK: PASS")


def test_check_fail_json_and_repo_override(suite, capsys, tmp_path):
    _, path, root = suite
    rc = cli.main(["check", "--registry", str(path), "--repo", f"alpha={root / 'Alpha'}", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert out["members_skipped"] == ["beta"]
    assert [f["code"] for f in out["findings"]] == ["MEMBER_MISSING"]


def test_check_only_and_strict(suite, capsys):
    _, path, root = suite
    p = root / "beta/vendor_alpha/contracts/fam.v1.json"
    p.write_text("{}", encoding="utf-8")
    args = ["check", "--registry", str(path), "--repos-root", str(root)]
    assert cli.main(args) == 0
    assert cli.main(args + ["--strict"]) == 1
    assert cli.main(args + ["--only", "alpha"]) == 0
    assert "NOT_EXAMINED=beta" in capsys.readouterr().out


@pytest.mark.parametrize("bad", [["--repo", "noequals"], ["--repo", "=x"], ["--registry", "/nonexistent.json"]])
def test_unusable_input_exits_2(suite, capsys, bad):
    _, path, root = suite
    args = ["check", "--registry", str(path)] + bad
    assert cli.main(args) == 2
    assert "ATRIUM-CHECK: ERROR" in capsys.readouterr().err


def test_repin_plan_then_apply(suite, capsys, monkeypatch):
    _, path, root = suite
    monkeypatch.setattr(cli, "_git_head", lambda p: "ddddddd" if p.name == "Alpha" else "bbbbbbb")
    p = root / "Alpha/contracts/rec.v1.schema.json"
    p.write_text(p.read_text() + " ", encoding="utf-8")
    base = ["repin", "--registry", str(path), "--repos-root", str(root)]
    before = path.read_text()
    assert cli.main(base) == 0
    out = capsys.readouterr().out
    assert "PLAN  Rec/1:" in out and "members.alpha.pinned_commit: aaaaaaa -> ddddddd" in out and "members.beta" not in out
    assert "plan only" in out
    assert path.read_text() == before
    assert cli.main(base + ["--apply"]) == 0
    assert "wrote" in capsys.readouterr().out
    reg = load_registry(path)
    assert reg["members"]["alpha"]["pinned_commit"] == "ddddddd"
    assert cli.main(base) == 0
    assert "nothing to change" in capsys.readouterr().out
    assert cli.main(["check", "--registry", str(path), "--repos-root", str(root)]) == 0


def test_repin_unusable_registry(tmp_path, capsys):
    assert cli.main(["repin", "--registry", str(tmp_path / "x.json")]) == 2


def test_git_head(tmp_path):
    assert REAL_GIT_HEAD(tmp_path / "missing") is None
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    assert REAL_GIT_HEAD(repo) is None  # no commit yet
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x"],
        check=True,
    )
    head = REAL_GIT_HEAD(repo)
    assert head is not None and len(head) >= 7


def test_git_missing_binary(monkeypatch):
    def boom(*a, **k):
        raise OSError("no git")

    monkeypatch.setattr(cli.subprocess, "run", boom)
    assert REAL_GIT_HEAD(cli.DEFAULT_REGISTRY.parent) is None


def test_git_empty_output(monkeypatch):
    class R:
        stdout = "\n"

    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: R())
    assert REAL_GIT_HEAD(cli.DEFAULT_REGISTRY.parent) is None


def test_default_registry_is_the_committed_one():
    assert cli.DEFAULT_REGISTRY.is_file()
    assert load_registry(cli.DEFAULT_REGISTRY)["owner"] == "Atrium"
