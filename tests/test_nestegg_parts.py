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
                                 "mineru_download", "spacy_model", "pinned_models"}, m
            if m["step"] == "pinned_models":  # every such reader has its files pinned in models_pinned.json
                man = json.loads((NESTEGG / "models_pinned.json").read_text(encoding="utf-8"))["readers"][p["name"]]
                assert all(meta.get("sha256") for mm in man["models"].values()
                           if mm.get("source") in ("huggingface", "github_release") for meta in mm["files"].values()), p


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


def test_dry_run_writes_nothing_and_never_passes_an_unlocked_part(tmp_path: Path, capsys) -> None:
    for r in ("Conclave", "locutus", "sequoia", "obsidian", "atrium"):
        (tmp_path / "src" / r).mkdir(parents=True)
    rc = _mod().main(["--src", str(tmp_path / "src"), "--envs", str(tmp_path / "envs"), "--dry-run"])
    assert not (tmp_path / "envs").exists()
    out = capsys.readouterr().out
    assert out.count("TODO ") == len(PARTS["parts"]) + 1 and "TODO  learning folders" in out  # the parts + the learning folders
    fails = [ln for ln in out.splitlines() if ln.startswith("FAIL ")]
    assert fails and all(" not locked " in ln for ln in fails)  # launcher + sequoia_bridge have no list yet
    assert rc == 1 and out.rstrip().endswith(f"NESTEGG-PARTS: FAIL {len(fails)}, HOLD 0, PASS 0")


def test_missing_source_and_unknown_part_fail_loudly(tmp_path: Path, capsys) -> None:
    rc = _mod().main(["--src", str(tmp_path), "--envs", str(tmp_path / "e"), "--only", "atrium,NoSuchPart"])
    out = capsys.readouterr().out
    assert rc == 1 and "source folder missing" in out and "not a part in parts.json" in out
    assert out.rstrip().endswith("NESTEGG-PARTS: FAIL 2, HOLD 0, PASS 0")


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


# ---------------------------------------------------------------- exact-version locks
LOCKS = NESTEGG / "locks"


def test_lock_copy_is_byte_identical_to_its_recorded_source() -> None:
    import hashlib
    for ln in (LOCKS / "SOURCE_SHA256.txt").read_text(encoding="utf-8").splitlines():
        h, rel = ln.split()
        assert hashlib.sha256((LOCKS / rel).read_bytes()).hexdigest() == h, rel


def test_every_list_belongs_to_a_part() -> None:
    names = {f"{p['name']}_py{p['python']}.txt" for p in PARTS["parts"]} | {"votingengine_beta_py3.13.txt", "_test_tools_py3.13.txt"}  # beta list kept by package accounting (equals votingengine since Conclave #2910); test tools for non-readers
    names |= {f"_{p['side_env']['name']}_cli_py{p['side_env']['python']}.txt" for p in PARTS["parts"] if p.get("side_env")}
    names |= {f"{p['name']}_side_py{p['spoke_side_env']['python']}.txt" for p in PARTS["parts"] if p.get("spoke_side_env")}
    names |= {p["test_env"]["list"] for p in PARTS["parts"] if p.get("test_env")}
    for f in (LOCKS / "lists").iterdir():
        assert f.name in names, f.name


def _cfg():
    return {"lock": PARTS["lock"], "torch": {"t": {"pins": ["torch==2.6.0"]}},
            "gate3_constraints": {"file": "g.txt", "names": ["numpy", "timm"]}}


def _sums():
    return {("torch", "2.6.0"): ["aa"], ("click", "8.5.1"): ["bb"], ("colorama", "0.4.6"): ["cc"],
            ("nvidia-cublas-cu12", "12.4.5.8"): ["dd"], ("numpy", "2.4.4"): ["ee"]}


def _part(tmp_path, monkeypatch, body: str, **kw):
    m = _mod()
    (tmp_path / "lists").mkdir(exist_ok=True)
    (tmp_path / "lists" / "P_py3.13.txt").write_text(body, encoding="utf-8")
    monkeypatch.setattr(m, "LOCKS", tmp_path)
    return m, dict({"name": "P", "python": "3.13"}, **kw)


def test_lock_lines_carry_every_hash_and_linux_keeps_nvidia(tmp_path, monkeypatch) -> None:
    m, p = _part(tmp_path, monkeypatch, "torch==2.6.0\nclick==8.5.1\nnvidia-cublas-cu12==12.4.5.8\n", torch="t")
    lines, probs = m.part_lock(p, _cfg(), tmp_path, False, True, _sums())
    assert probs == [] and lines == ["click==8.5.1 --hash=sha256:bb", "nvidia-cublas-cu12==12.4.5.8 --hash=sha256:dd",
                                     "torch==2.6.0 --hash=sha256:aa"]


def test_windows_drops_linux_only_adds_colorama_and_refuses_cuda_torch(tmp_path, monkeypatch) -> None:
    m, p = _part(tmp_path, monkeypatch, "torch==2.6.0\nclick==8.5.1\nnvidia-cublas-cu12==12.4.5.8\n", torch="t")
    lines, probs = m.part_lock(p, _cfg(), tmp_path, True, False, _sums())
    assert probs == [] and [x.split()[0] for x in lines] == ["click==8.5.1", "colorama==0.4.6", "torch==2.6.0"]
    _, probs = m.part_lock(p, _cfg(), tmp_path, True, True, _sums())
    assert probs == ["CUDA torch for Windows has no measured hash yet (only the CPU build is measured)"]


def test_unlocked_cases_are_named(tmp_path, monkeypatch) -> None:
    m, p = _part(tmp_path, monkeypatch, "torch==2.5.0\nrequests==2.0\nnumpy==2.5.5\n", torch="t", add=["six==1.17.0"], gate3=True)
    (tmp_path / "g.txt").write_text("numpy==2.4.4\ntimm==1.0.27\n", encoding="utf-8")
    _, probs = m.part_lock(p, _cfg(), tmp_path, False, False, _sums())
    assert "parts.json adds six==1.17.0, the known-good list has nothing" in probs
    assert "parts.json pins torch==2.6.0, the known-good list has 2.5.0" in probs
    assert "gate-3 constraint numpy==2.4.4, the known-good list has 2.5.5" in probs
    assert not any("timm" in x for x in probs)  # a constraint for a package the part does not install is not a disagreement
    assert "requests==2.0 has no measured hash for Linux" in probs
    _, probs = m.part_lock(dict(p, name="Q"), _cfg(), tmp_path, False, False, _sums())
    assert probs == ["no known-good list measured yet (locks/lists/Q_py3.13.txt)"]


def test_unlocked_part_fails_and_is_never_installed(tmp_path: Path, capsys, monkeypatch) -> None:
    (tmp_path / "src" / "Conclave").mkdir(parents=True)
    m = _mod()
    (tmp_path / "locks" / "lists").mkdir(parents=True)
    for f in ("SHA256SUMS_win_amd64.txt", "SHA256SUMS_linux_x86_64.txt", "SHA256SUMS_sdist.txt"):
        (tmp_path / "locks" / f).write_text("", encoding="utf-8")
    monkeypatch.setattr(m, "LOCKS", tmp_path / "locks")  # launcher has no list here
    rc = m.main(["--src", str(tmp_path / "src"), "--envs", str(tmp_path / "envs"), "--only", "launcher"])
    out = capsys.readouterr().out
    assert rc == 1 and "FAIL  launcher not locked" in out and not (tmp_path / "envs").exists()


def test_locked_install_uses_require_hashes_and_no_deps(tmp_path, monkeypatch) -> None:
    m = _mod()
    seen = []
    monkeypatch.setattr(m, "run", lambda cmd, log, **k: seen.append([str(c) for c in cmd]) or 0)
    assert m.locked_install(Path("py"), [], tmp_path / "l.txt", tmp_path / "x.log") == 0 and seen == []
    m.locked_install(Path("py"), ["a==1 --hash=sha256:ff"], tmp_path / "l.txt", tmp_path / "x.log")
    assert seen[0][:6] == ["py", "-m", "pip", "install", "--require-hashes", "--no-deps"]
    assert (tmp_path / "l.txt").read_text(encoding="utf-8") == "a==1 --hash=sha256:ff\n"


# ---------------------------------------------------------------- reviewer 2: unpinned and broken never PASS
def _models(tmp_path, monkeypatch, model, rc=0):
    m = _mod()
    monkeypatch.setattr(m, "run", lambda *a, **k: rc)
    rep = m.Report()
    part = {"name": "P", "roots": ["spoke"], "models": [model]}
    m.models(rep, part, tmp_path, tmp_path, tmp_path / "envs", Path("py"), tmp_path / "x.log")
    return rep


def test_every_unpinned_model_step_fails(tmp_path, monkeypatch, capsys) -> None:
    for model in ({"step": "unpinned", "what": "w"}, {"step": "docling_download"}, {"step": "mineru_download"},
                  {"step": "spoke_script", "script": "s.py", "unpinned": "revision main"}, {"step": "nonsense"}):
        rep = _models(tmp_path, monkeypatch, model)
        assert rep.fails == 1, model
    assert "PASS" not in capsys.readouterr().out


def test_pinned_spoke_script_passes_only_when_it_works(tmp_path, monkeypatch) -> None:
    assert _models(tmp_path, monkeypatch, {"step": "spoke_script", "script": "s.py"}).fails == 0
    assert _models(tmp_path, monkeypatch, {"step": "spoke_script", "script": "s.py"}, rc=1).fails == 1
    assert _models(tmp_path, monkeypatch, {"step": "spoke_script", "script": "s.py", "expect": "missing.json"}).fails == 1


def _probe(tmp_path, monkeypatch, stdout):
    import subprocess
    m = _mod()
    monkeypatch.setattr(m, "scan_imports", lambda *a: (["pkg"], ["requests", "paddle"]))
    monkeypatch.setattr(m, "closure", lambda repo, roots: ["-e", str(repo / "spoke")])
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout, ""))
    rep = m.Report()
    m.probe(rep, {"name": "P", "roots": ["spoke"], "probe_ignore": {"paddle": "why"}}, tmp_path, Path("py"), set(), tmp_path / "l")
    return rep


def test_probe_import_failures_are_fail_rows(tmp_path, monkeypatch, capsys) -> None:
    rep = _probe(tmp_path, monkeypatch, '{"requests": "ModuleNotFoundError: No module named requests"}\n')
    out = capsys.readouterr().out
    assert rep.fails == 1 and "FAIL  P import" in out and "requests" in out
    assert _probe(tmp_path, monkeypatch, "Traceback ...\n").fails == 1
    assert _probe(tmp_path, monkeypatch, "{}\n").fails == 0


def test_skipped_folders_and_uncalled_adapters_are_printed(tmp_path, monkeypatch, capsys) -> None:
    import subprocess
    m = _mod()
    seen = {}
    monkeypatch.setattr(m, "scan_imports", lambda d, l, skip=(), mods=(): (seen.setdefault("skip", skip), ([], []))[1])
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "{}\n", ""))
    rep = m.Report()
    part = {"name": "P", "roots": ["."], "probe_skip": {"tools/": "runs elsewhere"}, "no_caller": ["conclave_x"]}
    m.probe(rep, part, tmp_path, Path("py"), set(), tmp_path / "l")
    out = capsys.readouterr().out
    assert seen["skip"] == ("tools/",)  # the folder really is skipped
    assert "INFO  P not probed" in out and "tools/: runs elsewhere" in out  # and never silently
    assert "INFO  P conclave_x" in out and "no shipped caller yet" in out and rep.fails == 0


def test_probe_covers_every_in_repo_distribution_the_part_installs(tmp_path, monkeypatch) -> None:
    import subprocess
    m = _mod()
    seen = {}
    monkeypatch.setattr(m, "closure", lambda repo, roots: ["-e", str(repo / "root_spoke"), "-e", str(repo / "pulled_in")])
    monkeypatch.setattr(m, "scan_imports", lambda d, l, skip=(), mods=(): (seen.setdefault("dirs", d), ([], []))[1])
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "{}\n", ""))
    m.probe(m.Report(), {"name": "P", "roots": ["root_spoke"]}, tmp_path, Path("py"), set(), tmp_path / "l")
    assert seen["dirs"] == [tmp_path / "root_spoke", tmp_path / "pulled_in"]


def test_not_reached_vendored_modules_are_skipped_and_printed(tmp_path, capsys) -> None:
    m = _mod()
    d = tmp_path / "conclave_vendor_obsidian"
    (d / "src" / "obsidian").mkdir(parents=True)
    (d / "src" / "obsidian" / "__init__.py").write_text("")
    (d / "src" / "obsidian" / "kdf.py").write_text("import argon2\n")
    (d / "src" / "obsidian" / "egress.py").write_text("import jsonschema\n")
    _, third = m.scan_imports([d], set(), (), ("obsidian.kdf",))
    assert "argon2" not in third and "jsonschema" in third  # the skipped module's imports are not demanded
    _, third = m.scan_imports([d], set())
    assert "argon2" in third  # and without the entry they are
    assert 'or any(mi.name == k or mi.name.startswith(k + ".") for k in skip)' in m.PROBE  # submodule walk skips it too


