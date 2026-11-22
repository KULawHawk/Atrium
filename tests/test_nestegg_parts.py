"""Guards for tools/nestegg/install_parts.py + parts.json (Jake 11/22: everything used or
referenced is part of the build; nothing missing may pass quietly)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

NESTEGG = Path(__file__).resolve().parents[1] / "tools" / "nestegg"
PARTS = json.loads((NESTEGG / "parts.json").read_text(encoding="utf-8"))


def _mod():
    spec = importlib.util.spec_from_file_location("install_parts", NESTEGG / "install_parts.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_every_part_is_complete() -> None:
    names = [p["name"] for p in PARTS["parts"]]
    assert len(names) == len(set(names))
    for p in PARTS["parts"]:
        assert p["repo"] in {"Conclave", "locutus", "sequoia", "obsidian", "atrium"}, p
        assert p["roots"] and p["python"] in {"3.12", "3.13"}, p
        assert p.get("torch") in (None, *PARTS["torch"].keys()), p
        for m in p.get("models", []):
            assert m["step"] in {"unpinned", "htrlens_models", "spoke_script", "docling_download",
                                 "mineru_download", "spacy_model"}, m


def test_report_items_are_carried() -> None:
    """The package accounting's section A fixes are in the build list."""
    by = {p["name"]: p for p in PARTS["parts"]}
    assert by["HtrLens"]["python"] == "3.12" and by["HtrLens"]["torch"] == "htrlens"
    assert "torch==2.4.1" in PARTS["torch"]["htrlens"]["pins"]
    for r in ("HtrQwen", "GlmOcr", "GotOcrUnified", "VisionLocal", "FormFieldLens"):
        assert any(x.startswith("torchvision") for x in PARTS["torch"][by[r]["torch"]]["pins"]), r
    assert "accelerate" in by["GlmOcr"]["add"]
    assert by["MinerU"]["side_env"]["python"] == "3.12" and "six==1.17.0" in by["MinerU"]["add"]
    assert "six==1.17.0" in by["MarkerPdf"]["add"]
    assert by["OcrPaddle"]["spoke_side_env"]["python"] == "3.12"
    assert "sequoia" in by["sequoia_bridge"]["add_repos"]
    assert "keyring" in by["launcher"]["add"]
    assert any(m["step"] == "spacy_model" for m in by["obsidian"]["models"])
    assert any(m["step"] == "htrlens_models" for m in by["HtrLens"]["models"])


def test_dry_run_passes_and_writes_nothing(tmp_path: Path, capsys) -> None:
    for r in ("Conclave", "locutus", "sequoia", "obsidian", "atrium"):
        (tmp_path / "src" / r).mkdir(parents=True)
    rc = _mod().main(["--src", str(tmp_path / "src"), "--envs", str(tmp_path / "envs"), "--dry-run"])
    assert rc == 0 and not (tmp_path / "envs").exists()
    out = capsys.readouterr().out
    assert out.count("TODO ") == len(PARTS["parts"]) and out.rstrip().endswith("NESTEGG-PARTS: PASS")


def test_missing_source_and_unknown_part_fail_loudly(tmp_path: Path, capsys) -> None:
    rc = _mod().main(["--src", str(tmp_path), "--envs", str(tmp_path / "e"), "--only", "atrium,NoSuchPart"])
    out = capsys.readouterr().out
    assert rc == 1 and "source folder missing" in out and "not a part in parts.json" in out
    assert out.rstrip().endswith("NESTEGG-PARTS: FAIL 2")


def test_holds_never_read_as_pass(capsys) -> None:
    m = _mod()
    rep = m.Report()
    rep.row("HOLD", "x", "waits on Jake")
    assert rep.holds == 1 and rep.fails == 0


def test_missing_program_is_a_return_code_not_a_crash(tmp_path: Path) -> None:
    assert _mod().run(["no-such-program-nestegg"], tmp_path / "l.log") == 127


def test_closure_follows_in_repo_dependencies(tmp_path: Path) -> None:
    for name, deps, opt in (("conclave_a", ["conclave-b"], {"x": ["conclave-c"]}), ("conclave_b", [], {}), ("conclave_c", [], {})):
        d = tmp_path / name
        d.mkdir()
        (d / "pyproject.toml").write_text(
            f'[project]\nname = "{name.replace("_", "-")}"\ndependencies = {json.dumps(deps)}\n'
            f'[project.optional-dependencies]\n' + "".join(f'{k} = {json.dumps(v)}\n' for k, v in opt.items()), encoding="utf-8")
    out = _mod().closure(tmp_path, ["conclave_a[x]"])
    assert out == ["-e", f"{tmp_path / 'conclave_a'}[x]", "-e", str(tmp_path / "conclave_b"), "-e", str(tmp_path / "conclave_c")]
    assert _mod().closure(tmp_path, ["conclave_a"]) == ["-e", str(tmp_path / "conclave_a"), "-e", str(tmp_path / "conclave_b")]


def test_scan_skips_tests_and_sibling_scripts(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("import requests\nimport helper\n", encoding="utf-8")
    (tmp_path / "helper.py").write_text("import os\n", encoding="utf-8")
    (tmp_path / "test_x.py").write_text("import pytest\n", encoding="utf-8")
    (tmp_path / "conftest.py").write_text("import pytest\n", encoding="utf-8")
    pkgs, third = _mod().scan_imports([tmp_path], set())
    assert pkgs == ["pkg"] and third == ["requests"]


def test_no_secret_reads() -> None:
    src = (NESTEGG / "install_parts.py").read_text(encoding="utf-8")
    for bad in ("keyring.get", "CredRead", "ANTHROPIC_API_KEY", "RUNPOD_API_KEY", "HF_TOKEN", "setx", "winreg"):
        assert bad not in src, bad
