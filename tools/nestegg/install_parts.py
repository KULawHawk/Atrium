"""Build every part's environment and prove it is complete (Nestegg phase 2; run with python -I).

Jake 11/22 12:20 AM CT: "Any packages or anything that is used, referenced, etc. needs to be
included as part of the build." So each part (parts.json) gets its own environment, its
in-repo closure, its torch pin, its side engines and its model files, and then a PROBE imports
every module of the part plus every outside package its code names. Anything missing is a FAIL
row naming it. Nothing is skipped quietly; a model file with no pin yet is a FAIL ("not pinned").

Ported from the proven pod kit (POD_CALIB_GPU_v5.sh) to Windows and Linux.

  python -I install_parts.py --src <folder holding Conclave, locutus, sequoia, obsidian, atrium>
                             --envs <folder for environments> [--only A,B] [--dry-run]
Last line: NESTEGG-PARTS: PASS | HOLD n | FAIL n (exit 0 / 2 / 1)
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
WIN = os.name == "nt"
STD = set(sys.stdlib_module_names)


class Report:
    def __init__(self) -> None:
        self.fails = 0
        self.holds = 0

    def row(self, status: str, what: str, detail: str) -> None:
        if status == "FAIL":
            self.fails += 1
        if status == "HOLD":  # left out on purpose until Jake decides; never reported as PASS
            self.holds += 1
        print(f"{status:<5} {what:<30} {detail}", flush=True)


# ---------------------------------------------------------------- helpers
def env_python(env: Path) -> Path:
    return env / ("Scripts/python.exe" if WIN else "bin/python")


def env_bin(env: Path, name: str) -> Path:
    return env / ("Scripts" if WIN else "bin") / (name + (".exe" if WIN else ""))


def base_python(ver: str) -> list[str] | None:
    """The interpreter for a Python version: the py launcher on Windows, pythonX.Y elsewhere."""
    cands = [["py", f"-{ver}"]] if WIN else [[f"python{ver}"]]
    for c in cands:
        try:
            r = subprocess.run(c + ["-c", "import sys; print(sys.version_info[:2])"], capture_output=True, text=True)
        except OSError:
            continue
        if r.returncode == 0 and r.stdout.strip() == str(tuple(int(x) for x in ver.split("."))):
            return c
    return None


def run(cmd: list[str], log: Path, cwd: Path | None = None, env: dict | None = None) -> int:
    with log.open("a", encoding="utf-8") as fh:
        fh.write("\n$ " + " ".join(map(str, cmd)) + "\n")
        fh.flush()
        try:
            return subprocess.run(list(map(str, cmd)), stdout=fh, stderr=subprocess.STDOUT, cwd=cwd, env=env).returncode
        except OSError as exc:  # a missing program is a named FAIL upstream, never a crash
            fh.write(f"could not start: {exc}\n")
            return 127


def has_nvidia() -> bool:
    exe = shutil.which("nvidia-smi")
    return bool(exe) and subprocess.run([exe], capture_output=True).returncode == 0


def free_gb(path: Path) -> float:
    path.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(path).free / 1e9


# ---------------------------------------------------------------- in-repo closure (from the pod kit)
def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _req_name(req: str) -> str:
    return _norm(re.split(r"[\s<>=!~;\[(]", req.strip(), maxsplit=1)[0])


def closure(repo: Path, roots: list[str]) -> list[str]:
    """pip arguments for the roots plus every in-repo distribution they depend on (editable)."""
    if roots == ["."] or (len(roots) == 1 and roots[0].startswith(".[")):
        return ["-e", str(repo) + roots[0][1:]]
    dists = {}
    for pp in sorted(repo.glob("conclave_*/pyproject.toml")):
        proj = tomllib.loads(pp.read_text(encoding="utf-8")).get("project", {})
        if proj.get("name"):
            dists[_norm(proj["name"])] = (pp.parent, proj.get("dependencies", []), proj.get("optional-dependencies", {}))
    by_dir = {d.name: n for n, (d, _, _) in dists.items()}
    todo, seen, extras = [], [], {}
    for r in roots:
        d, _, ex = r.partition("[")
        if d not in by_dir:
            raise SystemExit(f"closure: {d} is not a conclave_* distribution in {repo}")
        todo.append(by_dir[d])
        if ex:
            extras[by_dir[d]] = ex.rstrip("]")
    while todo:
        n = todo.pop(0)
        if n in seen:
            continue
        seen.append(n)
        _, deps, opt = dists[n]
        reqs = list(deps)
        for e in filter(None, extras.get(n, "").split(",")):
            reqs += opt.get(e, [])
        todo += [_req_name(q) for q in reqs if _req_name(q) in dists]
    out: list[str] = []
    for n in seen:
        out += ["-e", str(dists[n][0]) + (f"[{extras[n]}]" if n in extras else "")]
    return out


# ---------------------------------------------------------------- what the code imports (for the probe)
def scan_imports(dirs: list[Path], local: set[str], skip: tuple[str, ...] = ()) -> tuple[list[str], list[str]]:
    """Packages of the part, and every outside top-level module its non-test code imports."""
    pkgs, mods = [], set()
    for d in dirs:
        base = d / "src" if (d / "src").is_dir() else d
        pkgs += [c.name for c in base.iterdir() if c.is_dir() and (c / "__init__.py").exists()
                 and c.name not in ("tests", "test", "scripts", "docs")]
        for f in d.rglob("*.py"):
            rel = f.relative_to(d).parts
            local.add(f.stem)  # a flat-script part imports its sibling files by name
            if any(p in ("tests", "test", "docs", "scripts") or p.startswith(".") for p in rel) or f.name.startswith("test_") \
                    or f.name in ("conftest.py",) or "test_support" in f.name \
                    or any(f.relative_to(d).as_posix().startswith(k) for k in skip):
                continue
            try:
                tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    mods |= {a.name.split(".")[0] for a in n.names}
                elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                    mods.add(n.module.split(".")[0])
    third = sorted(m for m in mods if m not in STD and m not in local and m not in pkgs and m != "__future__")
    return sorted(set(pkgs)), third


PROBE = r'''
import importlib, json, pkgutil, sys
pkgs, third = sys.argv[1].split(","), sys.argv[2].split(",")
bad = {}
for p in filter(None, pkgs):
    try:
        m = importlib.import_module(p)
    except BaseException as e:
        bad[p] = f"{type(e).__name__}: {e}"[:200]; continue
    for mi in pkgutil.walk_packages(getattr(m, "__path__", []), p + "."):
        if ".tests" in mi.name or mi.name.endswith("__main__"):
            continue
        try:
            importlib.import_module(mi.name)
        except BaseException as e:
            bad[mi.name] = f"{type(e).__name__}: {e}"[:200]
for t in filter(None, third):
    try:
        importlib.import_module(t)
    except BaseException as e:
        bad[t] = f"{type(e).__name__}: {e}"[:200]
print(json.dumps(bad))
'''


# ---------------------------------------------------------------- one part
def build_part(rep: Report, part: dict, cfg: dict, src: Path, envs: Path, dry: bool, gpu: bool, local: set[str]) -> None:
    name = part["name"]
    repo = src / part["repo"]
    env = envs / name
    log = envs / "_logs" / f"{name}.log"
    if not repo.is_dir():
        rep.row("FAIL", name, f"source folder missing: {repo}")
        return
    tor = cfg["torch"].get(part.get("torch", ""), None)
    if dry:
        rep.row("TODO", name, f"Python {part['python']}, {' '.join(part['roots'])}"
                + (f", {' '.join(tor['pins'])}" if tor else "") + (f", +{','.join(part.get('add', []))}" if part.get("add") else ""))
        return
    log.parent.mkdir(parents=True, exist_ok=True)
    need = part.get("free_gb", 5)
    if free_gb(envs) < need:
        rep.row("FAIL", name, f"needs {need} GB free in {envs}, has {free_gb(envs):.1f}; refusing to start")
        return
    base = base_python(part["python"])
    if not base:
        rep.row("FAIL", name, f"Python {part['python']} not found (phase 1 installs it)")
        return
    if not env_python(env).exists() and run(base + ["-m", "venv", env], log):
        rep.row("FAIL", name, f"could not create the environment (see {log})")
        return
    py = env_python(env)
    run([py, "-m", "pip", "install", "--upgrade", "pip"], log)
    cons = envs / "_logs" / f"{name}.constraints.txt"
    lines = list(tor["pins"]) if tor else []
    if part.get("gate3"):
        names = set(cfg["gate3_constraints"]["names"])
        f = src / cfg["gate3_constraints"]["file"]
        if not f.is_file():
            rep.row("FAIL", name, f"constraints file missing: {f}")
            return
        lines += [ln for ln in f.read_text(encoding="utf-8").splitlines() if ln.split("==")[0].lower() in names]
    cons.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if tor:
        idx = cfg["torch"]["index_gpu" if gpu else "index_cpu"]
        if run([py, "-m", "pip", "install", *tor["pins"], "--index-url", idx], log):
            rep.row("FAIL", name, f"torch install failed from {idx} (see {log})")
            return
    args = closure(repo, part["roots"]) + list(part.get("add", []))
    for r in part.get("add_repos", []):
        args += ["-e", str(src / r)]
    if run([py, "-m", "pip", "install", "-c", cons, *args], log):
        rep.row("FAIL", name, f"pip install failed (see {log})")
        return
    rep.row("PASS", name, "installed")
    side_envs(rep, part, src, envs, log, py)
    models(rep, part, src, repo, envs, py, log)  # before the probe: a model can be an importable package
    probe(rep, part, repo, py, local, log)
    for prog in part.get("programs", []):
        rep.row("PASS" if shutil.which(prog) else "FAIL", f"{name} needs {prog}",
                "found" if shutil.which(prog) else "not on PATH (phase 1 installs it)")
    run([py, "-m", "pip", "freeze"], envs / "_logs" / f"{name}.freeze.txt")


def side_envs(rep: Report, part: dict, src: Path, envs: Path, log: Path, py: Path) -> None:
    se = part.get("side_env")
    if se:
        env = envs / f"_{se['name']}_cli"
        base = base_python(se["python"])
        if not base:
            rep.row("FAIL", f"{part['name']} engine", f"Python {se['python']} not found")
            return
        if (not env_python(env).exists() and run(base + ["-m", "venv", env], log)) or \
                run([env_python(env), "-m", "pip", "install", *se["packages"]], log):
            rep.row("FAIL", f"{part['name']} engine", f"{' '.join(se['packages'])} did not install (see {log})")
            return
        exe = env_bin(env, se["check"][0])
        ok = exe.exists() and run([exe, *se["check"][1:]], log) == 0
        rep.row("PASS" if ok else "FAIL", f"{part['name']} engine", f"{se['check'][0]} {'runs' if ok else 'does not run'}")
    sse = part.get("spoke_side_env")
    if sse:
        base = base_python(sse["python"])
        script = src / part["repo"] / part["roots"][0].split("[")[0] / sse["script"]
        if not base or not script.is_file():
            rep.row("FAIL", f"{part['name']} side env", f"Python {sse['python']} or {script} missing")
            return
        exe = subprocess.run(base + ["-c", "import sys; print(sys.executable)"], capture_output=True, text=True).stdout.strip()
        if WIN:
            rc = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, "-Python", exe], log)
        else:  # the spoke ships a matching .sh recipe for Linux
            rc = run(["bash", script.with_suffix(".sh"), "--python", exe], log)
        rep.row("PASS" if rc == 0 else "FAIL", f"{part['name']} side env", "built by the spoke's own script" if rc == 0 else f"exit {rc} (see {log})")


def probe(rep: Report, part: dict, repo: Path, py: Path, local: set[str], log: Path) -> None:
    dirs = [repo] if part["roots"][0].startswith(".") else [repo / r.split("[")[0] for r in part["roots"]]
    pkgs, third = scan_imports(dirs, set(local), tuple(part.get("probe_skip", [])))
    ignore = part.get("probe_ignore", {})
    third = [t for t in third if t not in ignore]
    for mod, why in sorted(ignore.items()):
        rep.row("INFO", f"{part['name']} not probed", f"{mod}: {why}")
    hold = part.get("hold", {})
    third = [t for t in third if t not in hold]
    for mod, why in sorted(hold.items()):
        rep.row("HOLD", f"{part['name']} {mod}", why)
    r = subprocess.run([py, "-I", "-c", PROBE, ",".join(pkgs), ",".join(third)], capture_output=True, text=True)
    try:
        bad = json.loads(r.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        rep.row("FAIL", f"{part['name']} load check", f"probe did not finish: {(r.stderr or r.stdout)[-200:]}")
        return
    if bad:
        for mod, err in sorted(bad.items()):
            rep.row("FAIL", f"{part['name']} import", f"{mod}: {err}")
    else:
        rep.row("PASS", f"{part['name']} load check", f"{len(pkgs)} packages and {len(third)} outside modules import")


def models(rep: Report, part: dict, src: Path, repo: Path, envs: Path, py: Path, log: Path) -> None:
    mdir = envs / "_models"
    for m in part.get("models", []):
        label = f"{part['name']} model"
        step = m["step"]
        spoke = repo / part["roots"][0].split("[")[0]
        if step == "unpinned":
            rep.row("FAIL", label, f"{m['what']}: no pinned revision and hash in the project yet, so it is not installed")
        elif step == "htrlens_models":
            rc = run([py, "-I", HERE / "htrlens_models.py"], log)
            rep.row("PASS" if rc == 0 else "FAIL", label, "Kraken + TrOCR fetched, hash-checked, load offline" if rc == 0 else f"see {log}")
        elif step == "spoke_script":
            args = [a.replace("{models}", str(mdir)) for a in m.get("args", [])]
            rc = run([py, m["script"], *args], log, cwd=spoke)
            exp = m.get("expect_abs", "").replace("{models}", str(mdir)) or (str(spoke / m["expect"]) if m.get("expect") else "")
            ok = rc == 0 and (not exp or Path(exp).is_file())
            rep.row("PASS" if ok else "FAIL", label, f"{m['script']} {'done' if ok else 'failed'}" + ("" if ok else f" (see {log})"))
        elif step == "docling_download":
            rc = run([py, "-c", "import sys;from pathlib import Path;from docling.utils.model_downloader import download_models;"
                      "download_models(output_dir=Path(sys.argv[1]))", mdir / "docling_artifacts"], log)
            rep.row("PASS" if rc == 0 else "FAIL", label, "Docling models downloaded" if rc == 0 else f"see {log}")
        elif step == "mineru_download":
            cli = env_python(envs / "_mineru_cli")
            e = dict(os.environ, MINERU_MODEL_SOURCE="huggingface")
            rc = run([cli, "-m", "mineru.cli.models_download", "-s", "huggingface", "-m", "pipeline"], log, env=e)
            rep.row("PASS" if rc == 0 else "FAIL", label, "PDF-Extract-Kit downloaded" if rc == 0 else f"see {log}")
        elif step == "spacy_model":
            rc = run([py, "-m", "pip", "install", m["wheel"]], log)
            chk = ("import sys, en_core_web_sm; from pathlib import Path; from obsidian.detect import PINNED_MODELS, model_sha256;"
                   "d = Path(en_core_web_sm.__file__).parent / sys.argv[1];"
                   "sys.exit(0 if model_sha256(d) == PINNED_MODELS[sys.argv[1]] else 3)")
            ok = rc == 0 and run([py, "-I", "-c", chk, m["name"]], log) == 0
            rep.row("PASS" if ok else "FAIL", label, f"{m['name']} matches Obsidian's own pin" if ok else f"{m['name']} missing or does not match the pin (see {log})")
        else:
            rep.row("FAIL", label, f"unknown model step {step!r}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, required=True)
    ap.add_argument("--envs", type=Path, required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    cfg = json.loads((HERE / "parts.json").read_text(encoding="utf-8"))
    only = {s.strip() for s in a.only.split(",") if s.strip()}
    parts = [p for p in cfg["parts"] if not only or p["name"] in only]
    unknown = only - {p["name"] for p in cfg["parts"]}
    rep = Report()
    for u in sorted(unknown):
        rep.row("FAIL", u, "not a part in parts.json")
    gpu = False if a.dry_run else has_nvidia()
    print(f"Nestegg phase 2: {len(parts)} parts, torch build: {'CUDA' if gpu else 'CPU'}{'  [DRY RUN]' if a.dry_run else ''}")
    local = {"conclave", "sequoia", "locutus", "obsidian", "atrium", "curatorplug_conclave"}
    for r in ("Conclave", "locutus", "sequoia", "obsidian", "atrium"):
        for pp in (a.src / r).glob("**/pyproject.toml") if (a.src / r).is_dir() and not a.dry_run else []:
            for b in (pp.parent / "src", pp.parent):
                if b.is_dir():
                    local |= {c.name for c in b.iterdir() if c.is_dir() and (c / "__init__.py").exists()}
    for p in parts:
        build_part(rep, p, cfg, a.src, a.envs, a.dry_run, gpu, local)
    if rep.fails:
        print(f"NESTEGG-PARTS: FAIL {rep.fails}" + (f" (and {rep.holds} held for Jake's decision)" if rep.holds else ""))
    elif rep.holds:
        print(f"NESTEGG-PARTS: HOLD {rep.holds} (everything else passed; the held items wait on Jake's decision)")
    else:
        print("NESTEGG-PARTS: PASS")
    return 1 if rep.fails else (2 if rep.holds else 0)


if __name__ == "__main__":
    sys.exit(main())