def test_src_layout_scans_only_what_is_installed(tmp_path) -> None:
    m = _mod()
    d = tmp_path / "conclave_vendor_locutus"
    (d / "src" / "locutus").mkdir(parents=True)
    (d / "src" / "locutus" / "__init__.py").write_text("import jsonschema\n")
    (d / "tools").mkdir()
    (d / "tools" / "driver.py").write_text("import reportlab\n")  # loose script, not in the installed package
    _, third = m.scan_imports([d], set())
    assert third == ["jsonschema"]


def test_test_env_part_runs_its_tests_in_a_separate_locked_env_then_deletes_it(tmp_path, monkeypatch, capsys) -> None:
    import subprocess
    m = _mod()
    lists = tmp_path / "locks" / "lists"
    lists.mkdir(parents=True)
    (lists / "_te.txt").write_text("click==8.5.1\n")
    monkeypatch.setattr(m, "LOCKS", tmp_path / "locks")
    monkeypatch.setattr(m, "load_sums", lambda win: _sums())
    m.CFG_LOCK.update({"lock": PARTS["lock"]})
    repo = tmp_path / "repo"
    (repo / "spoke" / "tests").mkdir(parents=True)
    calls = []
    def fake_run(cmd, log, cwd=None, env=None):
        calls.append([str(c) for c in cmd])
        if cmd[1:3] == ["-m", "venv"]:
            m.env_python(Path(cmd[3])).parent.mkdir(parents=True, exist_ok=True)
        return 0
    monkeypatch.setattr(m, "run", fake_run)
    monkeypatch.setattr(m, "base_python", lambda v: ["py"])
    monkeypatch.setattr(m, "closure", lambda r, roots: ["-e", str(r / "spoke")])
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    part = {"name": "P", "roots": ["spoke"], "python": "3.13", "test_env": {"list": "_te.txt", "roots": ["spoke"]}}
    (tmp_path / "envs" / "_logs").mkdir(parents=True)
    rep = m.Report()
    m.own_tests(rep, part, repo, Path("main_py"), tmp_path / "envs", tmp_path / "l", "done", "status")
    out = capsys.readouterr().out
    test_env_py = str(m.env_python(tmp_path / "envs" / "P-test"))
    assert any(c[0] == test_env_py and "pytest" in c for c in calls)  # tests ran in the test env
    assert not any(c[0] == "main_py" for c in calls)  # never in the installed part's env
    assert "PASS  P" in out and "its locked test environment" in out
    assert not (tmp_path / "envs" / "P-test").exists()  # deleted after the run


def test_workbench_run_button_points_at_the_harness_env(tmp_path, monkeypatch, capsys) -> None:
    import subprocess
    m = _mod()
    envs = tmp_path / "envs"
    rep = m.Report()
    part = {"name": "workbench", "harness_from": "harness_adapters"}
    m.harness(rep, part, envs, Path("wb_py"), tmp_path / "log")
    assert rep.fails == 1 and "environment is not built" in capsys.readouterr().out  # never silently blank
    hp = m.env_python(envs / "harness_adapters")
    hp.parent.mkdir(parents=True)
    hp.write_text("")
    seen = []
    for out, rc, fails in (("WORKBENCH-HARNESS: OK /x (written to /s)\n", 0, 0), ("WORKBENCH-HARNESS: FAIL already set\n", 1, 1)):
        monkeypatch.setattr(m.subprocess, "run", lambda a, **k: (seen.append(a), subprocess.CompletedProcess(a, rc, out, ""))[1])
        rep = m.Report()
        m.harness(rep, part, envs, Path("wb_py"), tmp_path / "log")
        assert rep.fails == fails
    assert seen[0][0] == Path("wb_py") and seen[0][-1] == str(hp)  # run by the Workbench's Python, given the harness one
    parts = {p["name"]: p for p in PARTS["parts"]}
    assert parts["workbench"]["harness_from"] == "harness_adapters"


def test_workbench_harness_script_never_overwrites_a_chosen_value() -> None:
    src = (NESTEGG / "workbench_harness.py").read_text(encoding="utf-8")
    assert "if current is None:\n        save_user_value" in src  # writes only when blank
    assert "harness_python_reader(schema, layers)()" in src  # reads back through the Workbench's own resolver
    assert '"-m", "conclave_harness_adapters.pipeline_run", "--help"' in src


def test_engine_file_is_read_and_must_equal_the_saved_list(tmp_path, monkeypatch, capsys) -> None:
    m = _mod()
    f = tmp_path / "engine_requirements.txt"
    f.write_text("# header\nmineru[core]==3.2.2 \\\n    --hash=sha256:aa \\\n    --hash=sha256:bb\nsix==1.17.0 --hash=sha256:cc\n")
    assert m.read_engine_file(f) == {"mineru": "3.2.2", "six": "1.17.0"}
    assert m.read_engine_file(tmp_path / "missing.txt") is None
    lists = tmp_path / "locks" / "lists"
    lists.mkdir(parents=True)
    (lists / "_mineru_cli_py3.12.txt").write_text("mineru==3.2.2\nsix==1.16.0\n")  # disagrees on six
    monkeypatch.setattr(m, "LOCKS", tmp_path / "locks")
    (tmp_path / "src" / "Conclave" / "s").mkdir(parents=True)
    (tmp_path / "src" / "Conclave" / "s" / "engine_requirements.txt").write_text(f.read_text())
    part = {"name": "MinerU", "repo": "Conclave", "side_env": {"name": "mineru", "python": "3.12", "packages": [],
            "check": ["mineru", "--help"], "engine_file": "s/engine_requirements.txt"}}
    rep = m.Report()
    m.side_envs(rep, part, tmp_path / "src", tmp_path / "envs", tmp_path / "l", Path("py"))
    out = capsys.readouterr().out
    assert rep.fails == 1 and "disagree" in out  # never built from either when the two differ


def test_engine_file_linux_markers_must_be_dropped_on_windows(tmp_path, monkeypatch, capsys) -> None:
    # the MarkerPdf file (PA-2) marks four packages `; sys_platform == "linux"` (no Windows wheel)
    m = _mod()
    body = ('six==1.17.0 \\\n    --hash=sha256:aa\n'
            'triton==3.9.0 ; sys_platform == "linux" \\\n    --hash=sha256:bb\n'
            'odd-pkg==1.0 ; sys_platform == "linux" \\\n    --hash=sha256:cc\n')
    f = tmp_path / "e.txt"
    f.write_text(body)
    assert m.read_engine_file(f) == {"six": "1.17.0", "triton": "3.9.0", "odd-pkg": "1.0"}
    assert m.engine_linux_only(f) == {"triton", "odd-pkg"}
    lists = tmp_path / "locks" / "lists"
    lists.mkdir(parents=True)
    (lists / "_marker_cli_py3.13.txt").write_text("six==1.17.0\ntriton==3.9.0\nodd-pkg==1.0\n")
    monkeypatch.setattr(m, "LOCKS", tmp_path / "locks")
    m.CFG_LOCK.update({"linux_only": "^(nvidia-.*|triton)$"})
    (tmp_path / "src" / "Conclave" / "s").mkdir(parents=True)
    (tmp_path / "src" / "Conclave" / "s" / "engine_requirements.txt").write_text(body)
    part = {"name": "MarkerPdf", "repo": "Conclave", "side_env": {"name": "marker", "python": "3.13", "packages": [],
            "check": ["marker_single", "--help"], "engine_file": "s/engine_requirements.txt"}}
    rep = m.Report()
    m.side_envs(rep, part, tmp_path / "src", tmp_path / "envs", tmp_path / "l", Path("py"))
    out = capsys.readouterr().out
    assert rep.fails == 1 and "odd-pkg" in out and "Linux-only" in out
    # the other direction: the rule drops a package on Windows that the spoke's file installs there
    m.CFG_LOCK.update({"linux_only": "^(nvidia-.*|triton|odd-pkg|six)$"})
    rep = m.Report()
    m.side_envs(rep, part, tmp_path / "src", tmp_path / "envs", tmp_path / "l", Path("py"))
    out = capsys.readouterr().out
    assert rep.fails == 1 and "drops ['six']" in out


def test_engine_file_markers_are_honoured_per_platform(tmp_path, monkeypatch, capsys) -> None:
    m = _mod()
    body = ('six==1.17.0 \\\n    --hash=sha256:aa\n'
            'triton==3.9.0 ; sys_platform == "linux" \\\n    --hash=sha256:bb\n'
            'colorama==0.4.6 ; sys_platform == "win32" \\\n    --hash=sha256:cc\n')
    f = tmp_path / "e.txt"
    f.write_text(body)
    assert m.engine_markers(f) == {"triton": "linux", "colorama": "win32"}
    f.write_text(body + 'odd==1 ; python_version < "3.10" \\\n    --hash=sha256:dd\n')
    assert m.engine_markers(f)["odd"].startswith("?")
    lists = tmp_path / "locks" / "lists"
    lists.mkdir(parents=True)
    (lists / "_marker_cli_py3.13.txt").write_text("six==1.17.0\ntriton==3.9.0\ncolorama==0.4.6\n")
    monkeypatch.setattr(m, "LOCKS", tmp_path / "locks")
    m.CFG_LOCK.update({"linux_only": "^(nvidia-.*|cuda-.*|triton)$"})
    (tmp_path / "src" / "Conclave" / "s").mkdir(parents=True)
    (tmp_path / "src" / "Conclave" / "s" / "engine_requirements.txt").write_text(body)
    part = {"name": "MarkerPdf", "repo": "Conclave", "side_env": {"name": "marker", "python": "3.13", "packages": [],
            "check": ["marker_single", "--help"], "engine_file": "s/engine_requirements.txt"}}
    seen = {}
    monkeypatch.setattr(m, "lock_reqs", lambda pins, *a: (seen.setdefault(m.WIN, dict(pins)), ([], ["stop"]))[1])
    monkeypatch.setattr(m, "load_sums", lambda win: {})
    for win in (True, False):
        monkeypatch.setattr(m, "WIN", win)
        m.side_envs(m.Report(), part, tmp_path / "src", tmp_path / "envs", tmp_path / "l", Path("py"))
    assert seen[True] == {"six": "1.17.0", "colorama": "0.4.6"}  # Windows: linux lines out
    assert seen[False] == {"six": "1.17.0", "triton": "3.9.0"}  # Linux: win32 lines out
    (tmp_path / "src" / "Conclave" / "s" / "engine_requirements.txt").write_text(f.read_text())
    (lists / "_marker_cli_py3.13.txt").write_text("six==1.17.0\ntriton==3.9.0\ncolorama==0.4.6\nodd==1\n")
    rep = m.Report()
    m.side_envs(rep, part, tmp_path / "src", tmp_path / "envs", tmp_path / "l", Path("py"))
    assert rep.fails == 1 and "does not understand" in capsys.readouterr().out


def test_locutus_rulings_plugin_is_in_every_part_that_loads_it() -> None:
    # entry-point plugin: ReviewConsole wraps every Console with it, the Bridge refuses repeats without it
    parts = {p["name"]: p for p in json.loads((NESTEGG / "parts.json").read_text(encoding="utf-8"))["parts"]}
    for n in ("harness_adapters", "apexbridge", "sequoia_bridge", "launcher", "workbench", "reviewconsole"):
        assert "conclave_integration_locutus_rulings" in parts[n]["roots"], n


def test_pip_check_problem_fails_the_part(tmp_path, monkeypatch, capsys) -> None:
    import subprocess
    m = _mod()
    src = tmp_path / "src"
    (src / "atrium").mkdir(parents=True)
    monkeypatch.setattr(m, "base_python", lambda v: ["py"])
    monkeypatch.setattr(m, "run", lambda *a, **k: 0)
    monkeypatch.setattr(m, "closure", lambda repo, roots: ["-e", str(repo)])
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "x 1.0 requires y, which is not installed.\n", ""))
    rep = m.Report()
    part = {"name": "atrium", "repo": "atrium", "roots": ["."], "python": "3.13"}
    m.build_part(rep, part, PARTS, src, tmp_path / "envs", False, False, set(), {})
    out = capsys.readouterr().out
    assert rep.fails == 1 and "FAIL  atrium pip check" in out and "requires y" in out
    assert "PASS  atrium " not in out


def test_cuda_build_from_a_pod_freeze(tmp_path, monkeypatch) -> None:
    m, p = _part(tmp_path, monkeypatch, "torch==2.6.0+cu124\n", torch="t")
    lines, probs = m.part_lock(p, _cfg(), tmp_path, True, False, _sums())  # Windows, no NVIDIA card: PyPI CPU build
    assert probs == [] and lines == ["torch==2.6.0 --hash=sha256:aa"]
    _, probs = m.part_lock(p, _cfg(), tmp_path, False, True, _sums())  # Linux: the +cu124 file itself must be hashed
    assert probs == ["torch==2.6.0+cu124 has no measured hash for Linux"]
    sums = {**_sums(), ("torch", "2.6.0+cu124"): ["cc"]}
    lines, probs = m.part_lock(p, _cfg(), tmp_path, False, True, sums)  # Linux, hashed: PyTorch's index, hash-checked
    assert probs == [] and lines == ["--extra-index-url https://download.pytorch.org/whl/cu124", "torch==2.6.0+cu124 --hash=sha256:cc"]


