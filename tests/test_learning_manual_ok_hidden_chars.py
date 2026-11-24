"""A withdrawal must reach the manual it names (hunt 2026-11-24). Synthetic data only.

On main 3febbe8 a list saved with a UTF-8 byte-order mark (PowerShell 5.1 ``Out-File -Encoding utf8``) carried
the mark into the first manual id, so ``--withdraw`` printed ``ALREADY withdrawn`` and ``MANUAL-OK: PASS`` while
the OK stayed on record and that manual's items kept going out to the connector.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atrium_learning import LearningFolder
from atrium_learning.folder import manual_oks, record_manual_ok
from atrium_learning.manual_ok import main
from test_learning_folder import item, make_aim

MANUAL = "A manual [aaa]"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "root"
    make_aim(r, "readers-print")
    record_manual_ok(r, MANUAL, "jake", words="yes for this one")
    LearningFolder(r, "readers-print").add(item(tmp_path), "M", MANUAL, "jake")
    return r


def _withdraw(root: Path, tmp_path: Path, raw: bytes) -> int:
    p = tmp_path / "withdraw.txt"
    p.write_bytes(raw)
    return main(["--list", str(p), "--by", "jake", "--withdraw", "--root", str(root)])


@pytest.mark.parametrize("raw", [
    b"\xef\xbb\xbf" + MANUAL.encode() + b"\r\n",
    b"\xef\xbb\xbf# header\r\n" + MANUAL.encode() + b"\r\n",
    b"  " + MANUAL.encode() + b" \t\r\n",  # outer spaces and a trailing tab are not part of the id
])
def test_a_byte_order_mark_does_not_stop_a_withdrawal(root, tmp_path, capsys, raw):
    assert _withdraw(root, tmp_path, raw) == 0
    out = capsys.readouterr().out
    assert f"WITHDRAWN {MANUAL}" in out and "items_moved_aside=1" in out
    assert manual_oks(root) == set()
    assert LearningFolder(root, "readers-print").items_for_copy() == []


@pytest.mark.parametrize("hidden", ["​", "­", "⁠", "﻿", "\x07", "‮"])
def test_an_id_with_an_invisible_character_is_refused(root, tmp_path, capsys, hidden):
    assert _withdraw(root, tmp_path, (MANUAL[:3] + hidden + MANUAL[3:] + "\n").encode()) == 1
    out = capsys.readouterr().out
    assert "line 1 holds an invisible or control character" in out and out.strip().endswith("MANUAL-OK: FAIL")
    assert manual_oks(root) == {MANUAL}  # nothing recorded either way


def test_a_list_that_is_not_utf8_is_refused(root, tmp_path, capsys):
    assert _withdraw(root, tmp_path, b"\xff\xfeA\x00") == 1
    assert "not UTF-8" in capsys.readouterr().out
