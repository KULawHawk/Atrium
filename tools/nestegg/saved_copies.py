"""Saved copies of every package and model file (Jake 11/23 12:40 AM CT, Decision 30 A; run with python -I).

Two copies, both his: a private GitHub release built by a runner from our hash lists, and a home copy on his PC
pulled from that release. The installer looks in an ORDERED list of copy locations (saved_copies.json) and takes
the first copy whose bytes match the pinned sha256; the original site is the last resort. Every file is
hash-checked every time, whichever copy it came from. A changed file is refused by name, never used.

Layout (shared with the package accounting thread's packages half), content-addressed so names never collide:
  - a file of at most max_part_bytes is stored as  <sha256>
  - a larger one is stored as parts               <sha256>.p001, <sha256>.p002, ...   (GitHub: under 2 GiB each)
  - INDEX.json maps  sha256 -> {"name", "bytes", "parts": [{"sha256", "bytes"}, ...] or []}
A home or network folder holds the same names flat in one folder, with the same INDEX.json. Jake's home-network
drive (11/23 12:44 AM: a large external disk on his own network) becomes one more "folder" entry; no code change.

The release is private, so reading it uses the person's own `gh` sign-in (never a key in a file); without it that
location is skipped with a row saying so, and the next location is tried.

  python -I saved_copies.py split <file> <out-folder> [--max-part-bytes N]   (release build: add a file)
  python -I saved_copies.py check <folder>                                   (every file in INDEX.json, by hash)
  python -I saved_copies.py pull --to <home-folder> [--only sha,...]          (home copy from the release)
  python -I saved_copies.py fetch <sha256> <dest> --name N [--bytes B] [--root R]  (one file, saved copies only)
Last line of check/pull: SAVED-COPIES: PASS n | FAIL n. Of fetch: SAVED-COPY: PASS <from where> | FAIL
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "saved_copies.json"
GH_MAX_ASSET = 2 * 1024**3  # GitHub: each release file must be under 2 GiB
INDEX = "INDEX.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_config(path: Path = CONFIG) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if int(cfg["max_part_bytes"]) >= GH_MAX_ASSET:
        raise ValueError(f"max_part_bytes {cfg['max_part_bytes']} must be under GitHub's 2 GiB limit")
    return cfg


def expand(path: str, install_root: Path) -> Path:
    return Path(os.path.expandvars(path.replace("{install_root}", str(install_root))))


# ---- adding a file (release build side) ---------------------------------------------------------------------------

def split(src: Path, out: Path, max_part_bytes: int, name: str | None = None) -> dict:
    """Store one file content-addressed in `out`, cut into parts if needed, and add it to out/INDEX.json."""
    out.mkdir(parents=True, exist_ok=True)
    whole = sha256_file(src)
    size = src.stat().st_size
    entry = {"name": name or src.name, "bytes": size, "parts": []}
    if size <= max_part_bytes:
        shutil.copyfile(src, out / whole)
    else:
        with src.open("rb") as fh:
            n = 0
            while True:
                chunk = fh.read(max_part_bytes)
                if not chunk:
                    break
                n += 1
                part = out / f"{whole}.p{n:03d}"
                part.write_bytes(chunk)
                entry["parts"].append({"sha256": hashlib.sha256(chunk).hexdigest(), "bytes": len(chunk)})
    idx_path = out / INDEX
    idx = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else {}
    old = idx.get(whole)
    if old and old["bytes"] != size:
        raise ValueError(f"{whole} already in the index with a different size")
    idx[whole] = entry
    tmp = idx_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(idx, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(idx_path)
    return {"sha256": whole, **entry}


CHANGED = "copy changed: "  # prefix of a refusal where bytes WERE there but did not match the pin (said as WARN)


def asset_names(sha: str, entry: dict) -> list[str]:
    return [f"{sha}.p{i:03d}" for i in range(1, len(entry["parts"]) + 1)] if entry["parts"] else [sha]


# ---- getting a file (installer side) ------------------------------------------------------------------------------

def _join_verified(sha: str, entry: dict, getpart, dest: Path) -> str | None:
    """Assemble `dest` from its stored pieces; return None on success or the reason it was refused."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".joining")
    try:
        with tmp.open("wb") as out:
            names = asset_names(sha, entry)
            for i, nm in enumerate(names):
                piece = getpart(nm)
                if piece is None:
                    return f"{nm} not in this copy"
                if entry["parts"]:
                    want = entry["parts"][i]
                    got = sha256_file(piece)
                    if got != want["sha256"] or piece.stat().st_size != want["bytes"]:
                        return f"{CHANGED}part {nm} changed (sha256 {got})"
                with piece.open("rb") as fh:
                    shutil.copyfileobj(fh, out, 1 << 20)
        got = sha256_file(tmp)
        if got != sha or tmp.stat().st_size != entry["bytes"]:
            return f"{CHANGED}assembled file sha256 {got} is not the pinned {sha}"
        tmp.replace(dest)
        return None
    finally:
        if tmp.exists():
            tmp.unlink()  # our own half-written temp file only, never a saved copy