def test_linux_cuda_hashes_come_from_the_saved_cu124_list() -> None:
    m = _mod()  # real locks/ folder, not a test copy
    linux, win = m.load_sums(False), m.load_sums(True)
    for dv in (("torch", "2.6.0+cu124"), ("torchvision", "0.21.0+cu124"), ("torch", "2.4.1+cu124"), ("torchvision", "0.19.1+cu124")):
        assert dv in linux and dv not in win, dv  # the GPU files are Linux-only; Windows never gets them
    assert linux[("torch", "2.6.0+cu124")][0].startswith("0f3bc53c988c")


def test_engine_without_list_or_with_wrong_pin_fails(tmp_path, monkeypatch, capsys) -> None:
    m, _ = _part(tmp_path, monkeypatch, "")
    for f in ("SHA256SUMS_win_amd64.txt", "SHA256SUMS_linux_x86_64.txt", "SHA256SUMS_sdist.txt"):
        (tmp_path / f).write_text("", encoding="utf-8")
    m.CFG_LOCK.update(_cfg())
    se = {"name": "eng", "python": "3.13", "packages": ["tool==2.0"], "check": ["tool", "--help"]}
    rep = m.Report()
    m.side_envs(rep, {"name": "P", "side_env": se}, tmp_path, tmp_path / "envs", tmp_path / "l", Path("py"))
    (tmp_path / "lists" / "_eng_cli_py3.13.txt").write_text("tool==1.0\n", encoding="utf-8")
    m.side_envs(rep, {"name": "P", "side_env": se}, tmp_path, tmp_path / "envs", tmp_path / "l", Path("py"))
    out = capsys.readouterr().out
    assert rep.fails == 3 and "no known-good list" in out and "the engine needs tool==2.0, the known-good list has 1.0" in out
    assert not (tmp_path / "envs").exists()


def _built(tmp_path, monkeypatch, part, status, tools=None, test_rc=0):
    import subprocess
    m = _mod()
    src = tmp_path / "src"
    (src / "Conclave" / "conclave_x" / "tests").mkdir(parents=True)
    locks = tmp_path / "locks"
    (locks / "lists").mkdir(parents=True)
    (locks / "LIST_STATUS.txt").write_text(f"{part['name']}_py3.13.txt: {status}\n", encoding="utf-8")
    (locks / "lists" / f"{part['name']}_py3.13.txt").write_text("", encoding="utf-8")
    for f in ("SHA256SUMS_win_amd64.txt", "SHA256SUMS_linux_x86_64.txt", "SHA256SUMS_sdist.txt"):
        (locks / f).write_text("ab  pytest-9.0-py3-none-any.whl\n" if tools else "", encoding="utf-8")
    if tools:
        (locks / "lists" / "_test_tools_py3.13.txt").write_text("pytest==9.0\n", encoding="utf-8")
    monkeypatch.setattr(m, "LOCKS", locks)
    m.CFG_LOCK.update(PARTS)
    monkeypatch.setattr(m, "base_python", lambda v: ["py"])
    monkeypatch.setattr(m, "run", lambda cmd, *a, **k: test_rc if "pytest" in map(str, cmd) and "-q" in map(str, cmd) else 0)
    monkeypatch.setattr(m, "closure", lambda repo, roots: [])
    monkeypatch.setattr(m, "probe", lambda *a, **k: None)
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    rep = m.Report()
    m.build_part(rep, dict({"repo": "Conclave", "python": "3.13"}, **part), PARTS, src, tmp_path / "envs", False, False, set(), None)
    return rep


def test_reader_on_an_unmatched_list_is_held_never_passed(tmp_path, monkeypatch) -> None:
    rep = _built(tmp_path, monkeypatch, {"name": "R", "roots": ["conclave_lens_x"]}, "RESOLVED TODAY, NOT MEASURED")
    assert (rep.holds, rep.passes, rep.fails) == (1, 0, 0)


def test_reader_on_a_matched_list_passes(tmp_path, monkeypatch) -> None:
    rep = _built(tmp_path, monkeypatch, {"name": "R", "roots": ["conclave_lens_x"]}, "MATCHED to pod freeze f.txt")
    assert (rep.holds, rep.passes, rep.fails) == (0, 1, 0)


def test_non_reader_needs_its_own_tests_under_the_locked_set(tmp_path, monkeypatch) -> None:
    part = {"name": "N", "roots": ["conclave_x"]}
    assert _built(tmp_path / "a", monkeypatch, part, "RESOLVED TODAY").holds == 1  # no locked test tools
    assert _built(tmp_path / "b", monkeypatch, part, "RESOLVED TODAY", tools=True).passes == 1
    assert _built(tmp_path / "c", monkeypatch, part, "RESOLVED TODAY", tools=True, test_rc=1).fails == 1


# ---- reader record (envs/reader_envs.json): what LensRunner's launcher needs to start each reader in its own Python
def _fake_env(envs: Path, name: str, *, lens: bool = True, contracts: bool = True) -> None:
    import subprocess
    import sysconfig
    env = envs / name
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(env)], check=True)
    rel = Path(sysconfig.get_path("purelib")).relative_to(sysconfig.get_path("data"))
    site = env / rel
    if lens:
        d = site / "conclave_lens_fake-0.1.0.dist-info"
        d.mkdir(parents=True)
        (d / "METADATA").write_text("Metadata-Version: 2.1\nName: conclave-lens-fake\nVersion: 0.1.0\n", encoding="utf-8")
        (d / "entry_points.txt").write_text("[conclave.lenses]\nfake_lens = conclave_lens_fake:FakeLens\n", encoding="utf-8")
    if contracts:
        d = site / "conclave_contracts-1.2.3.dist-info"
        d.mkdir(parents=True)
        (d / "METADATA").write_text("Metadata-Version: 2.1\nName: conclave-contracts\nVersion: 1.2.3\n", encoding="utf-8")


def _reader_part(name: str) -> dict:
    return {"name": name, "roots": [f"conclave_lens_{name.lower()}"], "python": f"{sys.version_info[0]}.{sys.version_info[1]}"}


def test_reader_record_measures_the_readers_own_python(tmp_path, monkeypatch) -> None:
    m = _mod()
    monkeypatch.setattr(m, "LOCKS", tmp_path / "locks")
    _fake_env(tmp_path, "Fake")
    rep = m.Report()
    e = m.reader_entry(rep, _reader_part("Fake"), tmp_path, "PASS")
    assert rep.fails == 0 and e["status"] == "PASS"
    assert e["lens_ids"] == ["fake_lens"] and e["contracts_version"] == "1.2.3" and e["size_bytes"] > 0
    assert e["host_selftest"].startswith("NOT_RUN")  # never claimed until the reader host has answered


def test_reader_record_fails_loudly(tmp_path, monkeypatch, capsys) -> None:
    m = _mod()
    monkeypatch.setattr(m, "LOCKS", tmp_path / "locks")
    _fake_env(tmp_path, "NoLens", lens=False)
    _fake_env(tmp_path, "NoContracts", contracts=False)
    rep = m.Report()
    assert m.reader_entry(rep, _reader_part("NoLens"), tmp_path, "PASS")["status"] == "FAIL"
    assert m.reader_entry(rep, _reader_part("NoContracts"), tmp_path, "PASS")["status"] == "FAIL"
    assert m.reader_entry(rep, _reader_part("Missing"), tmp_path, "PASS")["status"] == "FAIL"
    wrong = dict(_reader_part("NoLens"), python="2.7")
    assert m.reader_entry(rep, wrong, tmp_path, "PASS")["status"] == "FAIL"
    out = capsys.readouterr().out
    for s in ("no reader is registered", "conclave-contracts is not installed", "its Python is missing", "the build declares 2.7"):
        assert s in out
    assert rep.fails >= 4


def test_reader_record_file_replaces_rebuilt_parts_only(tmp_path, monkeypatch) -> None:
    m = _mod()
    monkeypatch.setattr(m, "LOCKS", tmp_path / "locks")
    m.write_reader_envs(tmp_path, [{"part": "A", "status": "PASS"}, {"part": "B", "status": "PASS"}])
    out = m.write_reader_envs(tmp_path, [{"part": "B", "status": "FAIL"}])  # a failed rebuild never keeps its last good entry
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["schema"] == 1 and doc["provisional"] is False and {e["part"]: e["status"] for e in doc["readers"]} == {"A": "PASS", "B": "FAIL"}
    assert not out.with_suffix(".tmp").exists()


def _fake_run_env(envs: Path, host_body: str | None) -> None:
    import sysconfig
    _fake_env(envs, "harness_adapters", lens=False)
    rel = Path(sysconfig.get_path("purelib")).relative_to(sysconfig.get_path("data"))
    pkg = envs / "harness_adapters" / rel / "conclave_lensrunner"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    if host_body is not None:
        (pkg / "reader_host.py").write_text(host_body, encoding="utf-8")


_HOST = """import json, sys
ids = [sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--lens-id"]
ok = {ok}
print(json.dumps({{"reader_host_selftest": 1, "protocol": 1, "lens_ids": ids if ok else [], "ok": ok,
                  "import_failures": {{}} if ok else {{i: "ImportError: boom" for i in ids}}}}))
sys.exit(0 if ok else 1)
"""


def test_reader_host_selftest_pass_fail_and_not_run(tmp_path, monkeypatch, capsys) -> None:
    m = _mod()
    monkeypatch.setattr(m, "LOCKS", tmp_path / "locks")
    for case, body in (("pass", _HOST.format(ok=True)), ("fail", _HOST.format(ok=False)), ("nohost", None)):
        envs = tmp_path / case
        _fake_env(envs, "Fake")
        _fake_run_env(envs, body)
        rep = m.Report()
        e = m.reader_entry(rep, _reader_part("Fake"), envs, "PASS")
        m.host_selftest(rep, [e], envs)
        out = capsys.readouterr().out
        if case == "pass":
            assert e["status"] == "PASS" and e["host_selftest"]["ok"] is True and rep.fails == 0
        elif case == "fail":
            assert e["status"] == "FAIL" and "ImportError: boom" in out and rep.fails == 1
        else:
            assert e["status"] == "PASS" and e["host_selftest"].startswith("NOT_RUN") and "0.1.0a2" in out


def test_one_command_install_runs_both_phases_in_order_and_never_assumes_yes() -> None:
    """Jake 11/22: one command for all the parts. Static check (no PowerShell on CI's Linux runner)."""
    cmd = (NESTEGG / "Install AdAstra.cmd").read_text(encoding="utf-8")
    ps = (NESTEGG / "Install-AdAstra.ps1").read_text(encoding="utf-8")
    assert "Install-AdAstra.ps1" in cmd
    assert ps.index("Install-Prereqs.ps1") < ps.index("install_parts.py")
    assert "AssumeYes" not in ps.split("param(", 1)[1]  # winget agreements and security boxes stay the person's
    assert "NESTEGG-PREREQS: PASS" in ps and "phase 2 not started" in ps
    for line in ("NESTEGG-INSTALL: PASS", "NESTEGG-INSTALL: HOLD", "NESTEGG-INSTALL: FAIL"):
        assert line in ps
    for verb in ("Remove-Item", "Set-ItemProperty", "setx", "keyring"):
        assert verb not in ps


def test_learning_folders_create_only_and_never_touch_existing(tmp_path, capsys) -> None:
    m = _mod()
    cfg = {"learning": PARTS_LEARNING}
    rep = m.Report()
    m.learning_folders(rep, cfg, tmp_path, False)
    for aim in PARTS_LEARNING["aims"]:
        for sub in PARTS_LEARNING["subdirs"]:
            assert (tmp_path / "learning" / aim / sub).is_dir()
        assert (tmp_path / "learning" / aim / "manifest.jsonl").read_text(encoding="utf-8") == ""
    kept = tmp_path / "learning" / "sequoia"
    (kept / "manifest.jsonl").write_text('{"sha256": "x"}\n', encoding="utf-8")
    (kept / "README.md").write_text("mine", encoding="utf-8")
    (kept / "approved" / "item.json").write_text("{}", encoding="utf-8")
    m.learning_folders(rep, cfg, tmp_path, False)  # repair / upgrade
    assert (kept / "manifest.jsonl").read_text(encoding="utf-8") == '{"sha256": "x"}\n'
    assert (kept / "README.md").read_text(encoding="utf-8") == "mine" and (kept / "approved" / "item.json").exists()
    assert rep.fails == 0 and "0 new item(s)" in capsys.readouterr().out
    m.learning_folders(rep, {}, tmp_path, False)
    assert rep.fails == 1  # undeclared folder list fails loudly (SET-9)


PARTS_LEARNING = json.loads((NESTEGG / "parts.json").read_text(encoding="utf-8"))["learning"]


def test_every_env_gets_a_root_marker_before_any_verdict() -> None:
    """Installed programs (e.g. Obsidian's learning-folder button) find the install root from <env>/adastra.json."""
    src = (NESTEGG / "install_parts.py").read_text(encoding="utf-8")
    body = src[src.index("def build_part("):src.index("def side_envs(")]
    assert body.index('"adastra.json"') < body.index('rep.row("PASS", name')
    assert '"install_root"' in body and 'INSTALL_ROOT["root"] = a.root or a.envs.parent' in src


