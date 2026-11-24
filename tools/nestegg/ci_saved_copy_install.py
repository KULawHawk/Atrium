"""CI proof of the saved-copy package install on a clean machine (run with python -I).

Why: the PC install on 11/23 11:03 PM CT failed for all 6 parts: the saved packages release supplied the cp312 file
of numpy / pydantic-core / charset-normalizer to Python 3.13 environments and pip ran with --no-index. This script
rebuilds that situation without the private release: it makes a HOME COPY (the installer's first saved-copy
location) holding EVERY Windows file the lists name, cp312 and cp313 alike, downloaded from PyPI and checked against
the measured sha256, then runs the installer's own locked_install for each list into a fresh environment of THIS
interpreter, followed by pip check.

  python -I ci_saved_copy_install.py home    --root <dir> [--lists a,b]             (build the home copy)
  python -I ci_saved_copy_install.py install --root <dir> --installer <install_parts.py> [--lists a,b]
Last line of install: SAVED-COPY-INSTALL: PASS n | FAIL n (exit 0 / 1). The home copy is never a release.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import urllib.request
import venv
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_LISTS = ("harness_adapters", "workbench", "PdfText", "StructuredHeuristic", "OcrTesseract", "OcrPaddle",
                 "_test_env_workbench", "_test_tools")


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def lines_for(ip, list_name: str) -> list[str]:
    """The requirement lines the installer itself would use for this list on this platform."""
    cfg = json.loads((ip.HERE / "parts.json").read_text(encoding="utf-8"))
    ip.CFG_LOCK.update(cfg)
    sums = ip.load_sums(ip.WIN)
    part = next((p for p in cfg["parts"] if p["name"] == list_name), None)
    if part is not None:
        lines, probs = ip.part_lock(part, cfg, Path("."), ip.WIN, False, sums)
    else:
        pins = ip.read_list(ip.LOCKS / "lists" / f"{list_name}_py3.13.txt")
        lines, probs = ip.lock_reqs(pins or {}, cfg, ip.WIN, sums)
    if probs:
        raise SystemExit(f"{list_name}: not locked: {probs}")
    return lines


def home(root: Path, lists: list[str]) -> int:
    ip = load(HERE / "install_parts.py", "install_parts")
    sc = ip._saved_copies()
    names = ip.saved_file_names()
    saved = root / "saved"
    have = set(json.loads((saved / "INDEX.json").read_text(encoding="utf-8"))) if (saved / "INDEX.json").is_file() else set()
    tmp = root / "_dl"
    tmp.mkdir(parents=True, exist_ok=True)
    meta: dict[tuple[str, str], dict] = {}
    put = missing = 0
    for ln_name in lists:
        for ln in lines_for(ip, ln_name):
            if ln.startswith("--"):
                continue
            req = ln.split()[0]
            pkg, ver = req.split("==", 1)
            for h in [x.split(":", 1)[1] for x in ln.split() if x.startswith("--hash=sha256:")]:
                fn = names.get(h)
                if not fn or h in have or not (fn.endswith(".whl") or fn.endswith((".tar.gz", ".zip"))):
                    continue
                if not (fn.endswith("-any.whl") or "win_amd64" in fn or not fn.endswith(".whl")):
                    continue  # this copy is for a Windows install
                key = (pkg, ver.split("+")[0])
                if key not in meta:
                    try:
                        with urllib.request.urlopen(f"https://pypi.org/pypi/{key[0]}/{key[1]}/json", timeout=60) as r:
                            meta[key] = {u["filename"]: u for u in json.load(r)["urls"]}
                    except Exception as exc:  # noqa: BLE001
                        print(f"MISS  {fn}: PyPI metadata unreadable ({type(exc).__name__})")
                        meta[key] = {}
                u = meta[key].get(fn)
                if not u or u["digests"]["sha256"] != h:
                    print(f"MISS  {fn}: not on PyPI under this name and hash")
                    missing += 1
                    continue
                dest = tmp / fn
                urllib.request.urlretrieve(u["url"], dest)
                if hashlib.sha256(dest.read_bytes()).hexdigest() != h:
                    raise SystemExit(f"{fn}: downloaded bytes do not match the measured sha256")
                sc.split(dest, saved, 2_000_000_000)
                dest.unlink()
                have.add(h)
                put += 1
    print(f"HOME-COPY: {put} files added, {missing} not on PyPI (installed from the index instead), {len(have)} in total")
    return 0


def install(root: Path, installer: Path, lists: list[str]) -> int:
    ip = load(installer, "install_parts_under_test")
    ip.INSTALL_ROOT["root"] = root
    envs = root / "envs"
    (envs / "_logs").mkdir(parents=True, exist_ok=True)
    ok = bad = 0
    for name in lists:
        env = envs / f"ci_{name}"
        venv.EnvBuilder(with_pip=True, clear=True).create(env)
        py = ip.env_python(env)
        log = envs / "_logs" / f"ci_{name}.txt"
        rc = ip.locked_install(py, lines_for(ip, name), envs / "_logs" / f"ci_{name}.lock.txt", log)
        chk = subprocess.run([str(py), "-m", "pip", "check"], capture_output=True, text=True) if rc == 0 else None
        if rc == 0 and chk.returncode == 0:
            ok += 1
            print(f"PASS  {name:<22} installed from the lists; pip check clean")
        else:
            bad += 1
            tail = [l for l in log.read_text(encoding="utf-8", errors="replace").splitlines() if "ERROR" in l][-2:]
            print(f"FAIL  {name:<22} rc={rc} {(chk.stdout.strip() if chk else '')} {' | '.join(tail)}")
        taken = [l.split("saved copy: ", 1)[1] for l in log.read_text(encoding="utf-8", errors="replace").splitlines()
                 if l.startswith("saved copy: ")]
        wrong = [t for t in taken if "-cp312-" in t or "-cp311-" in t]
        if wrong:
            print(f"      {name}: files built for another Python were taken: {wrong[:3]}")
    print(f"SAVED-COPY-INSTALL: {'FAIL ' + str(bad) if bad else 'PASS ' + str(ok)}")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("home", "install"))
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--installer", type=Path, default=HERE / "install_parts.py")
    ap.add_argument("--lists", default=",".join(DEFAULT_LISTS))
    a = ap.parse_args()
    lists = [x for x in a.lists.split(",") if x]
    return home(a.root, lists) if a.mode == "home" else install(a.root, a.installer, lists)


if __name__ == "__main__":
    sys.exit(main())
