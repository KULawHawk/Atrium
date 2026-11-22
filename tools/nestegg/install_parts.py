"""Build every part's environment and prove it is complete (Nestegg phase 2; run with python -I).

Jake 11/22 12:20 AM CT: "Any packages or anything that is used, referenced, etc. needs to be
included as part of the build." So each part (parts.json) gets its own environment, its
in-repo closure, its torch pin, its side engines and its model files, and then a PROBE imports
every module of the part plus every outside package its code names. Anything missing is a FAIL
row naming it. Nothing is skipped quietly; a model file with no pin yet is a FAIL ("not pinned").

Exact versions (coordinator 11/22, reading of the same rule): every outside package comes from the
part's known-good list in locks/lists/ (measured by the package accounting thread) and is installed
with --require-hashes against locks/SHA256SUMS_*.txt, then the part's own source with --no-deps,
then `pip check`. A part with no measured list, or a package with no measured hash, is FAIL
"not locked" and is not installed from the open index.

Ported from the proven pod kit (POD_CALIB_GPU_v5.sh) to Windows and Linux.

  python -I install_parts.py --src <folder holding Conclave, locutus, sequoia, obsidian, atrium>
                             --envs <folder for environments> [--only A,B] [--dry-run]
Measured or not (coordinator 11/22): a reader (conclave_lens_*, and the engines) PASSes only on a list MATCHED to a
measured run; otherwise it installs exactly and shows HOLD "locked, not measured". A part that is not a reader
PASSes on a list resolved today only when its own tests pass under that exact locked set (the test tools come
from locks/lists/_test_tools_py<ver>.txt, hash-checked); otherwise HOLD.
Last line: NESTEGG-PARTS: PASS n | HOLD n, PASS n | FAIL n, HOLD n, PASS n (exit 0 / 2 / 1)
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
LOCKS = HERE / "locks"
CFG_LOCK: dict = {}  # parts.json, filled by main() (side_envs reads the lock settings from it)
WIN = os.name == "nt"
STD = set(sys.stdlib_module_names)


class Report:
    def __init__(self) -> None:
        self.fails = 0
        self.holds = 0
        self.passes = 0

    def row(self, status: str, what: str, detail: str) -> None:
        if status == "FAIL":
            self.fails += 1
        if status == "PASS":
            self.passes += 1
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


# ---------------------------------------------------------------- exact-version locks (with hashes)
def _dist_ver(fn: str) -> tuple[str, str]:
    if fn.endswith(".whl"):
        d, v = fn.split("-")[:2]
    else:
        d, v = re.sub(r"\.(tar\.gz|zip)$", "", fn).rsplit("-", 1)
    return _norm(d), v


def load_sums(win: bool) -> dict[tuple[str, str], list[str]]:
    """(name, version) -> the measured sha256 values of the saved files for this platform."""
    out: dict[tuple[str, str], list[str]] = {}
    for f in ("SHA256SUMS_win_amd64.txt",) if win else ("SHA256SUMS_linux_x86_64.txt", "SHA256SUMS_cu124_linux.txt"):
        out_f = LOCKS / f
        if not out_f.is_file():
            continue
        for ln in out_f.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                h, fn = ln.split()
                out.setdefault(_dist_ver(fn), []).append(h)
    for f in ("SHA256SUMS_sdist.txt",):
        for ln in (LOCKS / f).read_text(encoding="utf-8").splitlines():
            if ln.strip():
                h, fn = ln.split()
                out.setdefault(_dist_ver(fn), []).append(h)
    return out


def read_list(path: Path) -> dict[str, str] | None:
    if not path.is_file():
        return None
    out = {}
    for ln in path.read_text(encoding="utf-8").splitlines():
        if "==" in ln and not ln.lstrip().startswith("#"):
            n, v = ln.strip().split("==", 1)
            out[_norm(n)] = v
    return out


def lock_reqs(pins: dict[str, str], cfg: dict, win: bool, sums: dict) -> tuple[list[str], list[str]]:
    """Requirement lines with every measured hash, and the problems that make it 'not locked'."""
    lk = cfg["lock"]
    pins = dict(pins)
    if win:
        pins = {n: v for n, v in pins.items() if not re.match(lk["linux_only"], n)}
        # a CUDA build named by a pod freeze (torch==2.6.0+cu124) is the CPU build on Windows (no NVIDIA card)
        pins = {n: (v.split("+")[0] if re.match(lk["cuda_local"], v.partition("+")[2]) else v) for n, v in pins.items()}
        for n, x in lk["windows_extras"].items():
            if n not in pins and any(t in pins for t in x["when"]):
                pins[n] = x["version"]
    lines, probs = [], []
    for n, v in sorted(pins.items()):
        hs = sums.get((n, v))
        if hs:
            lines.append(f"{n}=={v} " + " ".join(f"--hash=sha256:{h}" for h in sorted(set(hs))))
        else:
            probs.append(f"{n}=={v} has no measured hash for {'Windows' if win else 'Linux'}")
    return lines, probs


def part_lock(part: dict, cfg: dict, src: Path, win: bool, gpu: bool, sums: dict) -> tuple[list[str], list[str]]:
    pins = read_list(LOCKS / "lists" / f"{part['name']}_py{part['python']}.txt")
    if pins is None:
        return [], [f"no known-good list measured yet (locks/lists/{part['name']}_py{part['python']}.txt)"]
    probs = []
    for a in part.get("add", []):
        want = a.split("==")[1] if "==" in a else None
        if _req_name(a) not in pins or (want and pins[_req_name(a)] != want):
            probs.append(f"parts.json adds {a}, the known-good list has {pins.get(_req_name(a), 'nothing')}")
    tor = cfg["torch"].get(part.get("torch", ""))
    for t in tor["pins"] if tor else []:
        n, v = t.split("==")
        if pins.get(n, "").split("+")[0] != v:
            probs.append(f"parts.json pins {t}, the known-good list has {pins.get(n, 'nothing')}")
    if win and gpu and "torch" in pins:  # the CPU build would run, but it is not what a GPU PC should get
        probs.append("CUDA torch for Windows has no measured hash yet (only the CPU build is measured)")
    if part.get("gate3"):
        f = src / cfg["gate3_constraints"]["file"]
        names = {_norm(x) for x in cfg["gate3_constraints"]["names"]}
        g = read_list(f)
        if g is None:
            probs.append(f"constraints file missing: {f}")
        else:
            probs += [f"gate-3 constraint {n}=={g[n]}, the known-good list has {pins.get(n, 'nothing')}"
                      for n in sorted(names & set(g) & set(pins)) if pins[n] != g[n]]  # a constraint only binds what is installed
    lines, more = lock_reqs(pins, cfg, win, sums)
    return lines, probs + more


def is_reader(part: dict) -> bool:
    """Anything whose output was or will be calibrated: the lens spokes."""
    return any(r.startswith("conclave_lens_") for r in part["roots"])


def own_tests(rep: Report, part: dict, repo: Path, py: Path, envs: Path, log: Path, done: str, status: str) -> None:
    """A part that is not a reader is measured by its own tests passing under the exact locked set."""
    name = part["name"]
    tools = read_list(LOCKS / "lists" / f"_test_tools_py{part['python']}.txt")
    if tools is None:
        rep.row("HOLD", name, f"{done}; {status}; its own tests not run under this set yet (no locked test-tools list)")
        return
    lines, probs = lock_reqs(tools, CFG_LOCK, WIN, load_sums(WIN))
    if probs or locked_install(py, lines, envs / "_logs" / f"{name}.testtools.txt", log):
        rep.row("HOLD", name, f"{done}; {status}; test tools could not be installed locked ({'; '.join(probs) or 'see ' + str(log)})")
        return
    dirs = [repo / "tests"] if part["roots"][0].startswith(".") else [repo / r.split("[")[0] / "tests" for r in part["roots"]]
    dirs = [d for d in dirs if d.is_dir()]
    if not dirs:
        rep.row("HOLD", name, f"{done}; {status}; it has no tests folder to measure it by")
        return
    own = read_list(LOCKS / "lists" / f"{name}_py{part['python']}.txt") or {}
    noqt = [] if {"pyside6", "pyqt5", "pyqt6"} & set(own) else ["-p", "no:pytest-qt"]  # pytest-qt aborts without a Qt binding
    rc = 0
    for d in dirs:  # from the project folder, as its own CI runs them (its pytest settings and import paths apply)
        rc = rc or run([py, "-m", "pytest", "-q", "-p", "no:cacheprovider", *noqt, "tests"], log, cwd=d.parent)
    if rc == 0:
        rep.row("PASS", name, f"{done}; {status}; its own tests pass under this exact set")
    else:
        rep.row("FAIL", name, f"{done}; its own tests fail under this exact set (exit {rc}, see {log})")


def list_status(name: str) -> str:
    for ln in (LOCKS / "LIST_STATUS.txt").read_text(encoding="utf-8").splitlines():
        if ln.startswith(name + ":"):
            return ln.split(":", 1)[1].strip()
    return "no status recorded"


def locked_install(py: Path, lines: list[str], lockfile: Path, log: Path) -> int:
    if not lines:  # a part with no outside packages (an empty known-good list)
        return 0
    lockfile.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return run([py, "-m", "pip", "install", "--require-hashes", "--no-deps", "-r", lockfile], log)


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
def build_part(rep: Report, part: dict, cfg: dict, src: Path, envs: Path, dry: bool, gpu: bool, local: set[str],
               sums: dict | None = None) -> None:
    name = part["name"]
    repo = src / part["repo"]
    env = envs / name
    log = envs / "_logs" / f"{name}.log"
    if not repo.is_dir():
        rep.row("FAIL", name, f"source folder missing: {repo}")
        return
    tor = cfg["torch"].get(part.get("torch", ""), None)
    lines, probs = part_lock(part, cfg, src, WIN, gpu, sums if sums is not None else load_sums(WIN))
    for p in probs:
        rep.row("FAIL", f"{name} not locked", p)
    if dry:
        rep.row("TODO", name, f"Python {part['python']}, {' '.join(part['roots'])}"
                + (f", {' '.join(tor['pins'])}" if tor else "") + (f", +{','.join(part.get('add', []))}" if part.get("add") else ""))
        return
    if probs:
        return  # never installed from the open index
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
    if locked_install(py, lines, envs / "_logs" / f"{name}.lock.txt", log):
        rep.row("FAIL", name, f"locked install failed (see {log})")
        return
    args = closure(repo, part["roots"])
    for r in part.get("add_repos", []):
        args += ["-e", str(src / r)]
    if run([py, "-m", "pip", "install", "--no-deps", *args], log):
        rep.row("FAIL", name, f"installing the part's own source failed (see {log})")
        return
    chk = subprocess.run([py, "-m", "pip", "check"], capture_output=True, text=True)
    if chk.returncode:
        for ln in (chk.stdout or chk.stderr).strip().splitlines():
            rep.row("FAIL", f"{name} pip check", ln)
        return
    status = list_status(f"{name}_py{part['python']}.txt")
    done = f"installed {len(lines)} locked packages (hash-checked) + its own source; pip check clean"
    if status.startswith("MATCHED") or status.startswith("empty on purpose"):
        rep.row("PASS", name, f"{done}; list measured ({status.split('(')[0].strip()})")
    elif is_reader(part):
        rep.row("HOLD", name, f"{done}; locked, not measured: {status}")
    else:
        own_tests(rep, part, repo, py, envs, log, done, status)
    rep.row("INFO", f"{name} build tools", "pip fetches the build backend for the part's own source (e.g. setuptools) at install time; not locked yet")
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
        label = f"{part['name']} engine"
        lst = f"_{se['name']}_cli_py{se['python']}.txt"
        pins = read_list(LOCKS / "lists" / lst)
        if pins is None:
            rep.row("FAIL", f"{label} not locked", f"no known-good list (locks/lists/{lst}); not built from the open index")
            return
        missing = [p for p in se["packages"] if pins.get(_req_name(p)) != p.split("==")[1]]
        lines, probs = lock_reqs(pins, CFG_LOCK, WIN, load_sums(WIN))
        probs += [f"the engine needs {p}, the known-good list has {pins.get(_req_name(p), 'nothing')}" for p in missing]
        if probs:
            for p in probs:
                rep.row("FAIL", f"{label} not locked", p)
            return
        env = envs / f"_{se['name']}_cli"
        base = base_python(se["python"])
        if not base:
            rep.row("FAIL", label, f"Python {se['python']} not found")
            return
        if (not env_python(env).exists() and run(base + ["-m", "venv", env], log)) or \
                locked_install(env_python(env), lines, envs / "_logs" / f"_{se['name']}_cli.lock.txt", log):
            rep.row("FAIL", label, f"locked install failed (see {log})")
            return
        exe = env_bin(env, se["check"][0])
        ok = exe.exists() and run([exe, *se["check"][1:]], log) == 0
        st = list_status(lst)
        if not ok:
            rep.row("FAIL", label, f"{se['check'][0]} does not run ({len(lines)} locked packages, see {log})")
        elif st.startswith("MATCHED"):
            rep.row("PASS", label, f"{se['check'][0]} runs ({len(lines)} locked packages); list measured")
        else:
            rep.row("HOLD", label, f"{se['check'][0]} runs ({len(lines)} locked packages); locked, not measured: {st}")
    if part.get("spoke_side_env"):
        rep.row("FAIL", f"{part['name']} side env not locked",
                "the spoke's own script installs from the open index without hashes (a known-good list exists in locks/lists "
                "but the script cannot take it yet); needs a hashed install in the spoke (Conclave PR)")


def probe(rep: Report, part: dict, repo: Path, py: Path, local: set[str], log: Path) -> None:
    dirs = [repo] if part["roots"][0].startswith(".") else [repo / r.split("[")[0] for r in part["roots"]]
    for dist in part.get("no_caller", []):  # SET-9: shipped because it is production code, though nothing calls it yet
        rep.row("INFO", f"{part['name']} {dist}", "installed, no shipped caller yet")
    skip = part.get("probe_skip", [])
    if isinstance(skip, dict):  # {folder prefix: why}; every skipped folder is printed with its reason
        for k, why in sorted(skip.items()):
            rep.row("INFO", f"{part['name']} not probed", f"{k}: {why}")
    pkgs, third = scan_imports(dirs, set(local), tuple(skip))
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
            if not ok:
                rep.row("FAIL", label, f"{m['script']} failed (see {log})")
            elif m.get("unpinned"):
                rep.row("FAIL", label, f"{m['script']} fetched it, but {m['unpinned']}; not trusted until pinned")
            else:
                rep.row("PASS", label, f"{m['script']} done (the script pins revision and hash)")
        elif step == "docling_download":
            rc = run([py, "-c", "import sys;from pathlib import Path;from docling.utils.model_downloader import download_models;"
                      "download_models(output_dir=Path(sys.argv[1]))", mdir / "docling_artifacts"], log)
            rep.row("FAIL", label, "Docling models fetched, but with no pinned revision or hash; not trusted until pinned"
                    if rc == 0 else f"Docling model download failed (see {log})")
        elif step == "mineru_download":
            cli = env_python(envs / "_mineru_cli")
            e = dict(os.environ, MINERU_MODEL_SOURCE="huggingface")
            rc = run([cli, "-m", "mineru.cli.models_download", "-s", "huggingface", "-m", "pipeline"], log, env=e)
            rep.row("FAIL", label, "PDF-Extract-Kit fetched, but with no pinned revision or hash; not trusted until pinned"
                    if rc == 0 else f"PDF-Extract-Kit download failed (see {log})")
        elif step == "spacy_model":
            rc = run([py, "-m", "pip", "install", "--no-deps", f"{m['wheel']}#sha256={m['wheel_sha256']}"], log)
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
    # Every import outside the part's own packages is checked in the part's environment, including names from the
    # five repos (Jake 11/22: anything referenced is part of the build). A Conclave part that imports locutus,
    # obsidian or another conclave_* distribution must have it installed, or the probe names it as a FAIL.
    sums = load_sums(WIN)
    CFG_LOCK.update(cfg)
    for p in parts:
        build_part(rep, p, cfg, a.src, a.envs, a.dry_run, gpu, set(), sums)
    counts = f"HOLD {rep.holds}, PASS {rep.passes}"
    if rep.fails:
        print(f"NESTEGG-PARTS: FAIL {rep.fails}, {counts}")
    elif rep.holds:
        print(f"NESTEGG-PARTS: {counts} (not a clean install: each HOLD is installed but waits on a measurement or Jake's decision)")
    else:
        print(f"NESTEGG-PARTS: PASS {rep.passes}")
    return 1 if rep.fails else (2 if rep.holds else 0)


if __name__ == "__main__":
    sys.exit(main())