def test_locked_files_come_from_the_saved_copy_first(tmp_path: Path, monkeypatch) -> None:
    """Decision 30 A: a wheel in the home copy is used (named for pip) and pip runs with --no-index when all are found."""
    import hashlib
    m = _mod()
    sc = m._saved_copies()
    whl = tmp_path / "demo-1.0-py3-none-any.whl"
    whl.write_bytes(b"wheel bytes")
    h = hashlib.sha256(b"wheel bytes").hexdigest()
    sc.split(whl, tmp_path / "root" / "saved", 2_000_000_000)
    m.INSTALL_ROOT["root"] = tmp_path / "root"
    monkeypatch.setattr(m, "saved_file_names", lambda: {h: whl.name})
    envs = tmp_path / "root" / "envs"
    (envs / "_logs").mkdir(parents=True)
    calls = []
    monkeypatch.setattr(m, "run", lambda cmd, log, **k: calls.append([str(c) for c in cmd]) or 0)
    rc = m.locked_install(Path("py"), [f"demo==1.0 --hash=sha256:{h}"], envs / "_logs" / "x.lock.txt", envs / "_logs" / "x.txt")
    assert rc == 0 and (envs / "_wheelhouse" / whl.name).read_bytes() == b"wheel bytes"
    assert "--no-index" in calls[0] and str(envs / "_wheelhouse") in calls[0]


def test_no_saved_copy_means_plain_hash_checked_install(tmp_path: Path, monkeypatch) -> None:
    m = _mod()
    m.INSTALL_ROOT["root"] = tmp_path  # no saved\INDEX.json, release repo not chosen
    calls = []
    monkeypatch.setattr(m, "run", lambda cmd, log, **k: calls.append([str(c) for c in cmd]) or 0)
    (tmp_path / "envs" / "_logs").mkdir(parents=True)
    m.locked_install(Path("py"), ["demo==1.0 --hash=sha256:" + "0" * 64], tmp_path / "envs" / "_logs" / "l.txt", tmp_path / "envs" / "_logs" / "o.txt")
    assert "--no-index" not in calls[0] and "--find-links" not in calls[0]


def test_reader_models_placed_from_saved_copy_when_every_file_is_pinned(tmp_path: Path, monkeypatch) -> None:
    m = _mod()
    sc = m._saved_copies()
    f = tmp_path / "w.safetensors"
    f.write_bytes(b"weights")
    e = sc.split(f, tmp_path / "root" / "saved", 2_000_000_000)
    man = {"readers": {"TableSurgeon": {"models": {
        "ok": {"source": "huggingface", "repo_id": "o/ok", "revision": "a" * 40, "files": {"w.safetensors": {"bytes": 7, "sha256": e["sha256"]}}},
        "unpinned_file": {"source": "huggingface", "repo_id": "o/no", "revision": "b" * 40, "files": {"config.json": {"bytes": 2, "sha256": None}}}}}}}
    (tmp_path / "nest").mkdir()
    (tmp_path / "nest" / "models_pinned.json").write_text(json.dumps(man))
    monkeypatch.setattr(m, "HERE", tmp_path / "nest")
    monkeypatch.setattr(m, "_saved_copies", lambda: sc)
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    m.INSTALL_ROOT["root"] = tmp_path / "root"
    rows = []
    rep = type("R", (), {"row": lambda self, s, w, d: rows.append((s, w, d))})()
    m.saved_models(rep, {"name": "TableSurgeon"}, tmp_path / "root" / "envs")
    assert (tmp_path / "hub" / "models--o--ok" / "snapshots" / ("a" * 40) / "w.safetensors").read_bytes() == b"weights"
    assert rows == [("INFO", "TableSurgeon saved models", "1 of 2 Hugging Face models placed from a saved copy: o/ok")]


def test_learning_folder_adders_carry_atrium_learning() -> None:
    """Learning-folders thread (Atrium #64 merged e53727a): workbench and obsidian add to learning folders (SET-9)."""
    by = {p["name"]: p for p in PARTS["parts"]}
    for n in ("workbench", "obsidian"):
        assert "atrium" in by[n].get("add_repos", []) and "atrium_learning" in by[n].get("must_import", [])


def _corrupt_home_copy(tmp_path: Path, sc, data: bytes) -> tuple[Path, str]:
    """Save `data` in the home copy, then change the stored bytes (same name): the saved copy no longer matches."""
    import hashlib
    f = tmp_path / "src.bin"
    f.write_bytes(data)
    h = hashlib.sha256(data).hexdigest()
    sc.split(f, tmp_path / "root" / "saved", 2_000_000_000)
    (tmp_path / "root" / "saved" / h).write_bytes(b"tampered " + data)
    return f, h


def test_changed_saved_package_copy_is_a_warn_row_on_screen(tmp_path: Path, monkeypatch, capsys) -> None:
    """Reviewer 3 on #67 (no silent failure): a saved wheel whose bytes changed is a WARN row naming it, not only a
    log line; the install still goes on from the original index under --require-hashes."""
    m = _mod()
    sc = m._saved_copies()
    _, h = _corrupt_home_copy(tmp_path, sc, b"wheel bytes")
    m.INSTALL_ROOT["root"] = tmp_path / "root"
    monkeypatch.setattr(m, "saved_file_names", lambda: {h: "demo-1.0-py3-none-any.whl"})
    envs = tmp_path / "root" / "envs"
    (envs / "_logs").mkdir(parents=True)
    calls = []
    monkeypatch.setattr(m, "run", lambda cmd, log, **k: calls.append([str(c) for c in cmd]) or 0)
    m.locked_install(Path("py"), [f"demo==1.0 --hash=sha256:{h}"], envs / "_logs" / "x.lock.txt", envs / "_logs" / "x.txt")
    out = capsys.readouterr().out
    assert any(ln.startswith("WARN") and "saved copy changed" in ln and "demo-1.0-py3-none-any.whl" in ln
               and "home copy" in ln for ln in out.splitlines()), out
    assert "--no-index" not in calls[0] and not (envs / "_wheelhouse" / "demo-1.0-py3-none-any.whl").exists()


def test_changed_saved_model_copy_is_a_warn_row(tmp_path: Path, monkeypatch) -> None:
    """Reviewer 3 on #67: the model path used to throw the refusal away and show only 'INFO 0 of 1 placed'."""
    m = _mod()
    sc = m._saved_copies()
    _, h = _corrupt_home_copy(tmp_path, sc, b"weights")
    man = {"readers": {"TableSurgeon": {"models": {"ok": {"source": "huggingface", "repo_id": "o/ok", "revision": "a" * 40,
                                                          "files": {"w.safetensors": {"bytes": 7, "sha256": h}}}}}}}
    (tmp_path / "nest").mkdir()
    (tmp_path / "nest" / "models_pinned.json").write_text(json.dumps(man))
    monkeypatch.setattr(m, "HERE", tmp_path / "nest")
    monkeypatch.setattr(m, "_saved_copies", lambda: sc)
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    m.INSTALL_ROOT["root"] = tmp_path / "root"
    rows = []
    rep = type("R", (), {"row": lambda self, s, w, d: rows.append((s, w, d))})()
    m.saved_models(rep, {"name": "TableSurgeon"}, tmp_path / "root" / "envs")
    warns = [r for r in rows if r[0] == "WARN"]
    assert len(warns) == 1 and warns[0][1] == "TableSurgeon saved copy changed"
    assert "o/ok/w.safetensors" in warns[0][2] and "home copy" in warns[0][2] and "not the pinned" in warns[0][2]
    assert rows[-1][0] == "INFO" and "0 of 1" in rows[-1][2]


def test_trocr_saved_copy_refusal_is_not_thrown_away() -> None:
    src = (Path(__file__).resolve().parent.parent / "tools" / "nestegg" / "htrlens_models.py").read_text(encoding="utf-8")
    assert "say=lambda m: None" not in src and '"TrOCR saved copy changed"' in src


def test_reader_with_its_own_model_folder_gets_files_there(tmp_path: Path, monkeypatch) -> None:
    """im2latex loads from CONCLAVE_IM2LATEX_MODEL_DIR (else ~/.conclave/...), not the Hugging Face cache."""
    m = _mod()
    sc = m._saved_copies()
    f = tmp_path / "model.safetensors"
    f.write_bytes(b"im2latex weights")
    e = sc.split(f, tmp_path / "root" / "saved", 2_000_000_000)
    man = {"readers": {"FormulaLens": {"models": {"im2latex": {
        "source": "huggingface", "repo_id": "o/im2latex", "revision": "c" * 40,
        "local_dir": {"env": "TEST_IM2LATEX_DIR", "default": "~/never-used"},
        "files": {"model.safetensors": {"bytes": 16, "sha256": e["sha256"]}}}}}}}
    (tmp_path / "nest").mkdir()
    (tmp_path / "nest" / "models_pinned.json").write_text(json.dumps(man))
    monkeypatch.setattr(m, "HERE", tmp_path / "nest")
    monkeypatch.setattr(m, "_saved_copies", lambda: sc)
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    monkeypatch.setenv("TEST_IM2LATEX_DIR", str(tmp_path / "im2latex"))
    m.INSTALL_ROOT["root"] = tmp_path / "root"
    rows = []
    rep = type("R", (), {"row": lambda self, s, w, d: rows.append((s, w, d))})()
    m.saved_models(rep, {"name": "FormulaLens"}, tmp_path / "root" / "envs")
    assert (tmp_path / "im2latex" / "model.safetensors").read_bytes() == b"im2latex weights"
    assert not (tmp_path / "hub").exists()
    assert rows == [("INFO", "FormulaLens saved models", "1 of 1 Hugging Face models placed from a saved copy: o/im2latex")]


def test_im2latex_pin_matches_the_package_lane_totals() -> None:
    man = json.loads((Path(__file__).resolve().parent.parent / "tools" / "nestegg" / "models_pinned.json").read_text(encoding="utf-8"))
    im = man["readers"]["FormulaLens"]["models"]["im2latex"]
    assert im["repo_id"] == "DGurgurov/im2latex" and im["revision"] == "6f28142d4d8358b6166c36d733e98ddea5862426"
    assert len(im["files"]) == 9 and sum(f["bytes"] for f in im["files"].values()) == 967_016_497
    assert all(len(f["sha256"]) == 64 for f in im["files"].values())


def _paddle_spoke(tmp_path: Path) -> tuple[Path, dict]:
    repo = tmp_path / "Conclave"
    pkg = repo / "conclave_lens_ocrpaddle" / "src" / "conclave_lens_ocrpaddle"
    pkg.mkdir(parents=True)
    (pkg / "engine_requirements.txt").write_text("paddlepaddle==2.6.2 \\\n    --hash=sha256:" + "a" * 64 + "\n")
    (pkg / "side_env_worker.py").write_text("")
    (pkg / "conclave_runtime_needs.toml").write_text(
        '[side_env]\npython = "3.12"\nneeded_when = "python_version >= \'3.13\'"\nrequirements = "engine_requirements.txt"\n'
        f'default_dir = "{(tmp_path / "home" / "ocrpaddle-side").as_posix()}"\nenv = "X"\nworker = "side_env_worker.py"\n'
        'gpu_swap = { remove = "paddlepaddle", add = "paddlepaddle-gpu==2.6.2" }\n')
    return repo, {"name": "OcrPaddle", "repo": "Conclave", "roots": ["conclave_lens_ocrpaddle"], "spoke_side_env": {"python": "3.12"}}


def test_paddle_side_env_built_from_the_spokes_hashed_list(tmp_path: Path, monkeypatch, capsys) -> None:
    """Conclave #2941: the installer builds the side env from engine_requirements.txt with --require-hashes at the
    spoke's default folder, runs the warmup, and names an old .paddle-env truthfully without touching it."""
    m = _mod()
    repo, part = _paddle_spoke(tmp_path)
    (repo / "conclave_lens_ocrpaddle" / ".paddle-env").mkdir()
    calls = []

    def fake_run(cmd, log, **k):
        calls.append([str(c) for c in cmd])
        if "venv" in calls[-1]:
            (Path(calls[-1][-1])).mkdir(parents=True, exist_ok=True)
        return 0
    monkeypatch.setattr(m, "run", fake_run)
    monkeypatch.setattr(m, "base_python", lambda v: ["python3.12"])
    rep = m.Report()
    m.side_envs(rep, part, tmp_path, tmp_path / "envs", tmp_path / "log.txt", Path("py"))
    out = capsys.readouterr().out
    target = tmp_path / "home" / "ocrpaddle-side"
    assert any("--require-hashes" in c and "--no-deps" in c and c[-1].endswith("engine_requirements.txt") for c in calls)
    assert any("--op" in c and "warmup" in c for c in calls) and (target / "adastra.json").is_file()
    assert "PASS  OcrPaddle side env" in out and "not locked" not in out
    assert "refuses it now" in out and (repo / "conclave_lens_ocrpaddle" / ".paddle-env").is_dir()  # named, not removed
    assert "GPU swap to paddlepaddle-gpu==2.6.2 is not done" in out
    assert not list(target.parent.glob("ocrpaddle-side.*"))  # nothing left beside it on a first build


