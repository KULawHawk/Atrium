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