def _folder_get(loc: Path):
    return lambda nm: (loc / nm) if (loc / nm).is_file() else None


def _gh_ok() -> bool:
    gh = shutil.which("gh")
    if not gh:
        return False
    return subprocess.run([gh, "auth", "status"], capture_output=True).returncode == 0


def _release_get(repo: str, tag: str, scratch: Path):
    gh = shutil.which("gh")

    def get(nm: str) -> Path | None:
        p = scratch / nm
        if p.is_file():
            return p
        r = subprocess.run([gh, "release", "download", tag, "-R", repo, "-p", nm, "-D", str(scratch), "--clobber"],
                           capture_output=True, text=True)
        return p if r.returncode == 0 and p.is_file() else None
    return get


def _release_exists(repo: str, tag: str) -> bool:
    """False only when GitHub says this release does not exist yet (a newly listed tag before its first publish)."""
    r = subprocess.run([shutil.which("gh"), "release", "view", tag, "-R", repo, "--json", "tagName"],
                       capture_output=True, text=True)
    return not (r.returncode != 0 and "release not found" in (r.stderr or "").lower())


def fetch(sha: str, size: int | None, name: str, dest: Path, cfg: dict, install_root: Path,
          origin_url: str | None = None, say=print) -> str | None:
    """Put the file with this sha256 at `dest`. Returns the location name it came from, or None (with rows said)."""
    if dest.is_file() and (size is None or dest.stat().st_size == size) and sha256_file(dest) == sha:
        return "already present"
    for loc in cfg["locations"]:
        kind, label = loc["kind"], loc["name"]
        if kind == "folder":
            folder = expand(loc["path"], install_root)
            idx_path = folder / INDEX
            if not idx_path.is_file():
                say(f"SKIP  {name:<28} {label}: no {INDEX} at {folder}")
                continue
            entry = json.loads(idx_path.read_text(encoding="utf-8")).get(sha)
            if not entry:
                say(f"SKIP  {name:<28} {label}: not in this copy")
                continue
            why = _join_verified(sha, entry, _folder_get(folder), dest)
        elif kind == "github_release":
            if not loc.get("repo"):
                say(f"SKIP  {name:<28} {label}: release repository not chosen yet (it must be private)")
                continue
            if not _gh_ok():
                say(f"SKIP  {name:<28} {label}: GitHub CLI not signed in (sign in with 'gh auth login'; your own step)")
                continue
            with tempfile.TemporaryDirectory() as td:
                get = _release_get(loc["repo"], loc["tag"], Path(td))
                idx_file = get(INDEX)
                entry = json.loads(idx_file.read_text(encoding="utf-8")).get(sha) if idx_file else None
                if not entry:
                    say(f"SKIP  {name:<28} {label}: not in release {loc['repo']}@{loc['tag']}")
                    continue
                why = _join_verified(sha, entry, get, dest)
        elif kind == "origin":
            if not origin_url:
                say(f"SKIP  {name:<28} {label}: no original address recorded")
                continue
            tmp = dest.with_name(dest.name + ".download")
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                urllib.request.urlretrieve(origin_url, tmp)
                got = sha256_file(tmp)
                why = None if got == sha and size in (None, tmp.stat().st_size) else f"{CHANGED}original site sent sha256 {got}"
                if why is None:
                    tmp.replace(dest)
            except OSError as exc:
                why = f"download failed: {exc}"
            finally:
                if tmp.exists():
                    tmp.unlink()
        else:
            say(f"FAIL  {name:<28} unknown copy kind {kind!r} in saved_copies.json")
            continue
        if why is None:
            return label
        if why.startswith(CHANGED):  # a copy that is there but not the pinned bytes is never a quiet skip
            say(f"WARN  {name:<28} {label}: {why}")
        else:
            say(f"SKIP  {name:<28} {label}: {why}")
    return None