def _fake_side_run(fail_warmup: bool = False):
    calls = []

    def fake_run(cmd, log, **k):
        c = [str(x) for x in cmd]
        calls.append(c)
        if "venv" in c:
            Path(c[-1]).mkdir(parents=True, exist_ok=True)
        return 1 if (fail_warmup and "warmup" in c) else 0
    return calls, fake_run


def test_paddle_side_env_rebuild_keeps_the_working_one_and_switches_only_on_pass(tmp_path: Path, monkeypatch, capsys) -> None:
    """SET-11 / SEC-8: the new build goes beside the old one; on PASS the old one is kept under a dated name."""
    m = _mod()
    repo, part = _paddle_spoke(tmp_path)
    target = tmp_path / "home" / "ocrpaddle-side"
    target.mkdir(parents=True)
    (target / "adastra.json").write_text("{}")
    (target / "old.txt").write_text("working copy")
    calls, fake = _fake_side_run()
    monkeypatch.setattr(m, "run", fake)
    monkeypatch.setattr(m, "base_python", lambda v: ["python3.12"])
    rep = m.Report()
    m.side_envs(rep, part, tmp_path, tmp_path / "envs", tmp_path / "log.txt", Path("py"))
    out = capsys.readouterr().out
    kept = list(target.parent.glob("ocrpaddle-side.kept-*"))
    assert rep.fails == 0 and len(kept) == 1 and (kept[0] / "old.txt").read_text() == "working copy"
    assert not (target / "old.txt").exists() and (target / "adastra.json").is_file()
    assert any(".new-" in c[-1] for c in calls if "venv" in c)  # built beside, not in place
    assert sum("warmup" in c for c in calls) == 2  # before and after the switch
    assert "warmup passed before and after the switch" in out and "previous side environment is kept" in out


def test_paddle_side_env_failed_warmup_leaves_the_old_one_in_use(tmp_path: Path, monkeypatch, capsys) -> None:
    m = _mod()
    repo, part = _paddle_spoke(tmp_path)
    target = tmp_path / "home" / "ocrpaddle-side"
    target.mkdir(parents=True)
    (target / "adastra.json").write_text("{}")
    (target / "old.txt").write_text("working copy")
    calls, fake = _fake_side_run(fail_warmup=True)
    monkeypatch.setattr(m, "run", fake)
    monkeypatch.setattr(m, "base_python", lambda v: ["python3.12"])
    rep = m.Report()
    m.side_envs(rep, part, tmp_path, tmp_path / "envs", tmp_path / "log.txt", Path("py"))
    out = capsys.readouterr().out
    assert rep.fails == 1 and (target / "old.txt").read_text() == "working copy"
    assert "not switched in" in out and f"the one already at {target} stays in use" in out
    assert not list(target.parent.glob("ocrpaddle-side.kept-*"))


def test_paddle_side_env_never_reuses_or_removes_a_folder_it_did_not_build(tmp_path: Path, monkeypatch, capsys) -> None:
    m = _mod()
    repo, part = _paddle_spoke(tmp_path)
    foreign = tmp_path / "home" / "ocrpaddle-side"
    foreign.mkdir(parents=True)
    (foreign / "keep.txt").write_text("someone else's")
    calls = []
    monkeypatch.setattr(m, "run", lambda cmd, log, **k: calls.append(cmd) or 0)
    monkeypatch.setattr(m, "base_python", lambda v: ["python3.12"])
    rep = m.Report()
    m.side_envs(rep, part, tmp_path, tmp_path / "envs", tmp_path / "log.txt", Path("py"))
    assert rep.fails == 1 and "was not built by this installer" in capsys.readouterr().out
    assert (foreign / "keep.txt").is_file() and not calls


def test_paddle_side_env_without_the_spokes_table_still_fails_as_not_locked(tmp_path: Path, monkeypatch, capsys) -> None:
    m = _mod()
    rep = m.Report()
    part = {"name": "OcrPaddle", "repo": "Conclave", "roots": ["conclave_lens_ocrpaddle"], "spoke_side_env": {"python": "3.12"}}
    m.side_envs(rep, part, tmp_path, tmp_path / "envs", tmp_path / "log.txt", Path("py"))
    assert rep.fails == 1 and "side env not locked" in capsys.readouterr().out


def _swap_setup(tmp_path: Path, monkeypatch, ok: bool, verified: bool = True, marker: str = ""):
    m = _mod()
    src = tmp_path / "src"
    (src / "atrium").mkdir(parents=True)
    env = tmp_path / "envs" / "atrium"
    env.mkdir(parents=True)
    (env / "old.txt").write_text("working copy")
    if verified:
        (env / m.VERIFIED).write_text("{}")
    if marker == "building":  # a build a crash interrupted
        (env / m.BUILDING).write_text("{}")
    elif marker == "legacy":  # built before the verified check existed: it has the root marker only
        (env / "adastra.json").write_text("{}")
    monkeypatch.setattr(m, "base_python", lambda v: ["py"])

    def fake_build(rep, part, src_, envs, env_, log, base, lines, repo, local, stamp=""):
        env_.mkdir(parents=True, exist_ok=True)
        (env_ / "new.txt").write_text("new build")
        return ok
    monkeypatch.setattr(m, "_build_env", fake_build)
    part = {"name": "atrium", "repo": "atrium", "roots": ["."], "python": "3.13"}
    return m, part, src, env


def test_main_env_rebuild_keeps_the_working_copy_when_the_new_one_passes(tmp_path: Path, monkeypatch, capsys) -> None:
    """SET-11: the previous environment is kept under a dated name, never deleted."""
    m, part, src, env = _swap_setup(tmp_path, monkeypatch, ok=True)
    rep = m.Report()
    m.build_part(rep, part, PARTS, src, tmp_path / "envs", False, False, set(), {})
    kept = list(env.parent.glob("atrium.kept-*"))
    assert len(kept) == 1 and (kept[0] / "old.txt").read_text() == "working copy" and (env / "new.txt").is_file()
    assert "previous environment is kept at" in capsys.readouterr().out
    rep2 = m.Report()  # a later run names the kept copy again (reviewer 3 on #70)
    m.build_part(rep2, part, PARTS, src, tmp_path / "envs", False, False, set(), {})
    out = capsys.readouterr().out
    assert f"{kept[0]} (previous working copy, kept" in out


def test_main_env_failed_rebuild_puts_the_working_copy_back(tmp_path: Path, monkeypatch, capsys) -> None:
    m, part, src, env = _swap_setup(tmp_path, monkeypatch, ok=False)
    rep = m.Report()
    m.build_part(rep, part, PARTS, src, tmp_path / "envs", False, False, set(), {})
    failed = list(env.parent.glob("atrium.failed-*"))
    assert (env / "old.txt").read_text() == "working copy" and not (env / "new.txt").exists()
    assert len(failed) == 1 and (failed[0] / "new.txt").is_file() and not list(env.parent.glob("atrium.kept-*"))
    assert "last verified working copy" in capsys.readouterr().out


def test_crash_then_failed_rerun_restores_the_true_working_copy(tmp_path: Path, monkeypatch, capsys) -> None:
    """Reviewer 3 on #72: a crash leaves a half-built env at the real path with no VERIFIED marker. A re-run whose
    build fails must not call that half env 'the previous environment'; it restores the newest VERIFIED .kept- copy."""
    m, part, src, env = _swap_setup(tmp_path, monkeypatch, ok=False, verified=False, marker="building")  # half build
    (env / "old.txt").write_text("half build")
    good = env.with_name("atrium.kept-20261123-070000")
    good.mkdir()
    (good / "old.txt").write_text("true working copy")
    (good / m.VERIFIED).write_text("{}")
    rep = m.Report()
    m.build_part(rep, part, PARTS, src, tmp_path / "envs", False, False, set(), {})
    out = capsys.readouterr().out
    assert (env / "old.txt").read_text() == "true working copy"
    unfinished = list(env.parent.glob("atrium.unfinished-*"))
    assert len(unfinished) == 1 and (unfinished[0] / "old.txt").read_text() == "half build"
    assert "last verified working copy (atrium.kept-20261123-070000) is back in use" in out
    assert "previous environment is back in use" not in out


def test_failed_rerun_with_no_verified_copy_says_so_plainly(tmp_path: Path, monkeypatch, capsys) -> None:
    m, part, src, env = _swap_setup(tmp_path, monkeypatch, ok=False, verified=False)
    rep = m.Report()
    m.build_part(rep, part, PARTS, src, tmp_path / "envs", False, False, set(), {})
    out = capsys.readouterr().out
    assert rep.fails == 1 and "there is no verified working copy to put back" in out and not env.exists()
    assert "back in use" not in out and list(env.parent.glob("atrium.unfinished-*"))


def test_env_from_before_the_check_is_kept_but_not_called_verified(tmp_path: Path, monkeypatch, capsys) -> None:
    m, part, src, env = _swap_setup(tmp_path, monkeypatch, ok=True, verified=False, marker="legacy")
    rep = m.Report()
    m.build_part(rep, part, PARTS, src, tmp_path / "envs", False, False, set(), {})
    out = capsys.readouterr().out
    assert "kept, not verified, at" in out and "last known working copy" not in out
    assert (env / m.VERIFIED).is_file() and not list(env.parent.glob("atrium.kept-*"))
    assert len(list(env.parent.glob("atrium.legacy-*"))) == 1


def test_env_from_before_the_check_is_put_back_not_verified_when_the_rebuild_fails(tmp_path: Path, monkeypatch, capsys) -> None:
    """Reviewer 3 on #72, round 2: on the first run after this lands every env on Jake's PC is from before the check.
    A failed rebuild must put it back (SET-11), saying it is not verified, not leave the part uninstalled."""
    m, part, src, env = _swap_setup(tmp_path, monkeypatch, ok=False, verified=False, marker="legacy")
    rep = m.Report()
    m.build_part(rep, part, PARTS, src, tmp_path / "envs", False, False, set(), {})
    out = capsys.readouterr().out
    assert (env / "old.txt").read_text() == "working copy" and not (env / "new.txt").exists()
    assert "put back, not verified" in out and "no verified working copy" not in out and rep.fails == 0
    assert not (env / m.VERIFIED).exists() and len(list(env.parent.glob("atrium.failed-*"))) == 1


def test_verified_kept_copy_outranks_a_legacy_env_on_failure(tmp_path: Path, monkeypatch, capsys) -> None:
    m, part, src, env = _swap_setup(tmp_path, monkeypatch, ok=False, verified=False, marker="legacy")
    good = env.with_name("atrium.kept-20261123-070000")
    good.mkdir()
    (good / "old.txt").write_text("verified copy")
    (good / m.VERIFIED).write_text("{}")
    rep = m.Report()
    m.build_part(rep, part, PARTS, src, tmp_path / "envs", False, False, set(), {})
    assert (env / "old.txt").read_text() == "verified copy" and list(env.parent.glob("atrium.legacy-*"))
    assert "last verified working copy (atrium.kept-20261123-070000)" in capsys.readouterr().out


def test_crash_in_an_earlier_rebuild_does_not_strand_the_legacy_copy(tmp_path: Path, monkeypatch, capsys) -> None:
    """Reviewer 3 on #72: run 1 set the pre-check env aside as .legacy- and crashed mid-build; run 2 fails too. The
    newest .legacy- from the earlier run is put back ("not verified"); the half build goes to .unfinished-."""
    m, part, src, env = _swap_setup(tmp_path, monkeypatch, ok=False, verified=False, marker="building")
    (env / "old.txt").write_text("half build")
    older = env.with_name("atrium.legacy-20261123-060000")
    older.mkdir()
    (older / "old.txt").write_text("stale legacy")
    leg = env.with_name("atrium.legacy-20261123-070000")
    leg.mkdir()
    (leg / "old.txt").write_text("legacy working copy")
    (leg / "adastra.json").write_text("{}")
    rep = m.Report()
    m.build_part(rep, part, PARTS, src, tmp_path / "envs", False, False, set(), {})
    out = capsys.readouterr().out
    assert (env / "old.txt").read_text() == "legacy working copy" and rep.fails == 0
    assert "(atrium.legacy-20261123-070000) is put back, not verified" in out and "no verified working copy" not in out
    unf = list(env.parent.glob("atrium.unfinished-*"))
    assert len(unf) == 1 and (unf[0] / "old.txt").read_text() == "half build" and older.is_dir()


def test_crash_interrupted_env_is_never_put_back_when_the_rebuild_fails(tmp_path: Path, monkeypatch, capsys) -> None:
    """A building marker with no verified marker is a build a crash cut off, even if adastra.json got written."""
    m, part, src, env = _swap_setup(tmp_path, monkeypatch, ok=False, verified=False, marker="building")
    (env / "adastra.json").write_text("{}")
    rep = m.Report()
    m.build_part(rep, part, PARTS, src, tmp_path / "envs", False, False, set(), {})
    out = capsys.readouterr().out
    assert rep.fails == 1 and "there is no verified working copy to put back" in out and not env.exists()
    assert "put back, not verified" not in out and len(list(env.parent.glob("atrium.unfinished-*"))) == 1


