"""Copy approved learning-folder items to the place the Claude connector reads (design §5; LF-1 A, LF-2 A).

Runs on the PC. For each aim:

1. every approved item is re-checked (sha256 + its class's gate; class P needs the aim's gate, Decision 38 = A);
2. the passing items are staged in ``<root>\\learning\\_outbox\\<run>\\<aim>\\`` with the aim's manifest;
3. the patient-run guard runs on that staging folder, and only on ``PATIENT-RUN-GUARD: PASS`` is it copied
   to ``<dest>\\<aim>\\`` (the project share's ``learning/<aim>/``).

Class M (manual-derived) items are NOT copied unless ``--include-manual`` is given: LF-3 is not decided, so the
copy carries synthetic, public and approved de-identified items only (LF-3 option D, coordinator 11/23).

Any failure stops that aim, loudly; the other aims still run, and the final line is FAIL. Nothing is deleted
(staging stays for the record). Standard library only.

    python -m atrium_learning.copyout --dest <share>\\learning --guard <pc-items>\\patient_run_guard.py \\
        [--root <install root>] [--gate obsidian=obsidian.learning:gate] [--aim readers-print ...]
"""

from __future__ import annotations

import argparse
import importlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from atrium_learning.folder import MANIFEST, Gate, LearningFolder, LearningFolderError, find_install_root

GuardRunner = Callable[[Path], tuple[bool, str]]


def run_guard(guard: Path) -> GuardRunner:
    """The patient-run guard as a callable: PASS only on exit 0 AND a ``PATIENT-RUN-GUARD: PASS`` line."""

    def _run(folder: Path) -> tuple[bool, str]:
        proc = subprocess.run(
            [sys.executable, "-I", str(guard), str(folder)], capture_output=True, text=True, check=False
        )
        last = (proc.stdout.strip().splitlines() or [""])[-1]
        return proc.returncode == 0 and last.startswith("PATIENT-RUN-GUARD: PASS"), last

    return _run


def load_gate(spec: str) -> Gate:
    """``module:function`` -> the callable. Refuses loudly if it cannot be found."""
    mod, _, name = spec.partition(":")
    if not mod or not name:
        raise LearningFolderError(f"gate {spec!r} is not module:function")
    try:
        gate = getattr(importlib.import_module(mod), name)
    except (ImportError, AttributeError):
        raise LearningFolderError(f"gate {spec!r} could not be loaded") from None
    if not callable(gate):
        raise LearningFolderError(f"gate {spec!r} is not callable")
    return gate


def copy_out(
    root: Path,
    dest: Path,
    guard: GuardRunner,
    gates: Mapping[str, Gate],
    aims: Sequence[str] | None = None,
    run_id: str | None = None,
    include_manual: bool = False,
) -> dict[str, str]:
    """Returns ``{aim: "PASS n=<items>" | "FAIL <why>"}``."""
    learning = Path(root) / "learning"
    if not learning.is_dir():
        raise LearningFolderError(f"{learning} does not exist; run the AdAstra installer")
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if aims is None:
        aims = sorted(p.name for p in learning.iterdir() if p.is_dir() and not p.name.startswith("_"))
    result: dict[str, str] = {}
    for aim in aims:
        try:
            folder = LearningFolder(root, aim)
            items = folder.items_for_copy(gates.get(aim), ("S", "M", "P") if include_manual else ("S", "P"))
            stage = learning / "_outbox" / run_id / aim
            stage.mkdir(parents=True, exist_ok=False)
            for path in items:
                shutil.copyfile(path, stage / path.name)
            shutil.copyfile(folder.dir / MANIFEST, stage / MANIFEST)
            ok, line = guard(stage)
            if not ok:
                raise LearningFolderError(f"patient-run guard did not pass: {line or 'no output'}")
            target = Path(dest) / aim
            target.mkdir(parents=True, exist_ok=True)
            for path in sorted(stage.iterdir()):
                shutil.copyfile(path, target / path.name)
            result[aim] = f"PASS n={len(items)}"
        except LearningFolderError as exc:
            result[aim] = f"FAIL {exc}"
    report = learning / "_outbox" / f"{run_id}.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"run": run_id, "aims": result}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="atrium_learning.copyout", description=__doc__.splitlines()[0])
    ap.add_argument("--dest", required=True, type=Path, help="where the connector reads (one subfolder per aim)")
    ap.add_argument("--guard", required=True, type=Path, help="path to pc-items/patient_run_guard.py")
    ap.add_argument("--root", type=Path, help="install root (default: from adastra.json)")
    ap.add_argument("--gate", action="append", default=[], help="aim=module:function for an aim's own gate")
    ap.add_argument("--aim", action="append", help="only these aims (default: every aim folder)")
    ap.add_argument("--include-manual", action="store_true", help="also copy class M items (only after Jake's LF-3)")
    args = ap.parse_args(argv)
    try:
        if not args.guard.is_file():
            raise LearningFolderError(f"patient-run guard not found at {args.guard}")
        gates: dict[str, Gate] = {}
        for spec in args.gate:
            aim, sep, target = spec.partition("=")
            if not sep:
                raise LearningFolderError(f"--gate {spec!r} is not aim=module:function")
            gates[aim] = load_gate(target)
        root = args.root or find_install_root()
        result = copy_out(root, args.dest, run_guard(args.guard), gates, args.aim, include_manual=args.include_manual)
    except LearningFolderError as exc:
        print(str(exc))
        print("LEARNING-COPY: FAIL")
        return 1
    for aim, verdict in result.items():
        print(f"{aim}: {verdict}")
    failed = [a for a, v in result.items() if v.startswith("FAIL")]
    print(f"LEARNING-COPY: {'FAIL' if failed else 'PASS'} aims={len(result)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover - thin entry point; main() is tested directly
    sys.exit(main())
