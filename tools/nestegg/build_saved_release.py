"""Build the private saved-copy release (Decision 30 A, Jake 11/23 12:40 AM CT). Runs on a GitHub runner INSIDE the
private saved-copies repository (its own GITHUB_TOKEN publishes; no key is stored anywhere). Run with python -I.

For each pinned file (packages: locks/SHA256SUMS_*.txt; models: models_pinned.json + htrlens_models.json; hashes there were transcribed from the Hub listing, so each is
recomputed here and a mismatch is a FAIL) it downloads
from the original site, refuses anything whose sha256 is not the pin, stores it content-addressed through
saved_copies.split (parts under 2 GiB), uploads the pieces, then deletes its own local working copy so a runner's disk
holds one file at a time. Assets already in the release are not uploaded again, so a stopped run resumes.
INDEX.json is re-uploaded after every file. With --source, SOURCE.txt (the reviewed Atrium commit and the sha256 of
every tool file; checked by release/source_pin.py before this runs) is uploaded into the release first.

  python -I build_saved_release.py --repo OWNER/NAME --kind packages|models [--tag packages-v1] [--limit N] [--dry-run]
                                   [--source nestegg/SOURCE.txt]
Last line: SAVED-RELEASE: PASS n | FAIL n (n files)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCKS = HERE / "locks"


def _sc():
    spec = importlib.util.spec_from_file_location("nestegg_saved_copies", HERE / "saved_copies.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- what to save ---------------------------------------------------------------------------------------------------

def package_items() -> list[dict]:
    items = {}
    for f in sorted(LOCKS.glob("SHA256SUMS_*.txt")):
        for ln in f.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                h, fn = ln.split()
                items[h] = {"sha256": h, "name": fn, "bytes": None, "source": "pypi"}
    return list(items.values())


def model_items() -> list[dict]:
    out: dict[str, dict] = {}

    def add_hf(repo: str, rev: str, files: dict) -> None:
        for path, meta in files.items():
            name = f"{repo}@{rev[:12]}/{path}"
            # a file with no pin yet (small non-LFS files) is measured here, at an immutable commit, and reported
            out[meta.get("sha256") or name] = {"sha256": meta.get("sha256"), "name": name, "bytes": meta.get("bytes"),
                                               "url": f"https://huggingface.co/{repo}/resolve/{rev}/{path}"}

    for mf in (HERE / "htrlens_models.json", HERE / "models_pinned.json"):
        if not mf.is_file():
            continue
        data = json.loads(mf.read_text(encoding="utf-8"))
        stack = [data]
        while stack:  # walk nested groups (reader -> model) without caring about grouping depth
            node = stack.pop()
            if not isinstance(node, dict):
                continue
            if node.get("repo_id") and node.get("revision") and isinstance(node.get("files"), dict):
                add_hf(node["repo_id"], node["revision"], node["files"])
            elif node.get("sha256") and (node.get("url") or node.get("doi")):
                url = node.get("url") or ""
                if url:
                    out[node["sha256"]] = {"sha256": node["sha256"], "name": node.get("file_name") or url.rsplit("/", 1)[-1],
                                           "bytes": node.get("bytes"), "url": url}
            stack.extend(v for v in node.values() if isinstance(v, dict))
    # model wheels the installer itself fetches (parts.json "models": spaCy's en_core_web_sm), pinned there by sha256
    pf = HERE / "parts.json"
    if pf.is_file():
        stack = [json.loads(pf.read_text(encoding="utf-8"))]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                if node.get("wheel") and node.get("wheel_sha256"):
                    out[node["wheel_sha256"]] = {"sha256": node["wheel_sha256"], "name": node["wheel"].rsplit("/", 1)[-1],
                                                 "bytes": node.get("wheel_bytes"), "url": node["wheel"]}
                stack.extend(node.values())
    return list(out.values())


# ---- where a package file comes from --------------------------------------------------------------------------------

class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs += [v for k, v in attrs if k == "href" and v]


def _dist(fn: str) -> tuple[str, str]:
    if fn.endswith(".whl"):
        d, v = fn.split("-")[:2]
    else:
        d, v = re.sub(r"\.(tar\.gz|zip)$", "", fn).rsplit("-", 1)
    return d, v


def package_url(fn: str) -> str | None:
    d, v = _dist(fn)
    m = re.search(r"\+(cu\d+)", v)
    if m:  # +cu124 builds live only on PyTorch's own index
        page = f"https://download.pytorch.org/whl/{m.group(1)}/{d.lower().replace('_', '-')}/"
        p = _Links()
        p.feed(urllib.request.urlopen(page, timeout=60).read().decode())
        for h in p.hrefs:
            if h.split("#")[0].rsplit("/", 1)[-1].replace("%2B", "+") == fn:
                return urllib.request.urljoin(page, h.split("#")[0])
        return None
    meta = json.loads(urllib.request.urlopen(f"https://pypi.org/pypi/{d}/{v}/json", timeout=60).read())
    for u in meta.get("urls", []):
        if u["filename"] == fn:
            return u["url"]
    return None


# ---- the release ----------------------------------------------------------------------------------------------------

# anything shaped like a credential is masked before gh's own error text is printed (reporting only)
_SECRET = re.compile(r"gh[opsur]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}")
# a name holding token, key, secret, password or an auth word masks everything after it to the end of that line
# matched inside a longer name too (GH_TOKEN=, ACCESS_TOKEN=, api_key=, x-api-key:); over-masking is the safe side
_AFTER = re.compile(r"(?i)([A-Za-z0-9_-]*(?:authorization|bearer|basic|token|key|secret|passw(?:or)?d)[A-Za-z0-9_-]*)[\s:=].*$")
_USERINFO = re.compile(r"(://)[^/\s@]+@")  # https://user:token@host


def _gh_error(stderr: str) -> str:
    """gh's own words on a failure, so a FAIL row says why (run 45174686732 had 35 bare 'exit status 1' rows).
    Credential-shaped text is masked; at most the last 3 lines and 300 characters are kept."""
    lines = [ln.strip() for ln in (stderr or "").splitlines() if ln.strip()][-3:]
    lines = [_USERINFO.sub(r"\1[masked]@", _AFTER.sub(r"\1 [masked]", _SECRET.sub("[masked]", ln))) for ln in lines]
    text = " | ".join(lines)
    return (text[:300] + "...") if len(text) > 300 else (text or "no error text from gh")


def gh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if check and r.returncode:
        raise RuntimeError(f"gh {' '.join(args)} failed (exit {r.returncode}): {_gh_error(r.stderr)}")
    return r


def release_assets(repo: str, tag: str) -> set[str]:
    if gh("release", "view", tag, "-R", repo, check=False).returncode != 0:
        gh("release", "create", tag, "-R", repo, "--title", tag, "--notes",
           "Saved copies of every pinned package and model file (Decision 30 A). Content-addressed; see INDEX.json.")
        return set()
    r = gh("release", "view", tag, "-R", repo, "--json", "assets")
    return {a["name"] for a in json.loads(r.stdout)["assets"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--tag", default="")
    ap.add_argument("--kind", choices=["packages", "models"], required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--source", type=Path, default=None,
                    help="SOURCE.txt (Atrium commit + sha256 of every tool file); uploaded into the release first")
    a = ap.parse_args(argv)
    a.tag = a.tag or f"{a.kind}-v1"  # packages-v1 / models-v1: each under GitHub's 1,000 files per release
    sc = _sc()
    cfg = sc.load_config()
    items = package_items() if a.kind == "packages" else model_items()
    total = sum(i["bytes"] or 0 for i in items)
    print(f"{len(items)} {a.kind} files, {total:,} bytes known", flush=True)
    if a.dry_run:
        for i in items[: a.limit or None]:
            print(f"TODO  {i['name']}")
        print(f"SAVED-RELEASE: DRY RUN ({len(items)} files)")
        return 0
    have = release_assets(a.repo, a.tag)
    if a.source:  # every release says which reviewed Atrium commit decided what is in it
        gh("release", "upload", a.tag, str(a.source), "-R", a.repo, "--clobber")
        print(f"SOURCE {a.source.name} uploaded to {a.tag}", flush=True)
    work = Path(tempfile.mkdtemp(prefix="saved_release_"))
    store = work / "store"
    store.mkdir()
    if "INDEX.json" in have:
        gh("release", "download", a.tag, "-R", a.repo, "-p", "INDEX.json", "-D", str(store), "--clobber")
    idx = json.loads((store / "INDEX.json").read_text()) if (store / "INDEX.json").exists() else {}
    fails = done = 0
    measured: dict[str, str] = {}
    by_name = {e["name"]: s for s, e in idx.items()}
    for i in items[: a.limit or None]:
        sha = i["sha256"] or by_name.get(i["name"])
        if sha and sha in idx and all(n in have for n in sc.asset_names(sha, idx[sha])):
            if not i["sha256"]:
                measured[i["name"]] = sha
            done += 1
            continue
        try:
            url = i.get("url") or package_url(i["name"])
            if not url:
                raise RuntimeError("no download address found")
            dl = work / "dl"
            urllib.request.urlretrieve(url, dl)
            got = sc.sha256_file(dl)
            if i["sha256"] is None:  # measured at the pinned commit; becomes a pin only by a reviewed commit
                measured[i["name"]] = sha = got
            elif got != sha:
                raise RuntimeError(f"original site sent sha256 {got}, not the pin")
            if i.get("bytes") and dl.stat().st_size != i["bytes"]:
                raise RuntimeError(f"original site sent {dl.stat().st_size} bytes, pinned {i['bytes']}")
            entry = sc.split(dl, store, int(cfg["max_part_bytes"]), i["name"])
            dl.unlink()
            for nm in sc.asset_names(sha, entry):
                gh("release", "upload", a.tag, str(store / nm), "-R", a.repo, "--clobber")
                (store / nm).unlink()  # our own working copy; the release now holds it
            gh("release", "upload", a.tag, str(store / "INDEX.json"), "-R", a.repo, "--clobber")
            done += 1
            print(f"PASS  {i['name']}  {entry['bytes']:,} bytes  {len(entry['parts']) or 1} piece(s)", flush=True)
        except Exception as exc:  # one bad file is a FAIL row; the rest still go
            fails += 1
            print(f"FAIL  {i['name']}  {exc}", flush=True)
    if measured:  # reported for a reviewed pin commit; the installer never trusts these until they are in the manifest
        mp = work / "measured_pins.json"
        mp.write_text(json.dumps(measured, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        gh("release", "upload", a.tag, str(mp), "-R", a.repo, "--clobber")
        print(f"MEASURED {len(measured)} files with no pin yet (release asset measured_pins.json)")
    shutil.rmtree(work, ignore_errors=True)  # the runner's temp folder only
    print(f"SAVED-RELEASE: PASS {done}" if not fails else f"SAVED-RELEASE: FAIL {fails} ({done} saved)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