def test_verified_marker_write_failure_is_a_fail_row_not_a_crash(tmp_path: Path, monkeypatch, capsys) -> None:
    m, part, src, env = _swap_setup(tmp_path, monkeypatch, ok=True)
    real = Path.write_text
    monkeypatch.setattr(Path, "write_text", lambda self, *a, **k: (_ for _ in ()).throw(OSError(28, "disk full"))
                        if self.name == m.VERIFIED else real(self, *a, **k))
    rep = m.Report()
    m.build_part(rep, part, PARTS, src, tmp_path / "envs", False, False, set(), {})
    out = capsys.readouterr().out
    assert "verified marker" in out and "cannot be counted as a working copy" in out
    assert (env / "old.txt").read_text() == "working copy"  # the verified previous copy is put back


def test_building_marker_is_written_before_the_venv_is_created(tmp_path: Path, monkeypatch) -> None:
    m = _mod()
    env = tmp_path / "envs" / "atrium"
    seen = []
    monkeypatch.setattr(m, "run", lambda cmd, log: seen.append((env / m.BUILDING).is_file()) or 1)
    rep = m.Report()
    ok = m._build_env(rep, {"name": "atrium", "roots": ["."]}, tmp_path, tmp_path / "envs", env, tmp_path / "l.txt",
                      ["py"], [], tmp_path, set(), "20261123-080000")
    assert not ok and seen == [True] and not (env / m.VERIFIED).exists()


def test_main_env_held_open_is_a_fail_row_not_a_crash(tmp_path: Path, monkeypatch, capsys) -> None:
    """Windows refuses to rename a folder a running program holds; that is a FAIL row and nothing changes."""
    m, part, src, env = _swap_setup(tmp_path, monkeypatch, ok=True)
    real = Path.rename
    monkeypatch.setattr(Path, "rename", lambda self, t: (_ for _ in ()).throw(PermissionError(32, "in use")) if self == env else real(self, t))
    rep = m.Report()
    m.build_part(rep, part, PARTS, src, tmp_path / "envs", False, False, set(), {})
    assert rep.fails == 1 and "could not set the existing environment aside" in capsys.readouterr().out
    assert (env / "old.txt").is_file() and not (env / "new.txt").exists()


def test_paddle_side_env_held_open_is_a_fail_row_and_the_old_one_stays(tmp_path: Path, monkeypatch, capsys) -> None:
    m = _mod()
    repo, part = _paddle_spoke(tmp_path)
    target = tmp_path / "home" / "ocrpaddle-side"
    target.mkdir(parents=True)
    (target / "adastra.json").write_text("{}")
    (target / "old.txt").write_text("working copy")
    calls, fake = _fake_side_run()
    monkeypatch.setattr(m, "run", fake)
    monkeypatch.setattr(m, "base_python", lambda v: ["python3.12"])
    real = Path.rename
    monkeypatch.setattr(Path, "rename", lambda self, t: (_ for _ in ()).throw(PermissionError(32, "in use")) if self == target else real(self, t))
    rep = m.Report()
    m.side_envs(rep, part, tmp_path, tmp_path / "envs", tmp_path / "log.txt", Path("py"))
    out = capsys.readouterr().out
    assert rep.fails == 1 and "could not switch the new build in" in out and (target / "old.txt").is_file()
    rep2 = m.Report()  # the unfinished build beside it is named on the next run
    monkeypatch.setattr(Path, "rename", real)
    m.side_envs(rep2, part, tmp_path, tmp_path / "envs", tmp_path / "log.txt", Path("py"))
    assert "(unfinished build, left in place" in capsys.readouterr().out


def test_spacy_model_wheel_comes_from_the_saved_copy_first(tmp_path: Path, monkeypatch) -> None:
    """HR 14: en_core_web_sm installs from the saved copy (no internet), by its pinned sha256; else the URL."""
    import hashlib
    m = _mod()
    sc = m._saved_copies()
    body = b"spacy model wheel"
    whl = tmp_path / "en_core_web_sm-3.8.0-py3-none-any.whl"
    whl.write_bytes(body)
    spec = {"wheel": "https://example.invalid/x/" + whl.name, "wheel_sha256": hashlib.sha256(body).hexdigest(),
            "wheel_bytes": len(body), "name": "en_core_web_sm-3.8.0"}
    envs = tmp_path / "root" / "envs"
    envs.mkdir(parents=True)
    log = envs / "spacy.txt"
    m.INSTALL_ROOT["root"] = tmp_path / "root"
    assert m.saved_model_wheel(spec, envs, log) is None  # no saved copy yet: the caller uses the URL
    sc.split(whl, tmp_path / "root" / "saved", 2_000_000_000)
    got = m.saved_model_wheel(spec, envs, log)
    assert got == envs / "_wheelhouse" / whl.name and got.read_bytes() == body
    other = dict(spec, wheel_sha256=hashlib.sha256(b"something else").hexdigest())
    assert m.saved_model_wheel(other, envs / "other", log) is None  # only the pinned sha256 is ever taken
    src = (NESTEGG / "install_parts.py").read_text(encoding="utf-8")
    step = src[src.index('elif step == "spacy_model":'):src.index('unknown model step')]
    assert step.index("saved_model_wheel(") < step.index('"--no-index", local') < step.index("#sha256=")


def test_saved_copy_build_fails_loudly_when_a_model_list_is_missing(tmp_path: Path) -> None:
    """No silent failure: a missing parts.json (or model list) must stop the build, not quietly drop its files."""
    import importlib.util
    import shutil

    import pytest
    for f in ("build_saved_release.py", "saved_copies.py", "saved_copies.json", "models_pinned.json", "htrlens_models.json"):
        shutil.copy(NESTEGG / f, tmp_path / f)
    spec = importlib.util.spec_from_file_location("bsr_missing", tmp_path / "build_saved_release.py")
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    with pytest.raises(SystemExit, match="parts.json not found"):
        b.model_items()
    (tmp_path / "htrlens_models.json").unlink()
    with pytest.raises(SystemExit, match="htrlens_models.json not found"):
        b.model_items()


def test_only_a_scratch_test_folder_this_installer_made_is_removed(tmp_path: Path, monkeypatch, capsys) -> None:
    """Decision 50 A: envs\\<Part>-test is removed only when it carries the installer's own marker."""
    m = _mod()
    rep = m.Report()
    envs = tmp_path / "envs"
    (envs / "_logs").mkdir(parents=True)
    theirs = envs / "Demo-test"
    theirs.mkdir()
    (theirs / "keep.txt").write_text("made by Jake")
    monkeypatch.setattr(m, "read_list", lambda p: {"demo": "1.0"})
    monkeypatch.setattr(m, "lock_reqs", lambda *a, **k: (["demo==1.0 --hash=sha256:" + "0" * 64], []))
    monkeypatch.setattr(m, "load_sums", lambda win: {})
    part = {"name": "Demo", "python": "3.13", "test_env": {"list": "x.txt", "roots": []}}
    assert m._test_env(rep, part, tmp_path, envs, envs / "_logs" / "d.txt", "built", "status") is None
    assert (theirs / "keep.txt").read_text() == "made by Jake"
    assert rep.holds == 1 and "not made by this installer; left untouched" in capsys.readouterr().out
    (theirs / m.TEST_ENV_MARK).write_text("{}")  # an earlier run's own scratch folder: removed, then rebuilt
    monkeypatch.setattr(m, "base_python", lambda v: None)
    m._test_env(rep, part, tmp_path, envs, envs / "_logs" / "d.txt", "built", "status")
    assert not theirs.exists()
    src = (NESTEGG / "install_parts.py").read_text(encoding="utf-8")
    assert src.count("rmtree(envs / f\"{name}-test\"") == 1 and "TEST_ENV_MARK).is_file():" in src


def test_own_tests_cleanup_removes_only_a_marked_scratch_folder(tmp_path: Path, monkeypatch, capsys) -> None:
    """Decision 50 A guard after the test run: an unmarked <Part>-test folder survives; the marked one goes."""
    m = _mod()
    envs = tmp_path / "envs"
    (envs / "_logs").mkdir(parents=True)
    (tmp_path / "spoke" / "tests").mkdir(parents=True)
    part = {"name": "Demo", "python": "3.13", "roots": ["spoke"], "test_env": {"list": "x.txt", "roots": []}}
    monkeypatch.setattr(m, "read_list", lambda p: {})
    monkeypatch.setattr(m, "run", lambda *a, **k: 0)
    folder = envs / "Demo-test"
    for marked in (False, True):
        folder.mkdir(exist_ok=True)
        (folder / "keep.txt").write_text("x")
        if marked:
            (folder / m.TEST_ENV_MARK).write_text("{}")
        monkeypatch.setattr(m, "_test_env", lambda *a, **k: Path("py"))  # the test env step itself is covered elsewhere
        m.own_tests(m.Report(), part, tmp_path, Path("py"), envs, envs / "_logs" / "d.txt", "built", "status")
        assert folder.exists() is (not marked)


def test_saved_copy_error_for_spacy_wheel_is_a_fail_row_then_the_pinned_url(tmp_path: Path, monkeypatch, capsys) -> None:
    """An exception reading the saved copies is never silent (FAIL row); the install then uses the #sha256= pinned URL."""
    m = _mod()
    envs = tmp_path / "envs"
    envs.mkdir()
    spec = {"step": "spacy_model", "wheel": "https://example.invalid/x/en_core_web_sm-3.8.0-py3-none-any.whl",
            "wheel_sha256": "1" * 64, "name": "en_core_web_sm-3.8.0"}

    def boom(*a, **k):
        raise OSError("disk unreadable")

    calls = []
    monkeypatch.setattr(m, "saved_models", lambda *a, **k: None)
    monkeypatch.setattr(m, "saved_model_wheel", boom)
    monkeypatch.setattr(m, "run", lambda cmd, log, **k: calls.append([str(c) for c in cmd]) or 0)
    rep = m.Report()
    m.models(rep, {"name": "obsidian", "roots": ["."], "models": [spec]}, tmp_path, tmp_path, envs, Path("py"), envs / "l.txt")
    out = capsys.readouterr().out
    assert "FAIL  en_core_web_sm-3.8.0 saved copy" in out and "OSError: disk unreadable" in out
    assert rep.fails >= 1
    assert calls[0][-1] == spec["wheel"] + "#sha256=" + spec["wheel_sha256"] and "--no-index" not in calls[0]


def _reader_record(envs: Path, status: str = "PASS") -> Path:
    rec = envs / "reader_envs.json"
    rec.write_text(json.dumps({"schema": 1, "provisional": False, "readers": [{"part": "PdfText", "status": status}]}))
    return rec


def _wb_envs(tmp_path: Path, m) -> tuple[Path, list[dict]]:
    envs = tmp_path / "envs"
    for n in ("workbench", "harness_adapters"):
        py = m.env_python(envs / n)
        py.parent.mkdir(parents=True, exist_ok=True)
        py.write_text("")
    return envs, [{"name": "workbench", "harness_from": "harness_adapters"}]


def test_reader_envs_turned_on_per_reader_gate_and_every_reader_named(tmp_path: Path, monkeypatch, capsys) -> None:
    """Go-live (coordinator ruling 11/23): on when >= 1 reader is PASS and this run's Run button passed; other
    FAIL rows in the run do not block it; every reader is listed usable / not usable; otherwise LEFT OFF, loudly."""
    import subprocess
    m = _mod()
    envs, parts = _wb_envs(tmp_path, m)
    rec = envs / "reader_envs.json"
    rec.write_text(json.dumps({"schema": 1, "provisional": False, "readers": [
        {"part": "PdfText", "status": "PASS"}, {"part": "MinerU", "status": "FAIL"}]}))
    calls = []

    def fake(cmd, **k):
        calls.append([str(c) for c in cmd])
        return subprocess.CompletedProcess(cmd, 0, f"WORKBENCH-READER-ENVS: OK {rec} (written to x)\n", "")

    monkeypatch.setattr(m.subprocess, "run", fake)
    m.RUN_BUTTON.clear()
    m.turn_on_reader_envs(m.Report(), rec, envs, parts, False)
    out = capsys.readouterr().out
    assert calls == [] and "LEFT OFF (the workbench Run button was not checked in this run)" in out
    m.RUN_BUTTON["workbench"] = False
    m.turn_on_reader_envs(m.Report(), rec, envs, parts, False)
    assert calls == [] and "LEFT OFF (the workbench Run button row failed)" in capsys.readouterr().out
    m.RUN_BUTTON["workbench"] = True
    _reader_record(envs, "HOLD")
    m.turn_on_reader_envs(m.Report(), rec, envs, parts, False)
    assert calls == [] and "LEFT OFF (no reader environment passed)" in capsys.readouterr().out
    rec.write_text(json.dumps({"schema": 1, "provisional": False, "readers": [
        {"part": "PdfText", "status": "PASS"}, {"part": "MinerU", "status": "FAIL"}]}))
    good = m.Report()
    good.fails = 9  # unpinned model steps elsewhere in the run do not block a reader that is PASS
    m.turn_on_reader_envs(good, rec, envs, parts, False)
    out = capsys.readouterr().out
    assert calls and calls[0][-3:] == ["--reader-envs", str(rec), str(m.env_python(envs / "harness_adapters"))]
    assert "readers usable" in out and "1: PdfText" in out and "readers NOT usable" in out and "MinerU (FAIL)" in out
    assert good.passes == 1 and "harness.reader_envs on: 1 readers usable (1 not usable, listed above)" in out
    m.RUN_BUTTON.clear()