def place_hf_snapshot(repo_id: str, revision: str, files: dict, hub_cache: Path, cfg: dict, install_root: Path,
                      say=print, ref: str = "main") -> Path | None:
    """Put a pinned Hugging Face snapshot into the standard hub cache from the saved copies (no origin here: the
    caller's own downloader is the original-site step). Files are written as plain files under
    snapshots/<revision>/ (as huggingface_hub itself does on Windows without symlinks), and refs/main points at the
    pinned revision (or `ref`, the tag the reader asks for). Returns the snapshot folder only when EVERY file matched its pin, else None."""
    locs = {"locations": [loc for loc in cfg["locations"] if loc["kind"] != "origin"]}
    if not usable(locs["locations"], install_root):
        return None
    repo_dir = hub_cache / ("models--" + repo_id.replace("/", "--"))
    snap = repo_dir / "snapshots" / revision
    for path, meta in sorted(files.items()):
        if not meta.get("sha256"):
            say(f"SKIP  {repo_id}/{path}: no pinned sha256, so not taken from a saved copy")
            return None
        if fetch(meta["sha256"], meta.get("bytes"), f"{repo_id}/{path}", snap / path, locs, install_root, say=say) is None:
            return None
    (repo_dir / "refs").mkdir(parents=True, exist_ok=True)
    (repo_dir / "refs" / ref).write_text(revision, encoding="utf-8")  # the name the reader asks for (main or a tag)
    return snap


def usable(locations: list[dict], install_root: Path) -> list[str]:
    """Names of the copy locations that can be read right now (a folder with an index, or a chosen, signed-in release)."""
    out = []
    for loc in locations:
        if loc["kind"] == "folder" and (expand(loc["path"], install_root) / INDEX).is_file():
            out.append(loc["name"])
        elif loc["kind"] == "github_release" and loc.get("repo") and _gh_ok():
            out.append(loc["name"])
    return out


# ---- commands -----------------------------------------------------------------------------------------------------

def check_folder(folder: Path, say=print) -> int:
    idx = json.loads((folder / INDEX).read_text(encoding="utf-8"))
    fails = 0
    for sha, entry in sorted(idx.items()):
        with tempfile.TemporaryDirectory() as td:
            why = _join_verified(sha, entry, _folder_get(folder), Path(td) / "x")
        if why:
            fails += 1
            say(f"FAIL  {entry['name']:<28} {why}")
        else:
            say(f"PASS  {entry['name']:<28} {entry['bytes']:,} bytes")
    say(f"SAVED-COPIES: PASS {len(idx)}" if not fails else f"SAVED-COPIES: FAIL {fails}")
    return 1 if fails else 0


