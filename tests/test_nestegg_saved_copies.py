"""Saved copies (Jake 11/23 12:40 AM CT, Decision 30 A): ordered locations, content-addressed, hash-checked every time."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

NESTEGG = Path(__file__).resolve().parents[1] / "tools" / "nestegg"
sys.path.insert(0, str(NESTEGG))
import saved_copies as sc  # noqa: E402


def _cfg(*locs: dict) -> dict:
    return {"max_part_bytes": 10, "locations": list(locs)}


def test_shipped_config_is_ordered_home_release_origin_and_under_github_limit() -> None:
    cfg = sc.load_config()
    assert [loc["kind"] for loc in cfg["locations"]] == ["folder", "github_release", "github_release", "origin"]
    assert {loc["repo"] for loc in cfg["locations"] if loc["kind"] == "github_release"} == {"KULawHawk/adastra-saved-copies"}
    assert cfg["max_part_bytes"] < sc.GH_MAX_ASSET


def test_split_small_and_large_then_check_and_fetch(tmp_path: Path) -> None:
    small = tmp_path / "a.bin"
    small.write_bytes(b"12345")
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * 25)
    store = tmp_path / "store"
    e1 = sc.split(small, store, 10)
    e2 = sc.split(big, store, 10)
    assert (store / e1["sha256"]).is_file() and e1["parts"] == []
    assert [p["bytes"] for p in e2["parts"]] == [10, 10, 5]
    assert sc.check_folder(store, say=lambda *_: None) == 0
    cfg = _cfg({"name": "home", "kind": "folder", "path": str(store)})
    dest = tmp_path / "out" / "big.bin"
    assert sc.fetch(e2["sha256"], 25, "big.bin", dest, cfg, tmp_path, say=lambda *_: None) == "home"
    assert dest.read_bytes() == b"x" * 25


def test_changed_part_is_refused_and_next_location_used(tmp_path: Path) -> None:
    big = tmp_path / "big.bin"
    big.write_bytes(b"y" * 25)
    bad, good = tmp_path / "bad", tmp_path / "good"
    e = sc.split(big, bad, 10)
    sc.split(big, good, 10)
    (bad / f"{e['sha256']}.p002").write_bytes(b"z" * 10)  # tampered copy
    rows: list[str] = []
    cfg = _cfg({"name": "home", "kind": "folder", "path": str(bad)},
               {"name": "network drive", "kind": "folder", "path": str(good)})
    dest = tmp_path / "d.bin"
    assert sc.fetch(e["sha256"], 25, "big.bin", dest, cfg, tmp_path, say=rows.append) == "network drive"
    assert any("home" in r and "changed" in r for r in rows)
    assert sc.check_folder(bad, say=lambda *_: None) == 1
    assert not list(tmp_path.glob("*.joining"))


def test_no_copy_matches_returns_none_and_writes_nothing(tmp_path: Path) -> None:
    rows: list[str] = []
    cfg = _cfg({"name": "home", "kind": "folder", "path": str(tmp_path / "missing")},
               {"name": "original site", "kind": "origin"})
    dest = tmp_path / "d.bin"
    assert sc.fetch("0" * 64, 5, "f", dest, cfg, tmp_path, say=rows.append) is None
    assert not dest.exists() and len(rows) == 2


def test_release_skipped_without_gh_sign_in(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sc, "_gh_ok", lambda: False)
    rows: list[str] = []
    cfg = _cfg({"name": "GitHub release", "kind": "github_release", "repo": "o/r", "tag": "t"})
    assert sc.fetch("0" * 64, 5, "f", tmp_path / "d", cfg, tmp_path, say=rows.append) is None
    assert "not signed in" in rows[0] and "your own step" in rows[0]


def test_present_file_with_right_hash_is_not_fetched_again(tmp_path: Path) -> None:
    f = tmp_path / "f"
    f.write_bytes(b"abc")
    sha = hashlib.sha256(b"abc").hexdigest()
    assert sc.fetch(sha, 3, "f", f, _cfg(), tmp_path, say=lambda *_: None) == "already present"


def test_install_root_placeholder_expands(tmp_path: Path) -> None:
    assert sc.expand("{install_root}/saved", tmp_path) == tmp_path / "saved"
    json.dumps(sc.load_config())


def test_release_with_no_repo_is_skipped(tmp_path: Path) -> None:
    rel = {"name": "GitHub release", "kind": "github_release", "repo": "", "tag": "t"}
    rows: list[str] = []
    assert sc.fetch("0" * 64, 5, "f", tmp_path / "d", _cfg(rel), tmp_path, say=rows.append) is None
    assert "not chosen yet" in rows[0]


def _build():
    import importlib.util
    spec = importlib.util.spec_from_file_location("bsr", NESTEGG / "build_saved_release.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_failed_gh_call_says_why_and_masks_anything_secret(monkeypatch) -> None:
    """Run 45174686732 printed 35 bare 'exit status 1' rows; a FAIL row now carries gh's own words, never a token."""
    import subprocess
    m = _build()
    tok = "ghs_" + "A" * 36
    err = f"uploading x\nHTTP 502: Bad Gateway (https://uploads.github.com/x)\nAuthorization: token {tok}\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", err))
    try:
        m.gh("release", "upload", "models-v1", "f")
        raise AssertionError("gh did not raise")
    except RuntimeError as exc:
        msg = str(exc)
    assert "HTTP 502: Bad Gateway" in msg and "exit 1" in msg and tok not in msg and "[masked]" in msg
    assert "github_pat_" not in m._gh_error("github_pat_" + "b" * 40) and len(m._gh_error("x" * 900)) <= 303
    assert m._gh_error("") == "no error text from gh"
    for line, secret in (("Authorization: Basic dXNlcjpwYXNzd29yZA==", "dXNlcjpwYXNzd29yZA=="),
                         ("proxy-authorization: Bearer abc.def.ghi", "abc.def.ghi"),
                         ("fatal: https://x-access-token:s3cr3tvalue@github.com/o/r", "s3cr3tvalue"),
                         ("token=sometokenvalue more words", "sometokenvalue"),
                         ("GH_TOKEN=ghvaluexyz gh: not logged in", "ghvaluexyz"),
                         ("env ACCESS_TOKEN=accessvalue123", "accessvalue123"),
                         ("config api_key=apikeyvalue456", "apikeyvalue456"),
                         ("X-Api-Key: headerkey789", "headerkey789"),
                         ("DB_PASSWD=pw000 failed", "pw000")):
        out = m._gh_error(line)
        assert secret not in out and "[masked]" in out, out
    assert "HTTP 422" in m._gh_error("HTTP 422: Validation Failed")  # ordinary errors pass through untouched
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "nope"))
    assert m.gh("release", "view", "t", check=False).returncode == 1  # check=False still returns, as before


