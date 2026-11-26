"""Decision 167 A (Jake, 1:48 PM CT 11/26): fill a Docling models folder from the saved copies, standalone.

For a PC whose Docling reader runs outside an installer environment (the workbench venv), so no adastra.json points the
reader at envs/_models/docling_artifacts. The reader's own lookup then reads %USERPROFILE%/.conclave/models/docling,
which is this script's default --to.

What it does:
- Takes every Docling model in models_pinned.json whose folder is under docling_artifacts (layout heron, TableFormer,
  the figure classifier, CodeFormulaV2, RapidOcr) and lays it out in Docling's own folder names under --to.
- Every file comes from the saved copies only (the home copy, then the private releases through your own GitHub CLI
  sign-in). The original sites are never asked, and every file is sha256-checked against its pin before it is kept.
- A file already there with the pinned bytes is kept as is. A file already there with OTHER bytes is never
  overwritten: that is a FAIL row and the file is left exactly as it was. Nothing is ever deleted.
- Exit code 0 only when every file is in place with its pinned sha256 ("DOCLING-MODELS: PASS").

--dry-run reads nothing from the network and writes nothing: it lists what would be placed and where.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PREFIX = "{models}/docling_artifacts/"
READER = "Docling"


def _saved_copies():
    spec = importlib.util.spec_from_file_location("nestegg_saved_copies", HERE / "saved_copies.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def docling_models(pins: dict) -> list[tuple[str, dict]]:
    """(folder name under the artifacts folder, model) for every Docling model the reader's artifacts folder holds."""
    out = []
    for m in pins.get("readers", {}).get(READER, {}).get("models", {}).values():
        default = str((m.get("local_dir") or {}).get("default", ""))
        if default.startswith(PREFIX):
            out.append((default[len(PREFIX):], m))
    return sorted(out, key=lambda t: t[0])


def plan(pins: dict, to: Path) -> tuple[list[tuple[Path, str, int | None, str]], list[str]]:
    """Every file to place: (destination, sha256, bytes, label), plus the reasons a model cannot be placed at all."""
    files, problems = [], []
    models = docling_models(pins)
    if not models:
        problems.append(f"no {READER} model under {PREFIX} in models_pinned.json")
    for folder, m in models:
        if not folder or ".." in Path(folder).parts:
            problems.append(f"{folder!r}: not a plain folder name")
            continue
        fs = m.get("files") or {}
        if not fs:
            problems.append(f"{folder}: no files pinned")
        for rel, meta in sorted(fs.items()):
            sha = meta.get("sha256")
            if not sha or len(sha) != 64 or Path(rel).is_absolute() or ".." in Path(rel).parts:
                problems.append(f"{folder}/{rel}: no usable pinned sha256 or path")
                continue
            files.append((to / folder / rel, sha, meta.get("bytes"), f"{folder}/{rel}"))
    return files, problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--to", type=Path, default=Path.home() / ".conclave" / "models" / "docling",
                    help="the Docling models folder to fill (default: %%USERPROFILE%%/.conclave/models/docling)")
    ap.add_argument("--root", type=Path, default=Path.home() / "AdAstra",
                    help="install root whose saved/ folder is the home copy (default: %%USERPROFILE%%/AdAstra)")
    ap.add_argument("--pins", type=Path, default=HERE / "models_pinned.json")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    sc = _saved_copies()
    pins = json.loads(a.pins.read_text(encoding="utf-8"))
    to = a.to.expanduser().resolve()
    files, problems = plan(pins, to)
    total = sum(b or 0 for _, _, b, _ in files)
    print(f"Docling models folder: {to}")
    print(f"{len(files)} files, {total:,} bytes, from the saved copies only (original sites never asked)")
    for p in problems:
        print(f"FAIL  {p}")
    if a.dry_run:
        for dest, sha, size, label in files:
            print(f"PLAN  {label}  {size if size is not None else '?'} B  sha256 {sha[:12]}...")
        print("DOCLING-MODELS: DRY RUN (nothing read from the network, nothing written)"
              + (f"; {len(problems)} problem(s) above" if problems else ""))
        return 1 if problems else 0

    cfg = sc.load_config()
    locs = [loc for loc in cfg["locations"] if loc["kind"] != "origin"]
    if not sc.usable(locs, a.root):
        print(f"FAIL  no saved copy can be read: no index in {a.root / 'saved'}, and the GitHub CLI is not signed in "
              "(sign in with 'gh auth login' yourself, or run Pull Saved Copies.cmd first)")
        print("DOCLING-MODELS: FAIL (nothing placed)")
        return 1

    placed: dict[str, int] = {}
    bad: list[str] = []
    for dest, sha, size, label in files:
        if dest.is_file():
            if (size is None or dest.stat().st_size == size) and sc.sha256_file(dest) == sha:
                placed["already present"] = placed.get("already present", 0) + 1
                continue
            print(f"FAIL  {label}: a file with other bytes is already at {dest}; left untouched (move it aside to place the pinned one)")
            bad.append(label)
            continue
        if dest.exists():
            print(f"FAIL  {label}: {dest} exists and is not a file; left untouched")
            bad.append(label)
            continue
        src = sc.fetch(sha, size, label, dest, {"locations": locs}, a.root, origin_url=None, say=print)
        if src is None:
            print(f"FAIL  {label}: not found with the pinned sha256 in any saved copy")
            bad.append(label)
        else:
            placed[src] = placed.get(src, 0) + 1
    where = ", ".join(f"{n} from {k}" for k, n in sorted(placed.items()))
    fails = len(bad) + len(problems)
    if fails:
        print(f"DOCLING-MODELS: FAIL {fails} ({len(files) - len(bad)} of {len(files)} files in place: {where or 'none'})")
        return 1
    print(f"DOCLING-MODELS: PASS {len(files)} files, {total:,} bytes, every sha256 matches its pin ({where}) at {to}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
