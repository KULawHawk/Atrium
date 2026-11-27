"""Decision 167 A: the standalone Docling models step fills the reader's folder from the saved copies only, hash-checked."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

NESTEGG = Path(__file__).resolve().parents[1] / "tools" / "nestegg"
sys.path.insert(0, str(NESTEGG))
import saved_copies as sc  # noqa: E402

_spec = importlib.util.spec_from_file_location("place_docling_models", NESTEGG / "place_docling_models.py")
pdm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pdm)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


FILES = {
    ("docling-project--docling-layout-heron", "model.safetensors"): b"heron weights",
    ("docling-project--docling-layout-heron", "config.json"): b"{}",
    ("docling-project--docling-models", "model_artifacts/tableformer/fast/tm_config.json"): b"table cfg",
}


def _pins(tmp: Path, files=FILES) -> Path:
    models: dict = {}
    for (folder, rel), data in files.items():
        m = models.setdefault(folder, {"source": "huggingface", "local_dir": {"default": f"{{models}}/docling_artifacts/{folder}"},
                                       "files": {}})
        m["files"][rel] = {"sha256": _sha(data), "bytes": len(data)}
    models["other"] = {"source": "huggingface", "local_dir": {"default": "{models}/elsewhere"},
                       "files": {"x.bin": {"sha256": _sha(b"x"), "bytes": 1}}}
    p = tmp / "pins.json"
    p.write_text(json.dumps({"readers": {"Docling": {"models": models}}}), encoding="utf-8")
    return p


def _home_copy(root: Path, files=FILES) -> None:
    src = root / "_src"
    src.mkdir(parents=True, exist_ok=True)
    for i, data in enumerate(files.values()):
        f = src / f"f{i}"
        f.write_bytes(data)
        sc.split(f, root / "saved", 5)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(sc, "_gh_ok", lambda: False)  # never the real release from a test
    monkeypatch.setattr(pdm, "_saved_copies", lambda: sc)


def _run(tmp: Path, *extra: str) -> int:
    return pdm.main(["--to", str(tmp / "out"), "--root", str(tmp / "root"), "--pins", str(_pins(tmp)), *extra])


def test_places_every_file_in_the_docling_layout_from_the_home_copy(tmp_path: Path, capsys) -> None:
    _home_copy(tmp_path / "root")
    assert _run(tmp_path) == 0
    for (folder, rel), data in FILES.items():
        assert (tmp_path / "out" / folder / rel).read_bytes() == data
    assert not (tmp_path / "out" / "other").exists() and not (tmp_path / "out" / "elsewhere").exists()
    assert "DOCLING-MODELS: PASS 3 files" in capsys.readouterr().out
    assert _run(tmp_path) == 0  # a second run keeps what is there
    assert "3 from already there" in capsys.readouterr().out


def test_a_file_with_other_bytes_is_never_overwritten(tmp_path: Path, capsys) -> None:
    _home_copy(tmp_path / "root")
    clash = tmp_path / "out" / "docling-project--docling-layout-heron" / "model.safetensors"
    clash.parent.mkdir(parents=True)
    clash.write_bytes(b"someone else's weights")
    assert _run(tmp_path) == 1
    assert clash.read_bytes() == b"someone else's weights"
    out = capsys.readouterr().out
    assert "left untouched" in out and "DOCLING-MODELS: FAIL 1" in out


def test_a_file_missing_from_the_saved_copies_fails_and_no_original_site_is_asked(tmp_path: Path, monkeypatch, capsys) -> None:
    partial = dict(list(FILES.items())[:2])
    _home_copy(tmp_path / "root", partial)
    monkeypatch.setattr(sc.urllib.request, "urlretrieve", lambda *a, **k: pytest.fail("original site asked"))
    assert _run(tmp_path) == 1
    assert not (tmp_path / "out" / "docling-project--docling-models").exists()
    assert "DOCLING-MODELS: FAIL 1" in capsys.readouterr().out


def test_no_readable_saved_copy_is_a_fail_and_writes_nothing(tmp_path: Path, capsys) -> None:
    assert _run(tmp_path) == 1
    assert not (tmp_path / "out").exists()
    assert "DOCLING-MODELS: FAIL (nothing placed)" in capsys.readouterr().out


def test_dry_run_writes_nothing(tmp_path: Path, capsys) -> None:
    _home_copy(tmp_path / "root")
    assert _run(tmp_path, "--dry-run") == 0
    assert not (tmp_path / "out").exists()
    assert "DRY RUN" in capsys.readouterr().out


def test_a_pin_without_a_sha256_or_with_a_climbing_path_fails(tmp_path: Path) -> None:
    pins = json.loads(_pins(tmp_path).read_text(encoding="utf-8"))
    heron = pins["readers"]["Docling"]["models"]["docling-project--docling-layout-heron"]["files"]
    heron["config.json"]["sha256"] = None
    heron["../escape.bin"] = {"sha256": _sha(b"e"), "bytes": 1}
    files, problems = pdm.plan(pins, tmp_path / "out")
    assert len(problems) == 2 and len(files) == 2
    assert all(tmp_path / "out" in d.parents for d, *_ in files)


def test_shipped_pins_cover_all_five_docling_folders() -> None:
    pins = json.loads((NESTEGG / "models_pinned.json").read_text(encoding="utf-8"))
    files, problems = pdm.plan(pins, Path("/x"))
    assert problems == []
    assert {f for f, _ in pdm.docling_models(pins)} == {
        "docling-project--docling-layout-heron", "docling-project--docling-models",
        "docling-project--DocumentFigureClassifier-v2.5", "docling-project--CodeFormulaV2", "RapidOcr"}
    assert len(files) == 45 and sum(b for *_, b, _ in files) == 1_297_926_359


def test_output_is_one_counted_line_per_file_with_no_skip_rows_and_the_verdict_last(tmp_path: Path, capsys) -> None:
    """Jake's first PC run (11/26 6:05 PM CT): rows of SKIP for places that simply lack a file read as his files
    being skipped. Wording only: one counted OK line per file, from where, and the verdict as the last line."""
    _home_copy(tmp_path / "root")
    assert _run(tmp_path) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert not [ln for ln in lines if "SKIP" in ln]
    ok = [ln for ln in lines if " OK " in ln]
    assert [ln.split("]")[0] for ln in ok] == ["[1 of 3", "[2 of 3", "[3 of 3"]
    assert all("(from home copy, checked)" in ln for ln in ok)
    assert lines[-1].startswith("DOCLING-MODELS: PASS 3 files") and lines[-2].startswith("Done.")


def test_a_changed_copy_is_still_shown_and_a_failed_file_lists_where_it_looked(tmp_path: Path, capsys) -> None:
    partial = dict(list(FILES.items())[:2])
    _home_copy(tmp_path / "root", partial)
    assert _run(tmp_path) == 1
    out = capsys.readouterr().out
    assert "FAIL  docling-project--docling-models/model_artifacts/tableformer/fast/tm_config.json" in out
    assert "home copy: not in this copy" in out  # the reason is shown only for the file that failed
    assert out.strip().splitlines()[-1].startswith("DOCLING-MODELS: FAIL 1")


def test_a_copy_with_other_bytes_is_shown_as_warn_never_hidden(tmp_path: Path, capsys) -> None:
    _home_copy(tmp_path / "root")
    data = FILES[("docling-project--docling-layout-heron", "model.safetensors")]
    (tmp_path / "root" / "saved" / f"{_sha(data)}.p001").write_bytes(b"XXXXX")  # tampered piece
    assert _run(tmp_path) == 1
    out = capsys.readouterr().out
    assert "WARN" in out and "changed" in out
    assert "FAIL  docling-project--docling-layout-heron/model.safetensors" in out
