"""Record Jake's OK for licensed manuals in one go (LF-3 = Decision 41, Jake 6:29 AM CT 11/23/2026).

    python -m atrium_learning.manual_ok --list MANUALS_IN_USE_2026-11-23.txt --by jake \\
        --words "They're all approved as of now and revisit in 5 mo" --revisit 2027-04-23 [--root <install root>]

The list holds one manual id per line (``<file stem> [<first 12 of sha256>]``; ``#`` lines ignored). Class M
items use that exact id as their ``source``. A manual already OK'd is reported ``ALREADY`` and not written again.
``--withdraw`` withdraws instead, which moves that manual's items aside in every aim (nothing deleted).
Prints ``MANUAL-OK: PASS/FAIL``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from atrium_learning.folder import LearningFolderError, find_install_root, manual_oks, record_manual_ok


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
        ids = [x.strip() for x in args.list.read_text(encoding="utf-8").splitlines()]
        ids = [x for x in ids if x and not x.startswith("#")]
        if not ids:
            raise LearningFolderError("the list names no manual")
        if not args.withdraw and not args.words:
            raise LearningFolderError("--words (Jake's answer, verbatim) is required to record an OK")
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
            moved += len(record_manual_ok(root, manual, args.by, not args.withdraw, args.words, args.revisit))
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
