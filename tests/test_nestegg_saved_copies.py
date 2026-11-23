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
    assert [loc["kind"] for loc in cfg["locations"]] == ["folder", "github_release", "origin"]
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


def test_release_repo_left_empty_until_jake_picks_a_private_one(tmp_path: Path) -> None:
    rel = [loc for loc in sc.load_config()["locations"] if loc["kind"] == "github_release"][0]
    assert rel["repo"] == ""  # Atrium is public; never point the saved copies at it
    rows: list[str] = []
    assert sc.fetch("0" * 64, 5, "f", tmp_path / "d", _cfg(rel), tmp_path, say=rows.append) is None
    assert "not chosen yet" in rows[0]


def _build():
    import importlib.util
    spec = importlib.util.spec_from_file_location("bsr", NESTEGG / "build_saved_release.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


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