def test_measured_small_files_are_pinned_with_their_second_check() -> None:
    import json
    man = json.loads((NESTEGG / "models_pinned.json").read_text(encoding="utf-8"))
    pinned, stack = [], [man]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if "sha256_source" in node:
                pinned.append(node)
            assert node.get("unmeasured_reason", "").find("small non-LFS") < 0  # every small HF file now has a pin
            stack.extend(v for v in node.values() if isinstance(v, dict))
    assert all(len(p["sha256"]) == 64 for p in pinned)
    blob = [p for p in pinned if "git blob oid" in p["sha256_source"]]  # the small HF files, checked by git blob oid
    other = [p for p in pinned if p not in blob]  # files measured by download, each with an independent second check
    assert len(blob) == 130
    assert len(other) == 64  # pix2tex (2), RapidOCR (10), PP-Structure (4), surya (48): each names its second check
    assert all("checked a second way" in p["sha256_source"] or "only second check" in p["sha256_source"] for p in other)


def test_release_build_lists_every_locked_package_and_pinned_model() -> None:
    m = _build()
    pk = m.package_items()
    assert len(pk) > 100 and all(len(i["sha256"]) == 64 for i in pk)
    md = m.model_items()  # at least the HtrLens TrOCR files (hash-pinned) and Kraken
    assert any("trocr-base-handwritten" in i["name"] for i in md)
    assert all(i["url"].startswith("https://") for i in md)
    assert m._dist("torch-2.6.0+cu124-cp313-cp313-linux_x86_64.whl") == ("torch", "2.6.0+cu124")


def test_release_job_template_lives_outside_atrium_workflows() -> None:
    assert (NESTEGG / "release" / "build-saved-copy.yml").is_file()
    wf = (NESTEGG.parents[1] / ".github" / "workflows")
    assert not any("saved" in p.name for p in wf.iterdir())  # Atrium is public: never build the release here


