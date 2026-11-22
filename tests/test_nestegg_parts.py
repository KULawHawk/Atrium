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


def test_dry_run_writes_nothing_and_never_passes_an_unlocked_part(tmp_path: Path, capsys) -> None:
    for r in ("Conclave", "locutus", "sequoia", "obsidian", "atrium"):
        (tmp_path / "src" / r).mkdir(parents=True)
    rc = _mod().main(["--src", str(tmp_path / "src"), "--envs", str(tmp_path / "envs"), "--dry-run"])
    assert not (tmp_path / "envs").exists()
    out = capsys.readouterr().out
    assert out.count("TODO ") == len(PARTS["parts"])
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
    names = {f"{p['name']}_py{p['python']}.txt" for p in PARTS["parts"]} | {"votingengine_beta_py3.13.txt", "_test_tools_py3.13.txt"}  # betacal hold (PA-3); test tools for non-readers
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
