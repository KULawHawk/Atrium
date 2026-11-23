"""Fetch, verify and load-check the HtrLens model files (Nestegg step, run with python -I).

Jake, 11/21: "any install should have those files included, so it should not come back
with that error. But yes, it should fail loudly." So every file is pinned (exact revision,
byte count, sha256) and any mismatch is a FAIL line, never a silent fallback.

Modes:
  --dry-run   say what would be fetched; write nothing.
  (default)   fetch into the standard caches HtrLens already reads (no environment
              variable and no Windows setting is changed), verify every file, then
              load both models through HtrLens's own classes.
  --measure   CI only: fetch and PRINT size + sha256 of every file (and the Kraken
              record's licence) so the manifest can be filled once; always ends FAIL.
  --load-check direct   load with the engines' own loaders (CI has no HtrLens code).
Last line: NESTEGG-HTRLENS: PASS | FAIL n
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "htrlens_models.json"


class Report:
    def __init__(self) -> None:
        self.fails = 0

    def row(self, status: str, what: str, detail: str) -> None:
        if status == "FAIL":
            self.fails += 1
        print(f"{status:<5} {what:<24} {detail}", flush=True)

    def final(self) -> int:
        print("NESTEGG-HTRLENS: PASS" if self.fails == 0 else f"NESTEGG-HTRLENS: FAIL {self.fails}")
        return 0 if self.fails == 0 else 1


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_manifest(path: Path = MANIFEST) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check_file(rep: Report, label: str, path: Path, want_sha: str | None, want_bytes: int | None) -> bool:
    """One pinned file: present, right size, right sha256. A missing pin is a FAIL, not a pass."""
    if not path.is_file():
        rep.row("FAIL", label, f"missing at {path}")
        return False
    if want_bytes is not None and path.stat().st_size != want_bytes:
        rep.row("FAIL", label, f"size {path.stat().st_size} bytes, expected {want_bytes}")
        return False
    if not want_sha:
        rep.row("FAIL", label, "no sha256 pinned in htrlens_models.json yet; refusing to trust it")
        return False
    got = sha256_file(path)
    if got != want_sha:
        rep.row("FAIL", label, f"sha256 {got[:12]}... does not match pinned {want_sha[:12]}...")
        return False
    rep.row("PASS", label, f"sha256 {got[:12]}... matches")
    return True


def kraken_cache_dir() -> Path:  # pragma: no cover - needs click from the reader's venv
    import click

    return Path(click.get_app_dir("kraken"))


def fetch_kraken(rep: Report, man: dict, dry: bool, measure: bool = False) -> None:
    k = man["kraken"]
    if dry:
        rep.row("TODO", "Kraken model", f"would fetch {k['doi']} and require sha256 {k['sha256'][:12]}...")
        return
    if measure:
        from kraken import repo as kraken_repo

        with tempfile.TemporaryDirectory() as tmp:
            got = Path(kraken_repo.get_model(k["doi"], tmp))
            got = got if got.is_absolute() else Path(tmp) / got
            print(f"MEASURED kraken:{got.name} {got.stat().st_size} {sha256_file(got)}")
        try:
            desc = kraken_repo.get_description(k["doi"])
            print(f"MEASURED kraken-licence {json.dumps(desc.get('license') if isinstance(desc, dict) else str(desc))}")
        except Exception as exc:  # the licence read is informational in measure mode
            print(f"MEASURED kraken-licence unreadable ({type(exc).__name__}: {exc})")
        return
    cache = kraken_cache_dir()
    target = cache / k["cache_name"]
    if not target.is_file():
        from kraken import repo as kraken_repo  # the reader's own fetcher

        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            got = Path(kraken_repo.get_model(k["doi"], tmp))
            if not got.is_absolute():
                got = Path(tmp) / got
            if not got.is_file():
                rep.row("FAIL", "Kraken model", f"kraken fetched no file for {k['doi']}")
                return
            if sha256_file(got) != k["sha256"]:
                rep.row("FAIL", "Kraken model", "downloaded file does not match the pinned sha256; not installed")
                return
            shutil.copy2(got, target)
    if check_file(rep, "Kraken model", target, k["sha256"], k.get("bytes")):
        rep.row("INFO", "Kraken licence", k.get("attribution", k.get("license", "")))


def fetch_trocr(rep: Report, man: dict, dry: bool, measure: bool) -> None:
    t = man["trocr"]
    names = sorted(t["files"])
    total = sum(f["bytes"] for f in t["files"].values())
    if dry:
        rep.row("TODO", "TrOCR model", f"would fetch {t['repo_id']}@{t['revision'][:12]} ({len(names)} files, {total} bytes)")
        return
    from huggingface_hub import model_info, snapshot_download

    card = model_info(t["repo_id"], revision=t["revision"]).card_data
    lic = None if card is None else (card.get("license") if hasattr(card, "get") else getattr(card, "license", None))
    if str(lic).lower() != t["license_expected"]:
        rep.row("FAIL", "TrOCR licence", f"model card licence is {lic!r}, expected {t['license_expected']!r}; stopping")
        return
    rep.row("PASS", "TrOCR licence", str(lic))
    snap = None
    if not measure:  # Decision 30 A: the saved copies first (home, then the private release); each file hash-checked
        import importlib.util
        from huggingface_hub import constants

        spec = importlib.util.spec_from_file_location("nestegg_saved_copies", HERE / "saved_copies.py")
        sc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sc)
        marker = Path(sys.prefix) / "adastra.json"  # written into every part's environment by install_parts.py
        root = Path(json.loads(marker.read_text(encoding="utf-8"))["install_root"]) if marker.is_file() \
            else Path(os.environ.get("ADASTRA_INSTALL_ROOT") or Path.home() / "AdAstra")
        snap = sc.place_hf_snapshot(t["repo_id"], t["revision"], t["files"], Path(constants.HF_HUB_CACHE),
                                    sc.load_config(), root,
                                    say=lambda m: m.startswith("WARN") and rep.row("WARN", "TrOCR saved copy changed", m[6:].strip()))
        if snap:
            rep.row("INFO", "TrOCR source", "saved copy")
    if snap is None:
        snap = Path(snapshot_download(t["repo_id"], revision=t["revision"], allow_patterns=names))
    if measure:
        for n in names:
            print(f"MEASURED {n} {(snap / n).stat().st_size} {sha256_file(snap / n)}")
        rep.row("FAIL", "TrOCR files", "measure mode only prints hashes; it never verifies")
        return
    ok = all(check_file(rep, f"TrOCR {n}", snap / n, t["files"][n]["sha256"], t["files"][n]["bytes"]) for n in names)
    if ok:
        # from_pretrained(repo_id) with no revision reads refs/main in the cache. Point it at
        # the pinned, verified snapshot so an offline load uses exactly these files.
        refs = snap.parent.parent / "refs"
        refs.mkdir(exist_ok=True)
        (refs / "main").write_text(t["revision"], encoding="utf-8")
        rep.row("PASS", "TrOCR pinned", f"cache points at revision {t['revision'][:12]}")


def load_check(rep: Report, how: str) -> None:
    """Load both models offline in a fresh child process (HF_HUB_OFFLINE must be set before
    huggingface_hub is imported, and this process already imported it)."""
    import os
    import subprocess

    env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    r = subprocess.run([sys.executable, "-I", str(Path(__file__).resolve()), "--load-only", how],
                       env=env, capture_output=True, text=True)
    for ln in (r.stdout + r.stderr).splitlines():
        if ln.startswith(("PASS ", "FAIL ")):
            rep.row(ln[:4], ln[5:].split("|", 1)[0].strip(), ln.split("|", 1)[1].strip() if "|" in ln else "")
    if r.returncode != 0 and "FAIL " not in r.stdout:
        rep.row("FAIL", "HtrLens load check", f"child exited {r.returncode}: {(r.stderr or r.stdout).strip()[-300:]}")


def load_only(how: str, man: dict) -> int:  # pragma: no cover - needs the reader's venv and the real files
    """Child-process body. how = 'htrlens' (HtrLens's own classes; a real install) or
    'direct' (the engines' own loaders; CI, where the private HtrLens code is absent)."""
    try:
        if how == "htrlens":
            from conclave_lens_htrlens.kraken_pipeline import KrakenPass
            from conclave_lens_htrlens.trocr_crosscheck import TrocrCrosscheck

            k = KrakenPass(allow_cpu_fallback=True)
            k.ensure_model()
            print(f"PASS HtrLens loads Kraken | {k.model_identifier()}")
            t = TrocrCrosscheck(allow_cpu_fallback=True)
            t.ensure_model()
            print(f"PASS HtrLens loads TrOCR | {t.model_identifier()}")
        else:
            from kraken.lib import models
            from transformers import TrOCRProcessor, VisionEncoderDecoderModel

            models.load_any(str(kraken_cache_dir() / man["kraken"]["cache_name"]))
            print("PASS Kraken loads offline | kraken.lib.models.load_any")
            TrOCRProcessor.from_pretrained(man["trocr"]["repo_id"])
            VisionEncoderDecoderModel.from_pretrained(man["trocr"]["repo_id"])
            print("PASS TrOCR loads offline | refs/main -> pinned revision")
    except Exception as exc:
        print(f"FAIL HtrLens load check | {type(exc).__name__}: {exc}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--skip-load-check", action="store_true")
    ap.add_argument("--load-check", choices=("htrlens", "direct"), default="htrlens")
    ap.add_argument("--load-only", choices=("htrlens", "direct"), help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    man = load_manifest()
    if a.load_only:
        return load_only(a.load_only, man)
    rep = Report()
    fetch_kraken(rep, man, a.dry_run, a.measure)
    fetch_trocr(rep, man, a.dry_run, a.measure)
    if not (a.dry_run or a.measure or a.skip_load_check) and rep.fails == 0:
        load_check(rep, a.load_check)
    return rep.final()


if __name__ == "__main__":
    sys.exit(main())
