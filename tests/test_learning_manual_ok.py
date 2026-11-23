"""Bulk manual OKs (LF-3 = Decision 41). Synthetic data only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atrium_learning import LearningFolder, LearningFolderError
from atrium_learning.folder import manual_oks, record_manual_ok
from atrium_learning import manual_ok as manual_ok_mod
from atrium_learning.manual_ok import DECISION_41_LIST_SHA256, DECISION_41_WORDS, list_sha256, main
from test_learning_folder import item, make_aim

WORDS = "Yes, these two synthetic manuals are fine"  # any answer other than Decision 41's


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
    assert rows[0]["list_sha256"] == list_sha256((tmp_path / "manuals.txt").read_bytes())
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


@pytest.mark.parametrize(
    "words",
    [DECISION_41_WORDS, "they're all approved as of now, and revisit in 5 mo.", "THEY'RE ALL APPROVED AS OF NOW AND REVISIT IN 5 MO"],
)
def test_decision_41_words_refused_on_any_other_list(root, tmp_path, capsys, words):
    """Review of #65: Jake's 11/23 words must not record an OK for a manual first used later."""
    args = ["--list", str(lst(tmp_path, "LATER MANUAL [123]")), "--by", "jake", "--words", words,
            "--revisit", "2027-04-23", "--root", str(root)]
    assert main(args) == 1
    out = capsys.readouterr().out
    assert "own OK with its own words" in out and out.strip().endswith("MANUAL-OK: FAIL")
    assert manual_oks(root) == set()
    assert not (root / "learning" / "manual_oks.jsonl").exists()


def test_decision_41_words_accepted_on_the_pinned_list_crlf_too(root, tmp_path, monkeypatch, capsys):
    p = lst(tmp_path, "A manual [aaa]")
    monkeypatch.setattr(manual_ok_mod, "DECISION_41_LIST_SHA256", list_sha256(p.read_bytes()))
    p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))  # a Windows copy of the same list
    assert main(["--list", str(p), "--by", "jake", "--words", DECISION_41_WORDS, "--root", str(root)]) == 0
    row = json.loads((root / "learning" / "manual_oks.jsonl").read_text().splitlines()[0])
    assert row["words"] == DECISION_41_WORDS and row["list_sha256"] == manual_ok_mod.DECISION_41_LIST_SHA256
    assert row["manual"] == "A manual [aaa]"


def test_withdraw_with_decision_41_words_is_not_blocked(root, tmp_path):
    record_manual_ok(root, "LATER MANUAL [123]", "jake", words=WORDS)
    args = ["--list", str(lst(tmp_path, "LATER MANUAL [123]")), "--by", "jake", "--withdraw",
            "--words", DECISION_41_WORDS, "--root", str(root)]
    assert main(args) == 0 and manual_oks(root) == set()


def test_pinned_hash_shape_and_bad_list_sha_refused(root):
    assert len(DECISION_41_LIST_SHA256) == 64 and int(DECISION_41_LIST_SHA256, 16) >= 0
    with pytest.raises(LearningFolderError, match="list_sha256"):
        record_manual_ok(root, "A [a]", "jake", words=WORDS, list_sha256="nothex")