def test_reader_envs_script_failure_is_a_fail_row(tmp_path: Path, monkeypatch, capsys) -> None:
    import subprocess
    m = _mod()
    envs, parts = _wb_envs(tmp_path, m)
    rec = _reader_record(envs)
    monkeypatch.setattr(m.subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(
        cmd, 1, "WORKBENCH-READER-ENVS: FAIL harness.reader_envs is already set to C:/other.json\n", ""))
    rep = m.Report()
    m.RUN_BUTTON["workbench"] = True
    m.turn_on_reader_envs(rep, rec, envs, parts, False)
    m.RUN_BUTTON.clear()
    assert rep.fails == 1 and "already set to C:/other.json" in capsys.readouterr().out


def test_workbench_reader_envs_writes_only_blank_and_puts_back_off_when_the_probe_fails(tmp_path: Path, monkeypatch, capsys) -> None:
    """The Workbench side of the go-live switch, against stand-ins for the Workbench settings API."""
    import importlib.util
    import subprocess
    import types
    store: dict = {}
    mods = {
        "conclave_workbench": types.ModuleType("conclave_workbench"),
        "conclave_workbench.pages": types.ModuleType("p"), "conclave_workbench.pages.settings": types.ModuleType("s"),
        "conclave_workbench.pages.settings.catalog": types.SimpleNamespace(
            HARNESS_READER_ENVS_KEY="harness.reader_envs", phase_a_defaults=lambda s, x: {}, workbench_schema=lambda x: None),
        "conclave_workbench.pages.settings.provenance": types.SimpleNamespace(
            Scope=types.SimpleNamespace(DEFAULT=0), ScopeLayer=lambda *a: None),
        "conclave_workbench.pages.settings.user_layer": types.SimpleNamespace(
            default_user_settings_path=lambda: tmp_path / "user.json", load_user_layer=lambda p: None,
            save_user_value=lambda p, k, v: store.__setitem__(k, v)),
        "conclave_workbench.seal": types.ModuleType("seal"),
        "conclave_workbench.seal.wiring": types.SimpleNamespace(
            harness_reader_envs_reader=lambda schema, layers: (lambda: store.get("harness.reader_envs") or None)),
    }
    for k, v in mods.items():
        monkeypatch.setitem(sys.modules, k, v)
    spec = importlib.util.spec_from_file_location("wbh", NESTEGG / "workbench_harness.py")
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    rec = tmp_path / "reader_envs.json"
    rec.write_text("{}")
    monkeypatch.setattr(w.subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(cmd, 0, '{"presets": {}}\n', ""))
    assert w.reader_envs(str(rec), "py") == 0 and store["harness.reader_envs"] == str(rec)
    store["harness.reader_envs"] = "C:/chosen.json"  # a value the person chose is never overwritten
    assert w.reader_envs(str(rec), "py") == 1 and store["harness.reader_envs"] == "C:/chosen.json"
    store.clear()
    monkeypatch.setattr(w.subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(cmd, 2, "", "boom\n"))
    assert w.reader_envs(str(rec), "py") == 1 and store["harness.reader_envs"] == ""  # put back off
    store["harness.reader_envs"] = str(rec)  # an earlier install left it on, and now the probe fails
    assert w.reader_envs(str(rec), "py") == 1 and store["harness.reader_envs"] == str(rec)
    assert "STILL ON" in capsys.readouterr().out  # never left on quietly


def test_reader_envs_left_off_when_the_harness_environment_is_not_built(tmp_path: Path, monkeypatch, capsys) -> None:
    """The fourth leg of the gate: with a PASS reader and a passed Run button, a missing harness env still leaves it off."""
    m = _mod()
    envs, parts = _wb_envs(tmp_path, m)
    m.env_python(envs / "harness_adapters").unlink()
    rec = _reader_record(envs)
    calls = []
    monkeypatch.setattr(m.subprocess, "run", lambda cmd, **k: calls.append(cmd))
    rep = m.Report()
    m.RUN_BUTTON["workbench"] = True
    m.turn_on_reader_envs(rep, rec, envs, parts, False)
    m.RUN_BUTTON.clear()
    out = capsys.readouterr().out
    assert calls == [] and rep.passes == 0 and "LEFT OFF (the harness_adapters environment is not built)" in out


def _pinned_setup(tmp_path: Path, monkeypatch, models: dict) -> tuple:
    """A fake models_pinned.json next to the real saved_copies.py, with a home copy and the original site."""
    import shutil
    m = _mod()
    here = tmp_path / "nestegg"
    here.mkdir(parents=True)
    shutil.copy(NESTEGG / "saved_copies.py", here / "saved_copies.py")
    (here / "saved_copies.json").write_text(json.dumps({"max_part_bytes": 2_000_000_000, "locations": [
        {"name": "home copy", "kind": "folder", "path": "{install_root}/saved"},
        {"name": "original site", "kind": "origin"}]}), encoding="utf-8")
    (here / "models_pinned.json").write_text(json.dumps({"readers": {"Rdr": {"models": models}}}), encoding="utf-8")
    monkeypatch.setattr(m, "HERE", here)
    m.INSTALL_ROOT["root"] = tmp_path / "root"
    envs = tmp_path / "root" / "envs"
    envs.mkdir(parents=True)
    spoke = tmp_path / "spoke"
    (spoke / "scripts").mkdir(parents=True)
    return m, envs, spoke, envs / "rdr.txt"


def _file_pin(tmp_path: Path, name: str, body: bytes) -> dict:
    import hashlib
    src = tmp_path / "origin" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(body)
    return {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "url": src.as_uri()}


def test_pinned_models_writes_the_readers_lock_and_runs_its_own_check(tmp_path: Path, monkeypatch, capsys) -> None:
    """HR 13/14: a lock-file reader (HtrQwen, GlmOcr) gets every pinned file, its lock in its own format, then
    its own fetch script re-checks it. A file from a saved copy and one from the original site both count."""
    target = tmp_path / "home" / "qwen"
    monkeypatch.setenv("FAKE_MODEL_DIR", str(target))
    files = {"config.json": _file_pin(tmp_path, "config.json", b"{}"),
             "model.safetensors": _file_pin(tmp_path, "model.safetensors", b"weights")}
    model = {"source": "huggingface", "repo_id": "org/qwen", "revision": "a" * 40, "files": files,
             "local_dir": {"env": "FAKE_MODEL_DIR", "default": "~/unused"}, "reader_lock": "conclave_model_lock.json"}
    m, envs, spoke, log = _pinned_setup(tmp_path, monkeypatch, {"q": model})
    sc = m._saved_copies()
    sc.split(tmp_path / "origin" / "config.json", tmp_path / "root" / "saved", 2_000_000_000)  # one in the home copy
    (spoke / "scripts" / "fetch_model.py").write_text("print('PASS')\n", encoding="utf-8")
    rep = m.Report()
    m.pinned_models(rep, {"name": "Rdr"}, spoke, envs, Path(sys.executable), log)
    out = capsys.readouterr().out
    assert rep.passes == 1 and rep.fails == 0, out
    assert "home copy" in out and "original site" in out and "own lock check passed" in out
    lock = json.loads((target / "conclave_model_lock.json").read_text(encoding="utf-8"))
    assert lock == {"repo": "org/qwen", "revision": "a" * 40, "files": {p: f["sha256"] for p, f in files.items()}}
    assert (target / "model.safetensors").read_bytes() == b"weights"
    (spoke / "scripts" / "fetch_model.py").write_text("print('FAIL')\n", encoding="utf-8")  # the reader's check decides too
    rep = m.Report()
    m.pinned_models(rep, {"name": "Rdr"}, spoke, envs, Path(sys.executable), log)
    assert rep.fails == 1 and rep.passes == 0


def test_pinned_models_never_overwrites_a_model_with_another_lock(tmp_path: Path, monkeypatch, capsys) -> None:
    target = tmp_path / "home" / "glm"
    target.mkdir(parents=True)
    monkeypatch.setenv("FAKE_MODEL_DIR", str(target))
    (target / "model.safetensors").write_bytes(b"theirs")
    (target / "conclave_model_lock.json").write_text(json.dumps({"revision": "b" * 40, "files": {}}), encoding="utf-8")
    model = {"source": "huggingface", "repo_id": "org/glm", "revision": "a" * 40,
             "files": {"model.safetensors": _file_pin(tmp_path, "model.safetensors", b"ours")},
             "local_dir": {"env": "FAKE_MODEL_DIR", "default": "~/unused"}, "reader_lock": "conclave_model_lock.json"}
    m, envs, spoke, log = _pinned_setup(tmp_path, monkeypatch, {"g": model})
    rep = m.Report()
    m.pinned_models(rep, {"name": "Rdr"}, spoke, envs, Path(sys.executable), log)
    assert rep.holds == 1 and rep.passes == 0 and "left untouched" in capsys.readouterr().out
    assert (target / "model.safetensors").read_bytes() == b"theirs"  # nothing of theirs changed
    assert not m._place_local_dir(m._saved_copies(), model, m._saved_copies().load_config(), tmp_path / "root", print)


def test_pinned_models_wrong_bytes_are_a_fail_and_the_cache_names_the_pin(tmp_path: Path, monkeypatch, capsys) -> None:
    """The standard cache: refs/main names the pinned commit. Bytes that do not match the pin are never used."""
    cache = tmp_path / "hub"
    monkeypatch.setenv("HF_HUB_CACHE", str(cache))
    good = _file_pin(tmp_path, "config.json", b"{}")
    model = {"source": "huggingface", "repo_id": "org/tt", "revision": "c" * 40, "pinned_in_code": False,
             "files": {"config.json": good}}
    m, envs, spoke, log = _pinned_setup(tmp_path, monkeypatch, {"t": model})
    rep = m.Report()
    m.pinned_models(rep, {"name": "Rdr"}, spoke, envs, Path(sys.executable), log)
    out = capsys.readouterr().out
    assert rep.passes == 1 and "does not name this revision" in out, out
    repo = cache / "models--org--tt"
    assert (repo / "refs" / "main").read_text(encoding="utf-8") == "c" * 40
    assert (repo / "snapshots" / ("c" * 40) / "config.json").read_bytes() == b"{}"
    bad = dict(model, revision="d" * 40, files={"config.json": dict(good, sha256="0" * 64)})
    m, envs, spoke, log = _pinned_setup(tmp_path / "2", monkeypatch, {"t": bad})
    rep = m.Report()
    m.pinned_models(rep, {"name": "Rdr"}, spoke, envs, Path(sys.executable), log)
    assert rep.fails == 1 and rep.passes == 0
    assert not (repo / "snapshots" / ("d" * 40) / "config.json").exists()


def test_pinned_models_names_a_tag_ref_and_fails_an_unmeasured_source(tmp_path: Path, monkeypatch, capsys) -> None:
    """Docling asks the cache for tag v2.3.0, so that ref names the pin; RapidOCR (modelscope, not measured yet)
    is a FAIL row, never skipped quietly while the rest of the reader passes."""
    cache = tmp_path / "hub"
    monkeypatch.setenv("HF_HUB_CACHE", str(cache))
    models = {"tf": {"source": "huggingface", "repo_id": "org/tf", "revision": "e" * 40, "revision_ref": "tag v2.3.0",
                     "files": {"config.json": _file_pin(tmp_path, "config.json", b"{}")}},
              "ocr": {"source": "modelscope", "files": {"det.onnx": {"sha256": None}},
                      "unmeasured_reason": "modelscope is blocked here"}}
    m, envs, spoke, log = _pinned_setup(tmp_path, monkeypatch, models)
    rep = m.Report()
    m.pinned_models(rep, {"name": "Rdr"}, spoke, envs, Path(sys.executable), log)
    out = capsys.readouterr().out
    assert rep.passes == 1 and rep.fails == 1 and "modelscope is blocked here" in out, out
    assert (cache / "models--org--tf" / "refs" / "v2.3.0").read_text(encoding="utf-8") == "e" * 40
    assert not (cache / "models--org--tf" / "refs" / "main").exists()
    assert m.hf_ref({"revision_ref": "main"}) == m.hf_ref({"revision_ref": "commit"}) == "main"


def _mineru_model(tmp_path: Path) -> dict:
    return {"source": "huggingface", "repo_id": "org/pek", "revision": "f" * 40, "mineru_config": True,
            "files": {"models/x.pt": _file_pin(tmp_path, "x.pt", b"pek")}}


def _fake_mineru_cli(envs: Path, body: str) -> None:
    """A _mineru_cli venv whose `python -m mineru.cli.models_download` runs `body` (a stand-in for MinerU's own)."""
    import subprocess
    import sysconfig
    env = envs / "_mineru_cli"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(env)], check=True)
    site = env / Path(sysconfig.get_path("purelib")).relative_to(sysconfig.get_path("data"))
    (site / "mineru" / "cli").mkdir(parents=True)
    for d in (site / "mineru", site / "mineru" / "cli"):
        (d / "__init__.py").write_text("", encoding="utf-8")
    (site / "mineru" / "cli" / "models_download.py").write_text(body, encoding="utf-8")