def pull(to: Path, cfg: dict, only: set[str] | None = None, say=print) -> int:
    """Fill a home folder from the release: same names, same INDEX.json, each piece hash-checked."""
    rels = [loc for loc in cfg["locations"] if loc["kind"] == "github_release" and loc.get("repo")]
    if not rels:
        say("SAVED-COPIES: FAIL 1 (no private release repository chosen in saved_copies.json yet)")
        return 1
    if not _gh_ok():
        say("SAVED-COPIES: FAIL 1 (GitHub CLI not signed in; run 'gh auth login' yourself, then this again)")
        return 1
    to.mkdir(parents=True, exist_ok=True)
    idx: dict = {}
    getters: dict = {}
    for rel in rels:  # one home folder and one merged INDEX.json for every release
        if not _release_exists(rel["repo"], rel["tag"]):  # listed, not published yet (reviewer 3 on #114)
            say(f"SKIP  release {rel['repo']}@{rel['tag']} does not exist yet (not published); the other releases are pulled")
            continue
        get = _release_get(rel["repo"], rel["tag"], Path(tempfile.mkdtemp(prefix="saved_idx_")))
        idx_file = get(INDEX)
        if not idx_file:
            say(f"SAVED-COPIES: FAIL 1 (no {INDEX} in release {rel['repo']}@{rel['tag']})")
            return 1
        part = json.loads(idx_file.read_text(encoding="utf-8"))
        idx.update(part)
        getters.update({s: _release_get(rel["repo"], rel["tag"], to) for s in part})
    need = sum(e["bytes"] for s, e in idx.items() if not only or s in only)
    free = shutil.disk_usage(to).free
    if free < need + 2 * 1024**3:
        say(f"SAVED-COPIES: FAIL 1 (needs {need / 1e9:.1f} GB plus 2 GB spare on {to}; {free / 1e9:.1f} GB free)")
        return 1
    fails = 0
    ok: set[str] = set()
    for sha, entry in sorted(idx.items()):
        if only and sha not in only:
            continue
        for i, nm in enumerate(asset_names(sha, entry)):
            want = entry["parts"][i] if entry["parts"] else {"sha256": sha, "bytes": entry["bytes"]}
            p = to / nm
            if p.is_file() and p.stat().st_size == want["bytes"] and sha256_file(p) == want["sha256"]:
                continue
            got = getters[sha](nm)
            if not got or sha256_file(got) != want["sha256"]:
                fails += 1
                say(f"FAIL  {entry['name']:<28} {nm} missing or changed in the release")
                break
        else:
            ok.add(sha)
            say(f"PASS  {entry['name']:<28} {entry['bytes']:,} bytes")
    merged = to / INDEX
    old = json.loads(merged.read_text(encoding="utf-8")) if merged.is_file() else {}
    old.update({s: e for s, e in idx.items() if s in ok})
    merged.write_text(json.dumps(old, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    say("SAVED-COPIES: PASS" if not fails else f"SAVED-COPIES: FAIL {fails}")
    return 1 if fails else 0


def fetch_one(sha: str, size: int | None, name: str, dest: Path, cfg: dict, install_root: Path, say=print) -> int:
    """One pinned file from the saved copies only (never the original site); a file already at dest is never replaced."""
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        say(f"SAVED-COPY: FAIL {name}: {sha!r} is not a sha256")
        return 1
    if dest.exists() and not (dest.is_file() and sha256_file(dest) == sha):
        say(f"SAVED-COPY: FAIL {name}: {dest} already exists with other bytes; left untouched")
        return 1
    locs = {"locations": [loc for loc in cfg["locations"] if loc["kind"] != "origin"]}
    notes: list[str] = []
    src = fetch(sha, size, name, dest, locs, install_root, origin_url=None, say=notes.append)
    for w in notes:
        if src is None or w.startswith("WARN"):  # where it looked is shown only when it was not found; WARN always
            say(w)
    if src is None:
        say(f"SAVED-COPY: FAIL {name}: not found with sha256 {sha} in any saved copy")
        return 1
    say(f"SAVED-COPY: PASS {name} from {src} (sha256 checked) at {dest}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("split")
    s.add_argument("file", type=Path)
    s.add_argument("out", type=Path)
    s.add_argument("--name")
    s.add_argument("--max-part-bytes", type=int)
    c = sub.add_parser("check")
    c.add_argument("folder", type=Path)
    p = sub.add_parser("pull")
    p.add_argument("--to", type=Path, required=True)
    p.add_argument("--only", default="")
    f = sub.add_parser("fetch")  # Install-Prereqs.ps1 (Decision 174 B): one pinned program from the saved copies only
    f.add_argument("sha256")
    f.add_argument("dest", type=Path)
    f.add_argument("--name", required=True)
    f.add_argument("--bytes", type=int, default=None)
    f.add_argument("--root", type=Path, default=Path.home() / "AdAstra")
    a = ap.parse_args(argv)
    cfg = load_config()
    if a.cmd == "split":
        e = split(a.file, a.out, a.max_part_bytes or int(cfg["max_part_bytes"]), a.name)
        print(json.dumps(e))
        return 0
    if a.cmd == "check":
        return check_folder(a.folder)
    if a.cmd == "fetch":
        return fetch_one(a.sha256.lower(), a.bytes, a.name, a.dest, cfg, a.root)
    return pull(a.to, cfg, {x for x in a.only.split(",") if x} or None)


if __name__ == "__main__":
    sys.exit(main())
