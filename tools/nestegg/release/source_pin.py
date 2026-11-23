"""Pin the saved-copies repository's tools to one reviewed Atrium commit (reviewer 3 on Atrium #67, 11/23/2026).

What gets published to the private saved-copy releases must be decided by a reviewed Atrium commit, not by whatever
copy of the tools sits on a branch of the saved-copies repository. So:

  make    writes SOURCE.txt from an Atrium commit: the commit id and the sha256 of every tool file AT THAT COMMIT
          (read with `git show`, never from the working tree).
  verify  run by the build job before anything is published. FAIL unless every listed file in the saved-copies
          checkout has exactly the listed sha256, no unlisted file sits in nestegg/ or .github/, no __pycache__ or .pyc
          is anywhere in the checkout, and every listed file at that
          commit on github.com (Atrium is public) has the same sha256. The job checks separately, in its own
          workflow step, that the commit is on Atrium main; this script is fetched from that commit, not from the
          saved-copies copy.

  python -I source_pin.py make --commit SHA [--out SOURCE.txt]          (in an Atrium checkout)
  python -I source_pin.py verify --source nestegg/SOURCE.txt [--root .] [--offline-from DIR]
Last line: SOURCE-PIN: PASS n | FAIL n
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ATRIUM = "KULawHawk/Atrium"
# Atrium path -> path in the saved-copies repository. Everything the build job runs or reads.
FILES = {
    "tools/nestegg/build_saved_release.py": "nestegg/build_saved_release.py",
    "tools/nestegg/saved_copies.py": "nestegg/saved_copies.py",
    "tools/nestegg/saved_copies.json": "nestegg/saved_copies.json",
    "tools/nestegg/models_pinned.json": "nestegg/models_pinned.json",
    "tools/nestegg/htrlens_models.json": "nestegg/htrlens_models.json",
    "tools/nestegg/parts.json": "nestegg/parts.json",
    "tools/nestegg/locks/SHA256SUMS_cu124_linux.txt": "nestegg/locks/SHA256SUMS_cu124_linux.txt",
    "tools/nestegg/locks/SHA256SUMS_linux_x86_64.txt": "nestegg/locks/SHA256SUMS_linux_x86_64.txt",
    "tools/nestegg/locks/SHA256SUMS_sdist.txt": "nestegg/locks/SHA256SUMS_sdist.txt",
    "tools/nestegg/locks/SHA256SUMS_win_amd64.txt": "nestegg/locks/SHA256SUMS_win_amd64.txt",
    "tools/nestegg/release/build-saved-copy.yml": ".github/workflows/build-saved-copy.yml",
}
LINE = re.compile(r"^([0-9a-f]{64})  (\S+)  (\S+)$")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def make(commit: str, out: Path, repo_dir: Path) -> int:
    full = subprocess.run(["git", "-C", str(repo_dir), "rev-parse", "--verify", commit + "^{commit}"],
                          capture_output=True, text=True, check=True).stdout.strip()
    lines = [f"atrium_repo {ATRIUM}", f"atrium_commit {full}",
             "# sha256  atrium path  path in the saved-copies repository (the build job refuses to publish on any mismatch)"]
    for src, dst in FILES.items():
        data = subprocess.run(["git", "-C", str(repo_dir), "show", f"{full}:{src}"], capture_output=True, check=True).stdout
        lines.append(f"{sha256_bytes(data)}  {src}  {dst}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"SOURCE-PIN: MADE {out} for {full} ({len(FILES)} files)")
    return 0


def parse(source: Path) -> tuple[str, list[tuple[str, str, str]]]:
    commit, rows = "", []
    for ln in source.read_text(encoding="utf-8").splitlines():
        if ln.startswith("atrium_commit "):
            commit = ln.split()[1]
        elif (m := LINE.match(ln)):
            rows.append(m.groups())
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("SOURCE.txt has no full 40-character atrium_commit line")
    return commit, rows


def _github_bytes(commit: str, path: str) -> bytes:
    url = f"https://raw.githubusercontent.com/{ATRIUM}/{commit}/{path}"
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def verify(source: Path, root: Path, offline_from: Path | None = None) -> int:
    fails = 0

    def fail(msg: str) -> None:
        nonlocal fails
        fails += 1
        print(f"FAIL  {msg}", flush=True)

    try:
        commit, rows = parse(source)
    except (OSError, ValueError) as exc:
        print(f"FAIL  {exc}\nSOURCE-PIN: FAIL 1")
        return 1
    listed = {dst for _, _, dst in rows}
    if {(s, d) for _, s, d in rows} != set(FILES.items()):
        fail("SOURCE.txt does not list exactly the files this checker pins (made by another version?)")
    for want, src, dst in rows:
        local = root / dst
        if not local.is_file():
            fail(f"{dst} missing from this checkout")
            continue
        got = sha256_bytes(local.read_bytes())
        if got != want:
            fail(f"{dst} sha256 {got} is not the pinned {want}")
            continue
        try:
            remote = (offline_from / src).read_bytes() if offline_from else _github_bytes(commit, src)
        except OSError as exc:
            fail(f"{src} at {commit[:12]} could not be read: {exc}")
            continue
        if sha256_bytes(remote) != want:
            fail(f"{src} at Atrium {commit[:12]} has sha256 {sha256_bytes(remote)}, not the pinned {want}")
            continue
        print(f"PASS  {dst}  = Atrium {commit[:12]}:{src}")
    # no compiled Python anywhere in the checkout: Python can run a __pycache__ .pyc in place of the pinned source
    # (an unchecked-hash .pyc is never compared with the source, and -I does not stop it; reviewer 3 on #68)
    for p in sorted(root.rglob("*")):
        if ".git" in p.relative_to(root).parts[:1]:
            continue
        if p.name == "__pycache__" or (p.is_file() and p.suffix in (".pyc", ".pyo")):
            fail(f"{p.relative_to(root).as_posix()} is compiled Python; the build runs only pinned source")
    # nothing unpinned may sit where the job reads tools (nestegg/) or where GitHub reads workflows and actions
    # (.github/: a second workflow file would run with this repository's token outside the pin; reviewer 3 on #67)
    for top in ("nestegg", ".github"):
        for p in sorted((root / top).rglob("*")):
            rel = p.relative_to(root).as_posix()
            if p.is_file() and rel != source.relative_to(root).as_posix() and rel not in listed:
                fail(f"{rel} is in {top}/ but not pinned in SOURCE.txt")
    print(f"SOURCE-PIN: PASS {len(rows)}" if not fails else f"SOURCE-PIN: FAIL {fails}")
    return 1 if fails else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    mk = sub.add_parser("make")
    mk.add_argument("--commit", required=True)
    mk.add_argument("--out", type=Path, default=Path("SOURCE.txt"))
    mk.add_argument("--repo-dir", type=Path, default=Path("."))
    vf = sub.add_parser("verify")
    vf.add_argument("--source", type=Path, required=True)
    vf.add_argument("--root", type=Path, default=Path("."))
    vf.add_argument("--offline-from", type=Path, default=None, help="tests only: an Atrium checkout instead of github.com")
    a = ap.parse_args(argv)
    if a.cmd == "make":
        return make(a.commit, a.out, a.repo_dir)
    return verify(a.source.resolve(), a.root.resolve(), a.offline_from)


if __name__ == "__main__":
    sys.exit(main())
