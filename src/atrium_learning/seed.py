"""Fill learning folders with synthetic and public items from a list (design §1, item 1 of the follow-up list).

The list is a tab-separated file, one item per line, ``#`` lines ignored::

    <aim>\\t<class>\\t<source line>\\t<path to the file>

Only class ``S`` is accepted here: manual-derived items wait for Jake's LF-3, and real-report items enter
only through their aim's own gate and a human check (Decision 38 = A). An item already approved is reported
as ``ALREADY`` (never silently skipped); every other problem is ``FAIL`` and the last line says so.

    python -m atrium_learning.seed --list seed_list.tsv [--root <install root>] [--by seed:kit-2026-11-23]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from atrium_learning.folder import LearningFolder, LearningFolderError, _sha256, find_install_root


def seed(root: Path, list_path: Path, by: str) -> list[tuple[int, str, str]]:
    """Returns ``(line number, verdict, detail)`` per item; verdict is ADDED, ALREADY or FAIL."""
    out: list[tuple[int, str, str]] = []
    for n, raw in enumerate(Path(list_path).read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) != 4:
            out.append((n, "FAIL", "needs 4 tab-separated fields: aim, class, source, path"))
            continue
        aim, cls, source, path = (p.strip() for p in parts)
        if cls != "S":
            out.append((n, "FAIL", f"class {cls!r}: only synthetic/public (S) items may be seeded"))
            continue
        try:
            folder = LearningFolder(root, aim)
            item = Path(path)
            if item.is_file() and folder.state().get(_sha256(item), {}).get("event") == "added":
                out.append((n, "ALREADY", f"{aim} {_sha256(item)[:12]}"))
                continue
            sha = folder.add(item, "S", source, by)
            out.append((n, "ADDED", f"{aim} {sha[:12]}"))
        except LearningFolderError as exc:
            out.append((n, "FAIL", str(exc)))
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="atrium_learning.seed", description=__doc__.splitlines()[0])
    ap.add_argument("--list", required=True, type=Path)
    ap.add_argument("--root", type=Path)
    ap.add_argument("--by", default="seed")
    args = ap.parse_args(argv)
    try:
        if not args.list.is_file():
            raise LearningFolderError(f"list not found: {args.list}")
        rows = seed(args.root or find_install_root(), args.list, args.by)
    except LearningFolderError as exc:
        print(str(exc))
        print("LEARNING-SEED: FAIL")
        return 1
    for n, verdict, detail in rows:
        print(f"line {n}: {verdict} {detail}")
    counts = {v: sum(1 for _, x, _ in rows if x == v) for v in ("ADDED", "ALREADY", "FAIL")}
    verdict = "FAIL" if counts["FAIL"] or not rows else "PASS"
    print(f"LEARNING-SEED: {verdict} added={counts['ADDED']} already={counts['ALREADY']} failed={counts['FAIL']}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover - thin entry point; main() is tested directly
    sys.exit(main())
