"""Copy approved learning-folder items to the place the Claude connector reads (design §5; LF-1 A, LF-2 A).

Runs on the PC. For each aim:

1. every approved item is re-checked (sha256 + its class's gate; class P needs the aim's gate, Decision 38 = A);
2. the passing items are staged in ``<root>\\learning\\_outbox\\<run>\\<aim>\\`` with their manifest rows only;
3. the patient-run guard runs on that staging folder, and only on ``PATIENT-RUN-GUARD: PASS`` is it copied
   to ``<dest>\\<aim>\\`` (the project share's ``learning/<aim>/``).

The guard checks for patient-run folders, links and protected patient paths; it does NOT read content or screen
for identifiers. For real-report (class P) items the identifier screen is the aim's own gate plus Jake's human
check (Decision 38 = A); the gate, which confirms his checked mark, is re-run in step 1. The staged manifest holds only the rows of items actually
copied, and an aim FAILs if the connector's folder holds any file this run would not send (nothing is deleted).

Class M (manual-derived) items are copied: Jake approved every manual in use as of 11/23/2026 (Decision 41 =
LF-3, revisit about 2027-04-23), and an item can only be class M if its manual's OK is on record; withdrawing an OK
moves that manual's items aside, and the next copy-out then FAILs that aim until a person takes the stale file off
the share. ``--exclude-manual`` leaves class M out of a run.

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


def _refuse_stale(target: Path, names: set[str]) -> None:
    """FAIL the aim if the connector's folder holds anything this run would not send (design review, #64 item 1).

    A file held aside on the PC after an earlier copy-out would otherwise stay where the connector reads it.
    Nothing is deleted here: taking a stale file off the share is a named step for a person.
    """
    if not target.exists():
        return
    stale = sorted(p.name for p in target.iterdir() if p.name != MANIFEST and (p.is_dir() or p.name not in names))
    if stale:
        shown = ", ".join(n[:24] for n in stale[:10]) + (f" and {len(stale) - 10} more" if len(stale) > 10 else "")
        raise LearningFolderError(
            f"{target} holds {len(stale)} entr{'y' if len(stale) == 1 else 'ies'} this run would not send "
            f"({shown}); a person must move them off the share first"
        )


def _write_copied_manifest(folder: LearningFolder, shas: set[str], out: Path) -> None:
    """Only the latest row of each item actually copied goes out (#64 item 2): no held-back or held-aside rows."""
    rows = [row for sha, row in sorted(folder.state().items()) if sha in shas]
    out.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def copy_out(
    root: Path,
    dest: Path,
    guard: GuardRunner,
    gates: Mapping[str, Gate],
    aims: Sequence[str] | None = None,
    run_id: str | None = None,
    include_manual: bool = True,
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
            target = Path(dest) / aim
            _refuse_stale(target, {p.name for p in items})
            stage = learning / "_outbox" / run_id / aim
            stage.mkdir(parents=True, exist_ok=False)
            for path in items:
                shutil.copyfile(path, stage / path.name)
            _write_copied_manifest(folder, {p.name.split(".")[0] for p in items}, stage / MANIFEST)
            ok, line = guard(stage)
            if not ok:
                raise LearningFolderError(f"patient-run guard did not pass: {line or 'no output'}")
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
    ap.add_argument("--exclude-manual", action="store_true", help="leave class M (manual-derived) items out of this run")
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
        result = copy_out(root, args.dest, run_guard(args.guard), gates, args.aim, include_manual=not args.exclude_manual)
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