def test_hf_snapshot_placed_from_saved_copy_only_when_every_file_matches(tmp_path: Path) -> None:
    store = tmp_path / "root" / "saved"
    files = {}
    for nm, data in (("config.json", b"{}"), ("model.safetensors", b"w" * 23)):
        f = tmp_path / nm
        f.write_bytes(data)
        e = sc.split(f, store, 10)
        files[nm] = {"bytes": len(data), "sha256": e["sha256"]}
    cfg = _cfg({"name": "home", "kind": "folder", "path": "{install_root}/saved"}, {"name": "o", "kind": "origin"})
    hub = tmp_path / "hub"
    snap = sc.place_hf_snapshot("org/m", "a" * 40, files, hub, cfg, tmp_path / "root", say=lambda *_: None)
    assert snap == hub / "models--org--m" / "snapshots" / ("a" * 40)
    assert (snap / "model.safetensors").read_bytes() == b"w" * 23
    assert (hub / "models--org--m" / "refs" / "main").read_text() == "a" * 40
    files["extra.bin"] = {"bytes": 1, "sha256": "f" * 64}  # not in any saved copy -> caller downloads instead
    assert sc.place_hf_snapshot("org/m", "b" * 40, files, hub, cfg, tmp_path / "root", say=lambda *_: None) is None
    files["extra.bin"] = {"bytes": 1, "sha256": None}  # unpinned file is never taken from a saved copy
    assert sc.place_hf_snapshot("org/m", "c" * 40, files, hub, cfg, tmp_path / "root", say=lambda *_: None) is None


def test_replaced_single_piece_file_is_refused(tmp_path: Path) -> None:
    """Reviewer 3 on #54: a whole (one-piece) file has no per-part hash, so only the joined-file check protects it.
    Removing that check must fail this test."""
    f = tmp_path / "model.bin"
    f.write_bytes(b"real weights")
    store = tmp_path / "store"
    e = sc.split(f, store, 1000)
    (store / e["sha256"]).write_bytes(b"fake weights")  # same size, different bytes
    rows: list[str] = []
    dest = tmp_path / "out.bin"
    cfg = _cfg({"name": "home", "kind": "folder", "path": str(store)})
    assert sc.fetch(e["sha256"], len(b"real weights"), "model.bin", dest, cfg, tmp_path, say=rows.append) is None
    assert not dest.exists() and "not the pinned" in rows[0]


def test_missing_copy_is_skip_but_changed_copy_is_warn(tmp_path: Path) -> None:
    """A copy that is simply absent is a SKIP row; one that is there with different bytes is a WARN row."""
    f = tmp_path / "a.bin"
    f.write_bytes(b"abc")
    e = sc.split(f, tmp_path / "home", 2_000_000_000)
    cfg = {"locations": [{"name": "home", "kind": "folder", "path": str(tmp_path / "home")}]}
    rows: list[str] = []
    (tmp_path / "home" / e["sha256"]).unlink()
    assert sc.fetch(e["sha256"], 3, "a.bin", tmp_path / "out" / "a.bin", cfg, tmp_path, say=rows.append) is None
    assert rows and rows[0].startswith("SKIP") and not any(r.startswith("WARN") for r in rows)
    (tmp_path / "home" / e["sha256"]).write_bytes(b"abd")
    rows.clear()
    assert sc.fetch(e["sha256"], 3, "a.bin", tmp_path / "out" / "a.bin", cfg, tmp_path, say=rows.append) is None
    assert rows and rows[0].startswith("WARN") and "a.bin" in rows[0] and "home" in rows[0]