def test_mineru_is_not_pass_until_its_reader_config_names_the_pinned_snapshot(tmp_path: Path, monkeypatch, capsys) -> None:
    """Reviewer 3 (#86): the MinerU reader finds models only via CONCLAVE_MINERU_MODELS_DIR, MINERU_TOOLS_CONFIG_JSON
    or ~/mineru.json. Placed files alone are never PASS; another folder there is HOLD, untouched."""
    cache = tmp_path / "hub"
    monkeypatch.setenv("HF_HUB_CACHE", str(cache))
    monkeypatch.delenv("CONCLAVE_MINERU_MODELS_DIR", raising=False)
    cfg = tmp_path / "home" / "mineru.json"
    monkeypatch.setenv("MINERU_TOOLS_CONFIG_JSON", str(cfg))
    snap = cache / "models--org--pek" / "snapshots" / ("f" * 40)
    m, envs, spoke, log = _pinned_setup(tmp_path, monkeypatch, {"p": _mineru_model(tmp_path)})
    rep = m.Report()  # no _mineru_cli env and no config: FAIL, never PASS
    m.pinned_models(rep, {"name": "Rdr"}, spoke, envs, Path(sys.executable), log)
    assert rep.fails == 1 and rep.passes == 0 and "would not find it" in capsys.readouterr().out
    _fake_mineru_cli(envs, "import json, os, sys\n"
                     "assert os.environ['HF_HUB_OFFLINE'] == '1'  # it can only resolve what is already in the cache\n"
                     f"open(os.environ['MINERU_TOOLS_CONFIG_JSON'], 'w').write(json.dumps({{'models-dir': {{'pipeline': {str(snap)!r}}}}}))\n")
    cfg.parent.mkdir(parents=True)
    rep = m.Report()
    m.pinned_models(rep, {"name": "Rdr"}, spoke, envs, Path(sys.executable), log)
    out = capsys.readouterr().out
    assert rep.passes == 1 and "names the pinned snapshot" in out, out
    other = {"models-dir": {"pipeline": str(tmp_path / "older")}, "keep": 1}
    cfg.write_text(json.dumps(other), encoding="utf-8")
    rep = m.Report()
    m.pinned_models(rep, {"name": "Rdr"}, spoke, envs, Path(sys.executable), log)
    assert rep.holds == 1 and rep.passes == 0 and json.loads(cfg.read_text(encoding="utf-8")) == other
    monkeypatch.setenv("CONCLAVE_MINERU_MODELS_DIR", str(snap))  # the reader's own override wins, as in the reader
    rep = m.Report()
    m.pinned_models(rep, {"name": "Rdr"}, spoke, envs, Path(sys.executable), log)
    assert rep.passes == 1 and "CONCLAVE_MINERU_MODELS_DIR" in capsys.readouterr().out


def test_pinned_models_guards_reviewer_3_listed(tmp_path: Path, monkeypatch, capsys) -> None:
    """The five legs reviewer 3's mutations showed untested (#86)."""
    target = tmp_path / "home" / "q"
    monkeypatch.setenv("FAKE_MODEL_DIR", str(target))
    files = {"w.bin": _file_pin(tmp_path, "w.bin", b"w")}
    lockm = {"source": "huggingface", "repo_id": "org/q", "revision": "a" * 40, "files": files,
             "local_dir": {"env": "FAKE_MODEL_DIR", "default": "~/x"}, "reader_lock": "conclave_model_lock.json"}
    # 1. same revision, different files in the lock: still someone else's model, HOLD
    target.mkdir(parents=True)
    (target / "conclave_model_lock.json").write_text(json.dumps({"revision": "a" * 40, "files": {"w.bin": "0" * 64}}))
    m, envs, spoke, log = _pinned_setup(tmp_path, monkeypatch, {"q": lockm})
    rep = m.Report()
    m.pinned_models(rep, {"name": "Rdr"}, spoke, envs, Path(sys.executable), log)
    assert rep.holds == 1 and rep.passes == 0
    # 5. a lock that already matches the pin is never rewritten (its exact bytes stay)
    mine = json.dumps({"repo": "org/q", "revision": "a" * 40, "files": {"w.bin": files["w.bin"]["sha256"]}})
    (target / "conclave_model_lock.json").write_text(mine, encoding="utf-8")
    (spoke / "scripts" / "fetch_model.py").write_text("print('PASS')\n", encoding="utf-8")
    rep = m.Report()
    m.pinned_models(rep, {"name": "Rdr"}, spoke, envs, Path(sys.executable), log)
    assert rep.passes == 1 and (target / "conclave_model_lock.json").read_text(encoding="utf-8") == mine
    # 2. a file without a pinned sha256: FAIL, nothing installed
    m, envs, spoke, log = _pinned_setup(tmp_path / "2", monkeypatch, {"n": dict(lockm, files={"w.bin": {"bytes": 1}})})
    rep = m.Report()
    m.pinned_models(rep, {"name": "Rdr"}, spoke, envs, Path(sys.executable), log)
    assert rep.fails == 1 and "without a pinned sha256" in capsys.readouterr().out
    # 3. the package folder: a failing lookup is a FAIL, not a folder
    pkg = {"source": "github_release", "files": files, "package_dir": {"package": "no_such_pkg_xyz", "sub": "c"}}
    m, envs, spoke, log = _pinned_setup(tmp_path / "3", monkeypatch, {"k": pkg})
    rep = m.Report()
    m.pinned_models(rep, {"name": "Rdr"}, spoke, envs, Path(sys.executable), log)
    assert rep.fails == 1 and "not found in the environment" in capsys.readouterr().out
    import subprocess
    real = m.subprocess.run
    monkeypatch.setattr(m.subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, str(tmp_path / "pk") + "\n", "boom")
                        if "find_spec" in " ".join(map(str, cmd)) else real(cmd, **k))
    assert m._package_dir(Path(sys.executable), pkg["package_dir"], log) is None  # a path printed by a failed run is not trusted
    monkeypatch.setattr(m.subprocess, "run", real)
    # 4. a reader with nothing pinned: FAIL
    m, envs, spoke, log = _pinned_setup(tmp_path / "4", monkeypatch, {})
    rep = m.Report()
    m.pinned_models(rep, {"name": "Rdr"}, spoke, envs, Path(sys.executable), log)
    assert rep.fails == 1 and "no model pinned" in capsys.readouterr().out


def test_mineru_read_back_and_a_config_without_a_pipeline(tmp_path: Path, monkeypatch, capsys) -> None:
    """Reviewer 3 (#86 follow-up): MinerU's own run that writes another folder, or exits 1, is FAIL (the read-back
    decides, not the exit code alone); a config that exists without a models-dir.pipeline entry is HOLD, untouched."""
    cache = tmp_path / "hub"
    monkeypatch.setenv("HF_HUB_CACHE", str(cache))
    monkeypatch.delenv("CONCLAVE_MINERU_MODELS_DIR", raising=False)
    cfg = tmp_path / "home" / "mineru.json"
    cfg.parent.mkdir(parents=True)
    monkeypatch.setenv("MINERU_TOOLS_CONFIG_JSON", str(cfg))
    snap = cache / "models--org--pek" / "snapshots" / ("f" * 40)
    m, envs, spoke, log = _pinned_setup(tmp_path, monkeypatch, {"p": _mineru_model(tmp_path)})
    _fake_mineru_cli(envs, "import json, os\n"
                     f"open(os.environ['MINERU_TOOLS_CONFIG_JSON'], 'w').write(json.dumps({{'models-dir': {{'pipeline': {str(tmp_path / 'elsewhere')!r}}}}}))\n")
    rep = m.Report()  # exit 0 but the wrong folder: FAIL
    m.pinned_models(rep, {"name": "Rdr"}, spoke, envs, Path(sys.executable), log)
    assert rep.fails == 1 and rep.passes == 0 and "was not written with the pinned snapshot" in capsys.readouterr().out
    cfg.unlink()
    import shutil
    shutil.rmtree(envs / "_mineru_cli")
    _fake_mineru_cli(envs, "import json, os, sys\n"
                     f"open(os.environ['MINERU_TOOLS_CONFIG_JSON'], 'w').write(json.dumps({{'models-dir': {{'pipeline': {str(snap)!r}}}}}))\n"
                     "sys.exit(1)\n")
    rep = m.Report()  # the right folder but exit 1: FAIL too
    m.pinned_models(rep, {"name": "Rdr"}, spoke, envs, Path(sys.executable), log)
    assert rep.fails == 1 and rep.passes == 0 and "exit 1" in capsys.readouterr().out
    cfg.write_text(json.dumps({"other": 1}), encoding="utf-8")
    rep = m.Report()  # a config without a pipeline entry: HOLD, its bytes unchanged
    m.pinned_models(rep, {"name": "Rdr"}, spoke, envs, Path(sys.executable), log)
    assert rep.holds == 1 and rep.passes == 0 and "without a models-dir.pipeline entry" in capsys.readouterr().out
    assert json.loads(cfg.read_text(encoding="utf-8")) == {"other": 1}


def _capture_env(envs: Path, name: str, script: str) -> None:
    """A venv with a stand-in conclave_locutus_rulings.wiring (same capture_state rule) and the launcher's exe."""
    import subprocess
    import sysconfig
    env = envs / name
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(env)], check=True)
    site = env / Path(sysconfig.get_path("purelib")).relative_to(sysconfig.get_path("data"))
    pkg = site / "conclave_locutus_rulings"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "wiring.py").write_text(
        "import os\ndef capture_state():\n"
        "    return 'Locutus capture: ON' if os.environ.get('CONCLAVE_LOCUTUS_KEY_FILE','').strip() "
        "else 'Locutus capture: OFF (no key)'\n", encoding="utf-8")
    exe = env / ("Scripts" if sys.platform == "win32" else "bin") / (script + (".exe" if sys.platform == "win32" else ""))
    exe.write_text("", encoding="utf-8")


def test_locutus_capture_key_made_once_never_shown_and_launchers_switch_it_on(tmp_path: Path, monkeypatch, capsys) -> None:
    """Decision 57 A: a random key in the user profile (outside OneDrive, the install folder and every repo), made
    only if none exists, never printed; each review launcher sets it for its own window, checked to read ON."""
    m = _mod()
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        monkeypatch.delenv(var, raising=False)
    root = tmp_path / "AdAstra"
    envs = root / "envs"
    envs.mkdir(parents=True)
    _capture_env(envs, "workbench", "conclave-workbench")
    rep = m.Report()
    m.locutus_capture(rep, envs, root, dry=False)  # the review console env is not built: a WARN, never a false ON
    out = capsys.readouterr().out
    key = m.locutus_key_path()
    secret = key.read_text(encoding="ascii")
    assert len(secret) == 64 and int(secret, 16) >= 0 and key.parent.parent.parent == home
    assert secret not in out and rep.fails == 0, out
    launcher = (root / "Open Workbench.cmd").read_text(encoding="utf-8")
    assert f'set "CONCLAVE_LOCUTUS_KEY_FILE={key}"' in launcher and secret not in launcher
    assert "conclave-workbench" in launcher and not (root / "Open Review Console.cmd").exists()
    assert "Open Workbench.cmd" in out and "reviewconsole environment not built" in out
    rep = m.Report()
    m.locutus_capture(rep, envs, root, dry=False)  # a second run: the key is never overwritten, loudly
    out = capsys.readouterr().out
    assert key.read_text(encoding="ascii") == secret and "NOT overwritten" in out
    assert m.make_locutus_key(key) is False and key.read_text(encoding="ascii") == secret


def test_locutus_capture_refuses_a_bad_key_place_and_a_launcher_it_did_not_write(tmp_path: Path, monkeypatch, capsys) -> None:
    """A failed step leaves capture off and says why; nothing of Jake's is replaced."""
    m = _mod()
    root = tmp_path / "AdAstra"
    envs = root / "envs"
    envs.mkdir(parents=True)
    home = tmp_path / "OneDrive - Home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("OneDrive", str(home))
    rep = m.Report()
    m.locutus_capture(rep, envs, root, dry=False)
    assert rep.fails == 1 and "inside OneDrive" in capsys.readouterr().out and not home.exists()
    monkeypatch.delenv("OneDrive")
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    assert "git repository" in m._key_place_problem(repo / "k" / "key", root)
    assert "install folder" in m._key_place_problem(root / "keys" / "key", root)
    assert m._key_place_problem(tmp_path / "plain" / "k" / "key", root) is None
    mine = root / "Open Workbench.cmd"
    mine.write_text("@echo off\r\nJake's own launcher\r\n", encoding="utf-8")
    assert "left untouched" in m._write_launcher(mine, tmp_path / "key", tmp_path / "exe")
    assert "Jake's own launcher" in mine.read_text(encoding="utf-8")
    rep = m.Report()
    m.locutus_capture(rep, envs, root, dry=True)  # a dry run writes nothing
    assert rep.fails == 0 and not (home / ".adastra_keys").exists()
