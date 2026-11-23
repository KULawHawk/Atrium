"""Bulk manual OKs (LF-3 = Decision 41). Synthetic data only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atrium_learning import LearningFolder, LearningFolderError
from atrium_learning.folder import manual_oks, record_manual_ok
from atrium_learning.manual_ok import main
from test_learning_folder import item, make_aim

WORDS = "They're all approved as of now and revisit in 5 mo"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "root"
    make_aim(r, "readers-print")
    return r


def lst(tmp_path: Path, *ids: str) -> Path:
    p = tmp_path / "manuals.txt"
    p.write_text("# header\n\n" + "\n".join(ids) + "\n", encoding="utf-8")
    return p


def test_bulk_ok_records_words_and_revisit(root, tmp_path, capsys):
    args = ["--list", str(lst(tmp_path, "A manual [aaa]", "B manual [bbb]")), "--by", "jake", "--words", WORDS,
            "--revisit", "2027-04-23", "--root", str(root)]
    assert main(args) == 0
    assert capsys.readouterr().out.strip().endswith("MANUAL-OK: PASS written=2 already=0 items_moved_aside=0")
    rows = [json.loads(x) for x in (root / "learning" / "manual_oks.jsonl").read_text().splitlines()]
    assert rows[0]["words"] == WORDS and rows[0]["revisit"] == "2027-04-23"
    assert manual_oks(root) == {"A manual [aaa]", "B manual [bbb]"}
    assert main(args) == 0
    assert "already=2" in capsys.readouterr().out


def test_withdraw_moves_items_aside(root, tmp_path, capsys):
    record_manual_ok(root, "A manual [aaa]", "jake", words=WORDS)
    f = LearningFolder(root, "readers-print")
    f.add(item(tmp_path), "M", "A manual [aaa]", "jake")
    args = ["--list", str(lst(tmp_path, "A manual [aaa]", "Z never [zzz]")), "--by", "jake", "--withdraw",
            "--root", str(root)]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "ALREADY withdrawn Z never [zzz]" in out and "items_moved_aside=1" in out
    assert f.approved() == []


@pytest.mark.parametrize(
    "extra,ids",
    [([], ("A [a]",)), (["--words", WORDS], ()), (["--words", WORDS, "--revisit", "soon"], ("A [a]",))],
)
def test_refusals(root, tmp_path, capsys, extra, ids):
    args = ["--list", str(lst(tmp_path, *ids)), "--by", "jake", "--root", str(root), *extra]
    assert main(args) == 1
    assert capsys.readouterr().out.strip().endswith("MANUAL-OK: FAIL")


def test_missing_list_and_root_from_marker(tmp_path, monkeypatch, root):
    assert main(["--list", str(tmp_path / "none.txt"), "--by", "jake", "--words", WORDS]) == 1
    (tmp_path / "adastra.json").write_text(json.dumps({"install_root": str(root)}))
    monkeypatch.setattr("sys.prefix", str(tmp_path))
    assert main(["--list", str(lst(tmp_path, "A [a]")), "--by", "jake", "--words", WORDS]) == 0


def test_bad_words_refused(root):
    with pytest.raises(LearningFolderError):
        record_manual_ok(root, "A [a]", "jake", words="two\nlines")