def _source_pin():
    import importlib.util
    spec = importlib.util.spec_from_file_location("nestegg_source_pin", NESTEGG / "release" / "source_pin.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_source_pin_passes_only_when_tools_equal_the_pinned_atrium_commit(tmp_path: Path, capsys) -> None:
    """Reviewer 3 on #67: the saved-copies repository publishes only what a reviewed Atrium commit decided."""
    import shutil
    import subprocess
    sp = _source_pin()
    atr = tmp_path / "atrium"
    for src in sp.FILES:
        (atr / src).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(NESTEGG.parent.parent / src, atr / src)
    git = ["git", "-C", str(atr), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(atr)], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-qm", "pin"], check=True)
    sc_root = tmp_path / "saved-copies"
    for src, dst in sp.FILES.items():
        (sc_root / dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(atr / src, sc_root / dst)
    source = sc_root / "nestegg" / "SOURCE.txt"
    (atr / "tools" / "nestegg" / "release" / "build-saved-copy.yml").write_text("changed after the commit\n")
    assert sp.main(["make", "--commit", "HEAD", "--out", str(source), "--repo-dir", str(atr)]) == 0  # reads the commit, not the tree
    subprocess.run(git + ["checkout", "-q", "--", "."], check=True)
    verify = ["verify", "--source", str(source), "--root", str(sc_root), "--offline-from", str(atr)]
    assert sp.main(verify) == 0 and capsys.readouterr().out.strip().endswith(f"SOURCE-PIN: PASS {len(sp.FILES)}")

    (sc_root / "nestegg" / "saved_copies.json").write_text("{}")  # a tool changed on the saved-copies branch
    assert sp.main(verify) == 1 and "nestegg/saved_copies.json sha256" in capsys.readouterr().out
    shutil.copy(atr / "tools" / "nestegg" / "saved_copies.json", sc_root / "nestegg" / "saved_copies.json")

    (sc_root / "nestegg" / "extra.py").write_text("print(1)")  # an unpinned file the job could run
    assert sp.main(verify) == 1 and "nestegg/extra.py is in nestegg/ but not pinned" in capsys.readouterr().out
    (sc_root / "nestegg" / "extra.py").unlink()

    for extra in (".github/workflows/other.yml", ".github/actions/x/action.yml", ".github/dependabot.yml"):
        (sc_root / extra).parent.mkdir(parents=True, exist_ok=True)
        (sc_root / extra).write_text("on: push\n")  # reviewer 3's probe: a second workflow outside the pin
        assert sp.main(verify) == 1 and f"{extra} is in .github/ but not pinned" in capsys.readouterr().out
        (sc_root / extra).unlink()
    assert sp.main(verify) == 0
    capsys.readouterr()

    for planted in ("nestegg/__pycache__/saved_copies.cpython-313.pyc", "stray.pyc", "nestegg/__pycache__/x.opt-1.pyo"):
        (sc_root / planted).parent.mkdir(parents=True, exist_ok=True)
        (sc_root / planted).write_bytes(b"\x00planted")  # reviewer 3 on #68: Python would run this instead of the source
        assert sp.main(verify) == 1 and f"{planted} is compiled Python" in capsys.readouterr().out
        (sc_root / planted).unlink()
    (sc_root / "nestegg" / "__pycache__").rmdir()
    (sc_root / "tools_cache" / "__pycache__").mkdir(parents=True)  # even an empty cache folder is refused
    assert sp.main(verify) == 1 and "tools_cache/__pycache__ is compiled Python" in capsys.readouterr().out
    (sc_root / "tools_cache" / "__pycache__").rmdir()
    assert sp.main(verify) == 0
    capsys.readouterr()

    (atr / "tools" / "nestegg" / "saved_copies.py").write_text("# not what the commit holds\n")  # pin names other bytes
    assert sp.main(verify) == 1 and "tools/nestegg/saved_copies.py at Atrium" in capsys.readouterr().out


def test_release_job_refuses_to_publish_before_the_source_pin_passes() -> None:
    wf = (NESTEGG / "release" / "build-saved-copy.yml").read_text(encoding="utf-8")
    assert "compare/main...$c" in wf and "identical|behind)" in wf  # the pinned commit must be on Atrium main
    assert "raw.githubusercontent.com/KULawHawk/Atrium/$c/tools/nestegg/release/source_pin.py" in wf  # checker from the commit
    assert "branches: [main]" in wf and "claude/" not in wf  # Decision 48 A: publish only from main after a merge
    assert "if: github.ref == 'refs/heads/main'" in wf  # a manual run from another branch publishes nothing
    assert "needs: source-pin" in wf and "needs.source-pin.result == 'success'" in wf
    assert wf.count('python3 -I -B -X pycache_prefix="$RUNNER_TEMP/no-pyc" nestegg/build_saved_release.py') == 2
    assert "--kind packages --source nestegg/SOURCE.txt" in wf and "--kind models --source nestegg/SOURCE.txt" in wf


def test_installer_model_wheels_from_parts_json_are_saved() -> None:
    """en_core_web_sm is pinned only in parts.json; the models release must carry it (package-accounting check 11/23)."""
    m = _build()
    items = {i["sha256"]: i for i in m.model_items()}
    en = items["1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85"]
    assert en["name"] == "en_core_web_sm-3.8.0-py3-none-any.whl"
    assert en["bytes"] == 12806118
    assert en["url"].startswith("https://github.com/explosion/spacy-models/releases/download/")
    src = (NESTEGG / "release" / "source_pin.py").read_text(encoding="utf-8")
    assert '"tools/nestegg/parts.json": "nestegg/parts.json"' in src
