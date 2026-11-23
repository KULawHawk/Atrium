"""Seeding learning folders with synthetic/public items. Synthetic data only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atrium_learning import LearningFolder
from atrium_learning.seed import main, seed
from test_learning_folder import item, make_aim


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "root"
    make_aim(r, "handwriting")
    return r


def write_list(tmp_path: Path, lines: list[str]) -> Path:
    p = tmp_path / "seed.tsv"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_seed_adds_then_reports_already(root, tmp_path):
    a = item(tmp_path, "a.png", "synthetic page a")
    lst = write_list(tmp_path, ["# comment", "", f"handwriting\tS\tpublic: NIST SD19\t{a}"])
    assert seed(root, lst, "seed:test")[0][1] == "ADDED"
    assert seed(root, lst, "seed:test")[0][1] == "ALREADY"
    assert LearningFolder(root, "handwriting").state().popitem()[1]["added_by"] == "seed:test"


def test_seed_refuses_non_s_and_bad_lines(root, tmp_path):
    a = item(tmp_path)
    lst = write_list(
        tmp_path,
        [
            f"handwriting\tM\tWISC-V\t{a}",
            f"handwriting\tP\tcopy\t{a}",
            "too\tfew",
            f"no-such-aim\tS\tsynthetic\t{a}",
            f"handwriting\tS\tsynthetic\t{tmp_path / 'missing.png'}",
        ],
    )
    assert [v for _, v, _ in seed(root, lst, "seed")] == ["FAIL"] * 5


def test_main_pass_and_fail(root, tmp_path, capsys):
    a = item(tmp_path, "a.png", "x")
    good = write_list(tmp_path, [f"handwriting\tS\tsynthetic\t{a}"])
    assert main(["--list", str(good), "--root", str(root)]) == 0
    assert capsys.readouterr().out.strip().endswith("LEARNING-SEED: PASS added=1 already=0 failed=0")
    bad = tmp_path / "bad.tsv"
    bad.write_text(f"handwriting\tM\tx\t{a}\n")
    assert main(["--list", str(bad), "--root", str(root)]) == 1


def test_main_empty_list_is_fail(root, tmp_path, capsys):
    empty = write_list(tmp_path, ["# nothing"])
    assert main(["--list", str(empty), "--root", str(root)]) == 1
    assert "LEARNING-SEED: FAIL added=0" in capsys.readouterr().out


def test_main_refusals(tmp_path, monkeypatch, capsys):
    assert main(["--list", str(tmp_path / "nope.tsv")]) == 1
    lst = write_list(tmp_path, ["x"])
    monkeypatch.setattr("sys.prefix", str(tmp_path))
    assert main(["--list", str(lst)]) == 1
    assert capsys.readouterr().out.strip().endswith("LEARNING-SEED: FAIL")


def test_main_root_from_adastra_json(root, tmp_path, monkeypatch):
    (tmp_path / "adastra.json").write_text(json.dumps({"install_root": str(root)}))
    monkeypatch.setattr("sys.prefix", str(tmp_path))
    a = item(tmp_path, "a.png", "y")
    assert main(["--list", str(write_list(tmp_path, [f"handwriting\tS\tsynthetic\t{a}"]))]) == 0
