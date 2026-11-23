"""Record Jake's OK for licensed manuals in one go (LF-3 = Decision 41, Jake 6:29 AM CT 11/23/2026).

    python -m atrium_learning.manual_ok --list MANUALS_IN_USE_2026-11-23.txt --by jake \\
        --words "They're all approved as of now and revisit in 5 mo" --revisit 2027-04-23 [--root <install root>]

The list holds one manual id per line (``<file stem> [<first 12 of sha256>]``; ``#`` lines ignored). Class M
items use that exact id as their ``source``. A manual already OK'd is reported ``ALREADY`` and not written again.
``--withdraw`` withdraws instead, which moves that manual's items aside in every aim (nothing deleted).
Prints ``MANUAL-OK: PASS/FAIL``.

**Decision 41's words cover one list only.** Jake's 11/23 answer approved the manuals in use *that day*, so an
OK recorded with those words is refused unless the list is byte-for-byte ``MANUALS_IN_USE_2026-11-23.txt``
(sha256 pinned below; CRLF line endings are read as LF so a Windows copy still matches). The words are compared
after folding case, spacing and punctuation, so a re-typed copy of them cannot slip past either. A manual first
used later needs its own OK with its own recorded words. Every OK line carries ``list_sha256`` so the record
shows which list it came from (review of Atrium #65).

What this check is and is not: it stops *accidental* reuse of Decision 41's words for a later manual. It does
not prove that any recorded words are Jake's. Someone who rewords his answer can still record an OK on another
list; the record then shows those reworded words and the list's sha256, so the mismatch is visible on review.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path
from typing import Sequence

from atrium_learning.folder import LearningFolderError, find_install_root, manual_oks, record_manual_ok

#: Jake's answer to Decision 41 (LF-3), 6:29 AM CT 11/23/2026, verbatim.
DECISION_41_WORDS = "They're all approved as of now and revisit in 5 mo"
#: sha256 of learning-folders/MANUALS_IN_USE_2026-11-23.txt (LF line endings): the only list those words cover.
DECISION_41_LIST_SHA256 = "f6e30875d9e7c0668126420f75ebc54c31bfda372c0af3a4b4ebc2d49d601fcb"


def _fold(words: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", words.casefold())


def list_sha256(data: bytes) -> str:
    """sha256 of a manual list, with CRLF read as LF."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="atrium_learning.manual_ok", description=__doc__.splitlines()[0])
    ap.add_argument("--list", required=True, type=Path)
    ap.add_argument("--by", required=True)
    ap.add_argument("--words", help="Jake's answer, verbatim")
    ap.add_argument("--revisit", help="YYYY-MM-DD")
    ap.add_argument("--withdraw", action="store_true")
    ap.add_argument("--root", type=Path)
    args = ap.parse_args(argv)
    try:
        if not args.list.is_file():
            raise LearningFolderError(f"list not found: {args.list}")
        data = args.list.read_bytes()
        digest = list_sha256(data)
        ids = [x.strip() for x in data.decode("utf-8").splitlines()]
        ids = [x for x in ids if x and not x.startswith("#")]
        if not ids:
            raise LearningFolderError("the list names no manual")
        if not args.withdraw and not args.words:
            raise LearningFolderError("--words (Jake's answer, verbatim) is required to record an OK")
        if not args.withdraw and _fold(args.words) == _fold(DECISION_41_WORDS) and digest != DECISION_41_LIST_SHA256:
            raise LearningFolderError(
                f"Decision 41's words cover only MANUALS_IN_USE_2026-11-23.txt (sha256 {DECISION_41_LIST_SHA256[:12]}); "
                f"this list is {digest[:12]}. A manual first used later needs its own OK with its own words"
            )
        root = args.root or find_install_root()
        current = manual_oks(root)
        written = already = moved = 0
        for manual in ids:
            if not args.withdraw and manual in current:
                print(f"ALREADY {manual}")
                already += 1
                continue
            if args.withdraw and manual not in current:
                print(f"ALREADY withdrawn {manual}")
                already += 1
                continue
            moved += len(record_manual_ok(root, manual, args.by, not args.withdraw, args.words, args.revisit, digest))
            print(f"{'WITHDRAWN' if args.withdraw else 'OK'} {manual}")
            written += 1
    except LearningFolderError as exc:
        print(str(exc))
        print("MANUAL-OK: FAIL")
        return 1
    print(f"MANUAL-OK: PASS written={written} already={already} items_moved_aside={moved}")
    return 0


if __name__ == "__main__":  # pragma: no cover - thin entry point; main() is tested directly
    sys.exit(main())
