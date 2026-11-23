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
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCKS = HERE / "locks"
CFG_LOCK: dict = {}  # parts.json, filled by main() (side_envs reads the lock settings from it)
INSTALL_ROOT: dict = {}  # {"root": Path}, filled by main() from --root
PROBE_CFG: dict = {}  # parts.json "probe": modules no shipped code reaches, and outside names never imported on our Pythons
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


def read_engine_file(path: Path) -> dict[str, str] | None:
    """A pip requirements file with exact pins (and --hash continuation lines): {name: version}, extras dropped."""
    if not path.is_file():
        return None
    out = {}
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith(("#", "-", "--")) or "==" not in ln:
            continue
        req = ln.split()[0].rstrip("\\")
        n, v = req.split("==", 1)
        out[_norm(n.split("[")[0])] = v.split(";")[0].strip()
    return out


def engine_markers(path: Path) -> dict[str, str]:
    """{name: platform} for lines an engine file marks `; sys_platform == "linux"` or `"win32"`.
    Any other marker is returned as "?<marker>" so the caller can refuse it (never guessed)."""
    out = {}
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln.startswith("#") or "==" not in ln or ";" not in ln:
            continue
        mk = ln.split(";", 1)[1].rstrip("\\").strip()
        m = re.fullmatch(r"""sys_platform\s*==\s*["'](linux|win32)["']""", mk)
        out[_norm(ln.split("==", 1)[0].split("[")[0])] = m.group(1) if m else f"?{mk}"
    return out


def engine_linux_only(path: Path) -> set[str]:
    """Names an engine file marks `; sys_platform == "linux"` (no Windows wheel; the Windows build leaves them out)."""
    return {n for n, p in engine_markers(path).items() if p == "linux"}


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
    locals_ = sorted({v.partition("+")[2] for v in pins.values() if re.match(lk["cuda_local"], v.partition("+")[2])})
    for tag in locals_:  # +cu124 files live only on PyTorch's own index; the hash still decides what is accepted
        lines.append(f"--extra-index-url https://download.pytorch.org/whl/{tag}")
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
    return part["roots"][0].startswith("conclave_lens_")  # the part's own spoke; a lens it carries does not make it one


def own_tests(rep: Report, part: dict, repo: Path, py: Path, envs: Path, log: Path, done: str, status: str) -> None:
    """A part that is not a reader is measured by its own tests passing under the exact locked set."""
    name = part["name"]
    if part.get("test_env"):
        py = _test_env(rep, part, repo, envs, log, done, status)
        if py is None:
            return
        tools = {}  # the test environment is a full locked environment of its own, test tools included
    else:
        tools = read_list(LOCKS / "lists" / f"_test_tools_py{part['python']}.txt")
    if tools is None:
        rep.row("HOLD", name, f"{done}; {status}; its own tests not run under this set yet (no locked test-tools list)")
        return
    lines, probs = lock_reqs(tools, CFG_LOCK, WIN, load_sums(WIN)) if tools else ([], [])
    if probs or locked_install(py, lines, envs / "_logs" / f"{name}.testtools.txt", log):
        rep.row("HOLD", name, f"{done}; {status}; test tools could not be installed locked ({'; '.join(probs) or 'see ' + str(log)})")
        return
    # the part's own spoke's tests; a spoke it carries (a lens, a plugin) is proven by its own part
    dirs = [repo / "tests"] if part["roots"][0].startswith(".") else [repo / part["roots"][0].split("[")[0] / "tests"]
    dirs = [d for d in dirs if d.is_dir()]
    if not dirs:
        rep.row("HOLD", name, f"{done}; {status}; it has no tests folder to measure it by")
        return
    own = read_list(LOCKS / "lists" / f"{name}_py{part['python']}.txt") or {}
    noqt = [] if {"pyside6", "pyqt5", "pyqt6"} & set(own) else ["-p", "no:pytest-qt"]  # pytest-qt aborts without a Qt binding
    rc = 0
    for d in dirs:  # from the project folder, as its own CI runs them (its pytest settings and import paths apply)
        rc = rc or run([py, "-m", "pytest", "-q", "-p", "no:cacheprovider", *noqt, "tests"], log, cwd=d.parent)
    where = "its locked test environment" if part.get("test_env") else "this exact set"
    if part.get("test_env") and (envs / f"{name}-test" / TEST_ENV_MARK).is_file():
        shutil.rmtree(envs / f"{name}-test", ignore_errors=True)  # used only for the proof; never left installed (Decision 50 A)
    if rc == 0:
        rep.row("PASS", name, f"{done}; {status}; its own tests pass under {where}")
    else:
        rep.row("FAIL", name, f"{done}; its own tests fail under {where} (exit {rc}, see {log})")


TEST_ENV_MARK = "adastra_scratch_test_env.json"  # Decision 50 A: names a scratch test folder this installer made


def _test_env(rep: Report, part: dict, repo: Path, envs: Path, log: Path, done: str, status: str) -> Path | None:
    """Some parts' tests need packages the installed part must not carry (e.g. a sibling's conflicting pin), so
    they run in a separate locked environment, built only for the test run and deleted after it."""
    name, te = part["name"], part["test_env"]
    pins = read_list(LOCKS / "lists" / te["list"])
    lines, probs = lock_reqs(pins, CFG_LOCK, WIN, load_sums(WIN)) if pins is not None else ([], [f"no list {te['list']}"])
    if probs:
        rep.row("HOLD", name, f"{done}; {status}; its test environment is not locked ({'; '.join(probs)})")
        return None
    env = envs / f"{name}-test"
    if env.exists() and not (env / TEST_ENV_MARK).is_file():  # Decision 50 A: only a folder this installer made is removed
        rep.row("HOLD", name, f"{done}; {status}; {env} already exists and was not made by this installer; left untouched")
        return None
    shutil.rmtree(env, ignore_errors=True)  # an earlier run's own scratch test folder (it carries the marker)
    base = base_python(part["python"])
    if base is None or run(base + ["-m", "venv", env], log):
        rep.row("HOLD", name, f"{done}; {status}; could not create its test environment (see {log})")
        return None
    try:
        (env / TEST_ENV_MARK).write_text(json.dumps({"part": name, "scratch_test_env": True}) + "\n", encoding="utf-8")
    except OSError as exc:
        rep.row("HOLD", name, f"{done}; {status}; could not mark its test environment ({exc})")
        return None
    py = env_python(env)
    if locked_install(py, lines, envs / "_logs" / f"{name}.testenv.txt", log) \
            or run([py, "-m", "pip", "install", "--no-deps", *closure(repo, te["roots"])], log):
        rep.row("FAIL", name, f"{done}; its locked test environment could not be installed (see {log})")
        shutil.rmtree(env, ignore_errors=True)
        return None
    chk = subprocess.run([py, "-m", "pip", "check"], capture_output=True, text=True)
    if chk.returncode:
        rep.row("FAIL", name, f"{done}; its test environment fails pip check: {(chk.stdout or chk.stderr).strip()[:200]}")
        shutil.rmtree(env, ignore_errors=True)
        return None
    return py


def list_status(name: str) -> str:
    for ln in (LOCKS / "LIST_STATUS.txt").read_text(encoding="utf-8").splitlines():
        if ln.startswith(name + ":"):
            return ln.split(":", 1)[1].strip()
    return "no status recorded"


def _saved_copies():
    """saved_copies.py loaded by path (python -I does not put this folder on sys.path)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("nestegg_saved_copies", HERE / "saved_copies.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def saved_file_names() -> dict[str, str]:
    """sha256 -> saved file name, from every SHA256SUMS file (the names pip needs in a wheelhouse)."""
    out: dict[str, str] = {}
    for f in sorted(LOCKS.glob("SHA256SUMS_*.txt")):
        for ln in f.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                h, fn = ln.split()
                out[h] = fn
    return out


def _saved_say(m: str, fh) -> None:
    """Every saved-copy line goes to the part's log; a copy whose bytes changed is also a WARN row on screen
    (Jake's no-silent-failure rule): the install still goes on from the next copy, but nobody misses it."""
    fh.write(m + "\n")
    if m.startswith("WARN"):
        print(f"{'WARN':<5} {'saved copy changed':<30} {m[6:].strip()}", flush=True)


def saved_wheelhouse(lines: list[str], wheelhouse: Path, log: Path) -> tuple[Path | None, bool]:
    """Decision 30 A: take each locked file from the saved copies first (home, then the private release), into a
    wheelhouse with its real name. Returns (wheelhouse or None, every file found). Files not found come from the
    original index inside pip, still under --require-hashes; nothing is ever taken without its measured hash."""
    sc = _saved_copies()
    cfg = sc.load_config()
    locs = [loc for loc in cfg["locations"] if loc["kind"] != "origin"]
    root = INSTALL_ROOT.get("root") or wheelhouse.parent
    if not sc.usable(locs, root):
        return None, False
    names = saved_file_names()
    want: dict[str, str] = {}
    for ln in lines:
        hs = re.findall(r"--hash=sha256:([0-9a-f]{64})", ln)
        got = [h for h in hs if h in names]
        if got:
            want[got[0]] = names[got[0]]  # one platform file per requirement is enough for pip
    found = 0
    with log.open("a", encoding="utf-8") as fh:
        for h, fn in sorted(want.items()):
            src = sc.fetch(h, None, fn, wheelhouse / fn, {"locations": locs}, root, say=lambda m: _saved_say(m, fh))
            found += src is not None
            fh.write(f"saved copy: {fn} <- {src or 'not in any saved copy (original index, hash-checked)'}\n")
    req_lines = [ln for ln in lines if not ln.startswith("--")]
    return wheelhouse, found == len(req_lines) and found == len(want)


def locked_install(py: Path, lines: list[str], lockfile: Path, log: Path) -> int:
    if not lines:  # a part with no outside packages (an empty known-good list)
        return 0
    lockfile.write_text("\n".join(lines) + "\n", encoding="utf-8")
    wh, complete = saved_wheelhouse(lines, lockfile.parent.parent / "_wheelhouse", log)
    extra = (["--no-index"] if complete else []) + (["--find-links", str(wh)] if wh else [])
    return run([py, "-m", "pip", "install", "--require-hashes", "--no-deps", *extra, "-r", lockfile], log)


# ---------------------------------------------------------------- what the code imports (for the probe)
def _modname(f: Path, base: Path, d: Path) -> str:
    rel = f.relative_to(base if f.is_relative_to(base) else d).with_suffix("").parts
    return ".".join(rel[:-1] if rel[-1] == "__init__" else rel)


def _not_reached(mod: str, skip_mods: tuple[str, ...]) -> bool:
    return any(mod == k or mod.startswith(k + ".") for k in skip_mods)


def scan_imports(dirs: list[Path], local: set[str], skip: tuple[str, ...] = (),
                 skip_mods: tuple[str, ...] = ()) -> tuple[list[str], list[str]]:
    """Packages of the part, and every outside top-level module its non-test code imports."""
    pkgs, mods = [], set()
    for d in dirs:
        base = d / "src" if (d / "src").is_dir() else d
        pkgs += [c.name for c in base.iterdir() if c.is_dir() and (c / "__init__.py").exists()
                 and c.name not in ("tests", "test", "scripts", "docs")]
        # a src-layout distribution installs only src/: tools/ and other loose scripts next to it never reach the env
        for f in base.rglob("*.py"):
            rel = f.relative_to(d).parts
            local.add(f.stem)  # a flat-script part imports its sibling files by name
            if any(p in ("tests", "test", "docs", "scripts") or p.startswith(".") for p in rel) or f.name.startswith("test_") \
                    or f.name in ("conftest.py",) or "test_support" in f.name \
                    or any(f.relative_to(d).as_posix().startswith(k) for k in skip) \
                    or _not_reached(_modname(f, base, d), skip_mods):
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
skip = tuple(filter(None, sys.argv[3].split(","))) if len(sys.argv) > 3 else ()
bad = {}
for p in filter(None, pkgs):
    try:
        m = importlib.import_module(p)
    except BaseException as e:
        bad[p] = f"{type(e).__name__}: {e}"[:200]; continue
    for mi in pkgutil.walk_packages(getattr(m, "__path__", []), p + "."):
        if ".tests" in mi.name or mi.name.endswith("__main__") or any(mi.name == k or mi.name.startswith(k + ".") for k in skip):
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
    # SET-11: the working environment is set aside (kept under a dated name, never deleted) and the new one is built at
    # the real path (a venv's launchers hold their own path, so it is not built elsewhere and moved). It stays only if
    # its own verdict and import probe pass; otherwise the previous one is put back and the failed build is kept beside.
    leftover_copies(rep, name, env)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    # An environment counts as a working copy only if it carries VERIFIED, written after its verdict and probe
    # passed. Every build writes BUILDING first, before the venv exists, so (reviewer 3 on #72, round 2):
    #   VERIFIED                         -> .kept-        (restorable, the last known working copy)
    #   BUILDING only                    -> .unfinished-  (a build a crash interrupted; never restored)
    #   neither, but adastra.json        -> .legacy-      (built before this check existed; restorable, "not verified")
    #   neither, no adastra.json         -> .unfinished-  (never restored)
    aside = None
    if env.exists():
        kind = "kept" if (env / VERIFIED).is_file() else "unfinished" if (env / BUILDING).is_file() \
            else "legacy" if (env / "adastra.json").is_file() else "unfinished"
        aside = env.with_name(f"{name}.{kind}-{stamp}")
        try:
            env.rename(aside)
        except OSError as e:
            rep.row("FAIL", name, f"could not set the existing environment aside ({e}); close any program using {env}, "
                    "then run again. Nothing was changed")
            return
    ok = _build_env(rep, part, src, envs, env, log, base, lines, repo, local, stamp)
    if ok:
        try:
            (env / VERIFIED).write_text(json.dumps({"verified": stamp, "part": name}) + "\n", encoding="utf-8")
        except OSError as e:
            rep.row("FAIL", f"{name} verified marker", f"the new build passed but {env / VERIFIED} could not be "
                    f"written ({e}), so it cannot be counted as a working copy")
            ok = False
    if ok:
        if aside and aside.name.startswith(f"{name}.kept-"):
            rep.row("INFO", f"{name} kept", f"the previous environment is kept at {aside} (last known working copy; "
                    "delete it yourself when you no longer want it)")
        elif aside and aside.name.startswith(f"{name}.legacy-"):
            rep.row("INFO", f"{name} set aside", f"the previous environment was built before this check existed; kept, "
                    f"not verified, at {aside}")
        elif aside:
            rep.row("INFO", f"{name} set aside", f"the previous environment was a build that did not finish; kept, "
                    f"never verified, at {aside}")
        return
    if not aside and not list(envs.glob(f"{name}.kept-*")) and not list(envs.glob(f"{name}.legacy-*")):
        return  # a first install that failed: its FAIL rows already say so; nothing to put back
    failed = env.with_name(f"{name}.failed-{stamp}")
    # put back: the newest verified kept copy, else the newest pre-check (.legacy-) environment from ANY run (a crash
    # in an earlier rebuild must not strand the working legacy copy; reviewer 3 on #72), else nothing
    good = sorted(k for k in envs.glob(f"{name}.kept-*") if (k / VERIFIED).is_file())
    olds = sorted(k for k in envs.glob(f"{name}.legacy-*") if k.is_dir())
    legacy = not good and bool(olds)
    if legacy:
        good = [olds[-1]]
    try:
        if env.exists():
            env.rename(failed)
        if good:
            good[-1].rename(env)
    except OSError as e:
        rep.row("FAIL", f"{name} restore", f"the new build did not pass and putting the last working copy back failed "
                f"({e}). Close any program using these folders and move {good[-1] if good else 'nothing'} back by hand, "
                "or run again")
        return
    if legacy:
        rep.row("WARN", f"{name} restored", f"the new build did not pass, so the previous environment ({good[-1].name}) is "
                f"put back, not verified (it was built before this check existed), at {env}; the failed build is kept "
                f"at {failed}")
    elif good:
        rep.row("WARN", f"{name} restored", f"the new build did not pass, so the last verified working copy "
                f"({good[-1].name}) is back in use at {env}; the failed build is kept at {failed}")
    else:
        rep.row("FAIL", f"{name} no working copy", f"the new build did not pass and there is no verified working copy to "
                f"put back, so {name} is not installed now. The failed build is at {failed}"
                + (f"; the earlier, never-verified environment is at {aside}" if aside else ""))

def _build_env(rep: Report, part: dict, src: Path, envs: Path, env: Path, log: Path, base: list[str], lines: list[str],
               repo: Path, local: set[str], stamp: str = "") -> bool:
    """Build one part's environment at `env`; True when its own verdict and import probe have no FAIL row."""
    name = part["name"]
    try:  # written before the venv exists: an environment holding only this marker is a build that did not finish
        env.mkdir(parents=True, exist_ok=True)
        (env / BUILDING).write_text(json.dumps({"building": stamp, "part": name}) + "\n", encoding="utf-8")
    except OSError as e:
        rep.row("FAIL", f"{name} building marker", f"could not write {env / BUILDING}: {e}")
        return False
    if not env_python(env).exists() and run(base + ["-m", "venv", env], log):
        rep.row("FAIL", name, f"could not create the environment (see {log})")
        return False
    py = env_python(env)
    if locked_install(py, lines, envs / "_logs" / f"{name}.lock.txt", log):
        rep.row("FAIL", name, f"locked install failed (see {log})")
        return False
    args = closure(repo, part["roots"])
    for r in part.get("add_repos", []):
        args += ["-e", str(src / r)]
    if run([py, "-m", "pip", "install", "--no-deps", *args], log):
        rep.row("FAIL", name, f"installing the part's own source failed (see {log})")
        return False
    chk = subprocess.run([py, "-m", "pip", "check"], capture_output=True, text=True)
    if chk.returncode:
        for ln in (chk.stdout or chk.stderr).strip().splitlines():
            rep.row("FAIL", f"{name} pip check", ln)
        return False
    for mod in part.get("must_import", []):  # a library the part reaches lazily (the probe may not see it in code)
        r = subprocess.run([py, "-I", "-c", f"import {mod}"], capture_output=True, text=True)
        if r.returncode:
            rep.row("FAIL", f"{name} import", f"{mod} does not import: {(r.stderr or '').strip().splitlines()[-1:]}")
            return False
    try:  # how an installed program finds the install root (learning folders etc.): <env>/adastra.json, read-only for it
        env.mkdir(parents=True, exist_ok=True)
        (env / "adastra.json").write_text(json.dumps({"install_root": str(INSTALL_ROOT.get("root") or envs.parent),
                                                      "envs": str(envs), "part": name}, indent=1) + "\n", encoding="utf-8")
    except OSError as e:
        rep.row("FAIL", f"{name} root marker", f"could not write {env / 'adastra.json'}: {e}")
        return False
    core = rep.fails  # the environment's own verdict and its import probe decide whether it replaces the old one;
    #                   a reader's unpinned model or a missing program is about the machine, not this environment
    status = list_status(f"{name}_py{part['python']}.txt")
    done = f"installed {len(lines)} locked packages (hash-checked) + its own source; pip check clean"
    if status.startswith("MATCHED") or status.startswith("empty on purpose"):
        rep.row("PASS", name, f"{done}; list measured ({status.split('(')[0].strip()})")
    elif is_reader(part):
        rep.row("HOLD", name, f"{done}; locked, not measured: {status}")
    else:
        own_tests(rep, part, repo, py, envs, log, done, status)
    env_ok = rep.fails == core
    rep.row("INFO", f"{name} build tools", "pip fetches the build backend for the part's own source (e.g. setuptools) at install time; not locked yet")
    side_envs(rep, part, src, envs, log, py)
    models(rep, part, src, repo, envs, py, log)  # before the probe: a model can be an importable package
    if part.get("harness_from"):
        harness(rep, part, envs, py, log)
    before_probe = rep.fails
    probe(rep, part, repo, py, local, log)
    env_ok = env_ok and rep.fails == before_probe
    for prog in part.get("programs", []):
        rep.row("PASS" if shutil.which(prog) else "FAIL", f"{name} needs {prog}",
                "found" if shutil.which(prog) else "not on PATH (phase 1 installs it)")
    run([py, "-m", "pip", "freeze"], envs / "_logs" / f"{name}.freeze.txt")
    return env_ok


def side_envs(rep: Report, part: dict, src: Path, envs: Path, log: Path, py: Path) -> None:
    se = part.get("side_env")
    if se:
        label = f"{part['name']} engine"
        lst = f"_{se['name']}_cli_py{se['python']}.txt"
        pins = read_list(LOCKS / "lists" / lst)
        if pins is None:
            rep.row("FAIL", f"{label} not locked", f"no known-good list (locks/lists/{lst}); not built from the open index")
            return
        if se.get("engine_file"):  # Jake PA-2 A+: the spoke's own engine list is the one source; the saved list must equal it
            ef = src / part["repo"] / se["engine_file"]
            own = read_engine_file(ef)
            if own is None:
                rep.row("INFO", label, f"{se['engine_file']} is not in this checkout yet; building from the saved list {lst}")
            elif own != pins:
                diff = sorted(set(own.items()) ^ set(pins.items()))[:6]
                rep.row("FAIL", f"{label} not locked", f"{se['engine_file']} and the saved list {lst} disagree: {diff}")
                return
            elif bad := sorted(n for n in engine_linux_only(ef) if not re.match(CFG_LOCK["linux_only"], n)):
                # the spoke says Linux-only, but the Windows build would still try to install them: the two disagree
                rep.row("FAIL", f"{label} not locked", f"{se['engine_file']} marks {bad} Linux-only; the installer's "
                        f"linux_only rule ({CFG_LOCK['linux_only']}) does not leave them out on Windows")
                return
            elif extra := sorted(n for n in own if re.match(CFG_LOCK["linux_only"], n) and n not in engine_linux_only(ef)):
                # the installer would skip them on Windows while the spoke's own setup installs them there
                rep.row("FAIL", f"{label} not locked", f"the installer's linux_only rule drops {extra} on Windows, but "
                        f"{se['engine_file']} does not mark them Linux-only")
                return
            elif odd := sorted(f"{n} ({p[1:]})" for n, p in engine_markers(ef).items() if p.startswith("?")):
                rep.row("FAIL", f"{label} not locked", f"{se['engine_file']} has markers the installer does not "
                        f"understand: {odd}; only sys_platform == \"linux\" / \"win32\" are honoured")
                return
            else:
                # honour the file's own markers: a Windows build skips "linux" lines, a Linux build skips "win32" lines
                skip = "linux" if WIN else "win32"
                gone = sorted(n for n, p in engine_markers(ef).items() if p == skip)
                pins = {n: v for n, v in pins.items() if n not in gone}
                rep.row("INFO", label, f"built from {se['engine_file']} (equals the saved list {lst}; files hash-checked; "
                        f"{len(gone)} lines marked {skip} left out on this platform)")
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
        needs = runtime_side_env(src / part["repo"], part)
        if needs is None:
            rep.row("FAIL", f"{part['name']} side env not locked",
                    "the spoke's own script installs from the open index without hashes (a known-good list exists in locks/lists "
                    "but the script cannot take it yet); needs a hashed install in the spoke (Conclave PR)")
        else:
            build_runtime_side_env(rep, part, src / part["repo"], needs, log)


VERIFIED = "adastra_verified.json"  # written into a part's environment only after its own verdict and probe passed
BUILDING = "adastra_building.json"  # written at the START of every build, before the venv; VERIFIED outranks it


def leftover_copies(rep: Report, label: str, folder: Path) -> None:
    """Every kept, unfinished or failed copy beside `folder` is named on EVERY run, not only the run that made it
    (reviewer 3 on #70): they use disk, and nothing here deletes them (that is Jake's call)."""
    for old in sorted(folder.parent.glob(f"{folder.name}.*")):
        kind = old.name[len(folder.name) + 1:].split("-")[0]
        what = {"kept": "previous working copy, kept", "new": "unfinished build, left in place",
                "failed": "failed build, kept beside", "unfinished": "set aside, never verified",
                "legacy": "built before the verified check, kept, not verified"}.get(kind)
        if what and old.is_dir():
            rep.row("INFO", f"{label} copy", f"{old} ({what}; delete it yourself when you no longer want it)")


def runtime_side_env(repo: Path, part: dict) -> tuple[Path, dict] | None:
    """The spoke's own [side_env] table (conclave_runtime_needs.toml, read by the INSTALLER; Conclave #2941 for
    OcrPaddle): where the lens looks for its side environment and the hash-locked list to build it from."""
    for root in part["roots"]:
        for f in sorted((repo / root / "src").glob("*/conclave_runtime_needs.toml")):
            table = tomllib.loads(f.read_text(encoding="utf-8")).get("side_env")
            if table:
                return f, table
    return None


def build_runtime_side_env(rep: Report, part: dict, repo: Path, needs: tuple[Path, dict], log: Path) -> None:
    """Build the side environment exactly as the spoke declares: a fresh CPython venv at its default folder, the
    packaged list installed with --require-hashes --no-deps, then the spoke's warmup. Never reuses a folder this
    installer did not build, and never deletes one: an old folder is named with what to do about it. A rebuild is
    made beside the one in use and switched in only after its warmup passes; the previous one is kept, dated."""
    f, se = needs
    label = f"{part['name']} side env"
    req = f.parent / se["requirements"]
    target = Path(se["default_dir"]).expanduser()
    leftover_copies(rep, label, target)
    for old in sorted(repo / r / ".paddle-env" for r in part["roots"]):
        if old.is_dir():  # built by the spoke's old script from the unhashed list; the lens refuses it since #2941
            rep.row("INFO", f"{label} old folder", f"{old} was built from the old list without hashes; {part['name']} "
                    f"refuses it now and uses {target} instead. Left in place: delete it yourself if you want the space")
    if not req.is_file():
        rep.row("FAIL", label, f"{f.name} names {se['requirements']}, which is not in {f.parent}")
        return
    if target.exists() and not (target / "adastra.json").is_file():
        rep.row("FAIL", label, f"{target} already exists and was not built by this installer, so it is not reused or "
                "removed. Move or delete it yourself, then run again (the lens checks it against the locked list "
                "and refuses a mismatch)")
        return
    base = base_python(se["python"])
    if base is None:
        rep.row("FAIL", label, f"Python {se['python']} not found (phase 1 installs it)")
        return
    # SET-11: the new environment is built BESIDE the one in use, warmed up, and switched in only on PASS; the
    # previous one is kept under a dated name (SEC-8: nothing is deleted), and a failed build never replaces it.
    stamp = time.strftime("%Y%m%d-%H%M%S")
    new = target.with_name(f"{target.name}.new-{stamp}")
    vpy = env_python(new)
    worker = f.parent / se["worker"]
    pins = sum(1 for ln in req.read_text(encoding="utf-8").splitlines() if "==" in ln and not ln.lstrip().startswith("#"))
    in_use = f"; the one already at {target} stays in use" if target.exists() else ""
    if run(base + ["-m", "venv", new], log) or \
            run([vpy, "-m", "pip", "install", "--require-hashes", "--no-deps", "-r", req], log):
        rep.row("FAIL", label, f"could not build it from {se['requirements']} with --require-hashes (see {log}); "
                f"the unfinished build is left at {new}{in_use}")
        return
    (new / "adastra.json").write_text(json.dumps({"built_by": "nestegg install_parts.py", "part": part["name"],
                                                  "from": str(req), "built": stamp}, indent=1) + "\n", encoding="utf-8")
    if run([vpy, "-I", worker, "--op", "warmup", "--allow-network", "--response", new / "warmup_response.json"], log):
        rep.row("FAIL", label, f"built at {new} from {se['requirements']} (hash-checked) but its warmup failed (see {log}); "
                f"not switched in{in_use}")
        return
    kept = target.with_name(f"{target.name}.kept-{stamp}") if target.exists() else None
    try:
        if kept:
            target.rename(kept)  # the last known working copy, kept (never deleted)
        try:
            new.rename(target)
        except OSError:
            if kept:
                kept.rename(target)
            raise
    except OSError as e:  # Windows refuses to rename a folder a running program holds open
        rep.row("FAIL", label, f"could not switch the new build in ({e}); close any program using {target} (a running "
                f"{part['name']} read), then run again. The new build is left at {new}{in_use}")
        return
    tpy = env_python(target)  # a venv moved to its final folder is checked again there before it counts
    if run([tpy, "-I", worker, "--op", "warmup", "--response", target / "warmup_response.json"], log):
        try:
            target.rename(new)
            if kept:
                kept.rename(target)
            back = f"switched back (new build left at {new}){in_use}"
        except OSError as e:
            back = f"switching back failed too ({e}): check {target}, {new} and {kept} by hand"
        rep.row("FAIL", label, f"the new build passed its warmup but not after moving to {target}; {back} (see {log})")
        return
    rep.row("PASS", label, f"built at {target} from {se['requirements']} ({pins} exact pins, --require-hashes --no-deps); "
            "warmup passed before and after the switch (paddle imports, run_check, engine built)")
    if kept:
        rep.row("INFO", f"{label} kept", f"the previous side environment is kept at {kept} (last known working copy; "
                "delete it yourself when you no longer want it)")
    if se.get("gpu_swap"):
        rep.row("INFO", f"{label} GPU", f"CPU build. The GPU swap to {se['gpu_swap']['add']} is not done here and has no "
                "recorded hash yet")


def probe(rep: Report, part: dict, repo: Path, py: Path, local: set[str], log: Path) -> None:
    # every in-repo distribution the part installs is probed, not only its roots: code a root pulls in
    # (e.g. the Bridge inside the launcher) runs in this environment too
    dirs = [repo] if part["roots"][0].startswith(".") else [Path(a.split("[")[0]) for a in closure(repo, part["roots"]) if a != "-e"]
    for dist in part.get("no_caller", []):  # SET-9: shipped because it is production code, though nothing calls it yet
        rep.row("INFO", f"{part['name']} {dist}", "installed, no shipped caller yet")
    skip = part.get("probe_skip", [])
    if isinstance(skip, dict):  # {folder prefix: why}; every skipped folder is printed with its reason
        for k, why in sorted(skip.items()):
            rep.row("INFO", f"{part['name']} not probed", f"{k}: {why}")
    not_reached = {**PROBE_CFG.get("not_reached", {}), **part.get("not_reached", {})}
    for mod, why in sorted(not_reached.items()):
        if any((d / "src" / mod.split(".")[0]).is_dir() or (d / mod.split(".")[0]).is_dir() for d in dirs):
            rep.row("INFO", f"{part['name']} not probed", f"{mod}: {why}")
    pkgs, third = scan_imports(dirs, set(local), tuple(skip), tuple(not_reached))
    ignore = {**PROBE_CFG.get("ignore", {}), **part.get("probe_ignore", {})}
    glob_ign = PROBE_CFG.get("ignore", {})
    for mod, why in sorted(ignore.items()):
        if mod in third or mod not in glob_ign:  # a project-wide entry is printed only where the part imports it
            rep.row("INFO", f"{part['name']} not probed", f"{mod}: {why}")
    third = [t for t in third if t not in ignore]
    hold = part.get("hold", {})
    third = [t for t in third if t not in hold]
    for mod, why in sorted(hold.items()):
        rep.row("HOLD", f"{part['name']} {mod}", why)
    r = subprocess.run([py, "-I", "-c", PROBE, ",".join(pkgs), ",".join(third), ",".join(sorted(not_reached))],
                       capture_output=True, text=True)
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


RUN_BUTTON: dict[str, bool] = {}  # this run's Run-button result per Workbench part (the reader_envs switch needs a PASS)


def harness(rep: Report, part: dict, envs: Path, py: Path, log: Path) -> None:
    """The Workbench's Run launches the harness with its harness.python setting; blank = the Workbench's own Python,
    which does not carry the harness. Point the setting at the harness part's environment and prove it starts."""
    label, hp = f"{part['name']} Run button", env_python(envs / part["harness_from"])
    rep.row("INFO", label, "a blank harness.python on a fresh install would fail at Run, so the installer writes "
                           f"it (the {part['harness_from']} environment) and proves it starts")
    if not hp.exists():
        rep.row("FAIL", label, f"the {part['harness_from']} environment is not built, so harness.python cannot point "
                               "at it; a blank harness.python would fail at Run")
        return
    r = subprocess.run([py, "-I", HERE / "workbench_harness.py", str(hp)], capture_output=True, text=True)
    out = (r.stdout.strip().splitlines() or [r.stderr.strip()[-200:]])[-1]
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(r.stdout + r.stderr)
    if r.returncode == 0 and out.startswith("WORKBENCH-HARNESS: OK"):
        rep.row("PASS", label, out.removeprefix("WORKBENCH-HARNESS: "))
        RUN_BUTTON[part["name"]] = True
    else:
        rep.row("FAIL", label, out.removeprefix("WORKBENCH-HARNESS: "))
        RUN_BUTTON[part["name"]] = False


def hf_hub_cache() -> Path:
    """The cache the readers' from_pretrained reads (huggingface_hub's own default order; no setting is changed)."""
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"])
    home = Path(os.environ.get("HF_HOME") or Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "huggingface")
    return home / "hub"


def _local_target(m: dict) -> Path:
    """The folder a reader loads this model from: its env-variable override, else its own default."""
    ld = m["local_dir"]
    return Path(os.environ.get(ld["env"]) or Path(ld["default"]).expanduser())


def _lock_conflict(m: dict, target: Path) -> str | None:
    """A reader that keeps its own lock file (HtrQwen, GlmOcr): an existing lock that is not exactly this pin
    means a model someone already put there. Nothing is overwritten then; the reason is returned."""
    if not m.get("reader_lock") or not (target / m["reader_lock"]).is_file():
        return None
    try:
        lock = json.loads((target / m["reader_lock"]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return f"its lock file cannot be read ({type(exc).__name__})"
    want = {path: meta["sha256"] for path, meta in m["files"].items()}
    if lock.get("revision") != m["revision"] or lock.get("files") != want:
        return f"a model at revision {str(lock.get('revision'))[:12]} is already there with its own lock"
    return None


def _place_local_dir(sc, m: dict, cfg: dict, root: Path, say) -> bool:
    """A reader that loads from its own folder (its env-variable override, else its default): every file must be
    pinned and match, or nothing is claimed; the reader's own fetch script then downloads and checks as before."""
    target = _local_target(m)
    if _lock_conflict(m, target):  # never overwrite a model that carries a different lock (the model step says so)
        return False
    locs = {"locations": [loc for loc in cfg["locations"] if loc["kind"] != "origin"]}
    for path, meta in sorted(m["files"].items()):
        if not meta.get("sha256") or sc.fetch(meta["sha256"], meta.get("bytes"), f"{m['repo_id']}/{path}", target / path,
                                              locs, root, say=say) is None:
            return False
    return True


def saved_model_wheel(m: dict, envs: Path, log: Path) -> Path | None:
    """A model wheel the installer pip-installs (parts.json "models": spaCy's en_core_web_sm), taken from the saved
    copies first by its pinned sha256 (every saved copy is re-hashed before use). None means not in any saved copy: the original URL is used,
    still pinned by #sha256= (and Obsidian's own content pin is checked after either way)."""
    sc = _saved_copies()
    cfg = sc.load_config()
    locs = [loc for loc in cfg["locations"] if loc["kind"] != "origin"]
    root = INSTALL_ROOT.get("root") or envs.parent
    if not sc.usable(locs, root):
        return None
    fn = m["wheel"].rsplit("/", 1)[-1]
    dest = envs / "_wheelhouse" / fn
    with log.open("a", encoding="utf-8") as fh:
        src = sc.fetch(m["wheel_sha256"], m.get("wheel_bytes"), fn, dest, {"locations": locs}, root,
                       say=lambda msg: _saved_say(msg, fh))
        fh.write(f"saved copy: {fn} <- {src or 'not in any saved copy (original URL, hash-pinned)'}\n")
    return dest if src else None


def saved_models(rep: Report, part: dict, envs: Path) -> None:
    """Decision 30 A: put each pinned Hugging Face snapshot of this reader in place from the saved copies first.
    A snapshot is placed only when every one of its files matches a pin; otherwise the reader's own step below
    downloads it as before. Nothing here marks a model PASS: the model steps below still decide."""
    man = HERE / "models_pinned.json"
    if not man.is_file():
        return
    reader = json.loads(man.read_text(encoding="utf-8")).get("readers", {}).get(part["name"])
    if not reader:
        return
    sc = _saved_copies()
    cfg = sc.load_config()
    root = INSTALL_ROOT.get("root") or envs.parent
    if not sc.usable([loc for loc in cfg["locations"] if loc["kind"] != "origin"], root):
        return
    every = [m for m in reader.get("models", {}).values() if m.get("source") == "huggingface" and m.get("files")]
    hf = [m for m in every if not m.get("local_dir")]
    def say(msg: str) -> None:  # a changed saved copy is a WARN row; plain "not in this copy" stays quiet
        if msg.startswith("WARN"):
            rep.row("WARN", f"{part['name']} saved copy changed", msg[6:].strip())

    placed = [m["repo_id"] for m in hf
              if sc.place_hf_snapshot(m["repo_id"], m["revision"], m["files"], hf_hub_cache(), cfg, root, say=say,
                                      ref=hf_ref(m))]
    for m in every:  # readers that load from their own folder (im2latex): each pinned file straight into that folder
        if m.get("local_dir"):
            placed += [m["repo_id"]] if _place_local_dir(sc, m, cfg, root, say) else []
    rep.row("INFO", f"{part['name']} saved models", f"{len(placed)} of {len(every)} Hugging Face models placed from a saved copy"
            + (f": {', '.join(placed)}" if placed else " (the rest download from the original site, hash-pinned where pinned)"))


def hf_ref(m: dict) -> str:
    """The name the reader's code asks the cache for: a tag ("tag v2.3.0") by its name, else main."""
    ref = str(m.get("revision_ref") or "")
    return ref.split(None, 1)[1] if ref.startswith("tag ") else "main"


def hf_url(repo_id: str, revision: str, path: str) -> str:
    return f"https://huggingface.co/{repo_id}/resolve/{revision}/{path}"


MINERU_MODELS_ENV = "CONCLAVE_MINERU_MODELS_DIR"
MINERU_CONFIG_ENV = "MINERU_TOOLS_CONFIG_JSON"


def _mineru_pipeline_dir() -> tuple[str, Path | None, Path]:
    """Where the MinerU reader looks, in its own order (bundle_inspector._read_mineru_models_pipeline_dir):
    CONCLAVE_MINERU_MODELS_DIR, then MINERU_TOOLS_CONFIG_JSON, then ~/mineru.json. Returns (source, dir, config)."""
    cfg = Path(os.environ.get(MINERU_CONFIG_ENV) or Path.home() / "mineru.json")
    if os.environ.get(MINERU_MODELS_ENV):
        return MINERU_MODELS_ENV, Path(os.environ[MINERU_MODELS_ENV]), cfg
    if not cfg.is_file():
        return str(cfg), None, cfg
    try:
        pipeline = (json.loads(cfg.read_text(encoding="utf-8")).get("models-dir") or {}).get("pipeline")
    except (OSError, ValueError, AttributeError):
        pipeline = None
    return str(cfg), Path(pipeline) if pipeline else None, cfg


def _same_dir(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _mineru_config(snapshot: Path, envs: Path, log: Path) -> tuple[str, str]:
    """The MinerU reader finds its models only through its config, so a placed snapshot is not enough (reviewer 3,
    #86). A config naming another folder is never changed (HOLD). With no config, MinerU's own models_download
    writes it, run with the Hugging Face cache offline so it can only resolve the pinned snapshot just placed;
    the result is read back and must name that snapshot. Returns (PASS | HOLD | FAIL, reason)."""
    src, pdir, cfg = _mineru_pipeline_dir()
    if pdir is not None:
        if _same_dir(pdir, snapshot):
            return "PASS", f"the reader's models-dir.pipeline ({src}) names the pinned snapshot"
        return "HOLD", (f"the reader's models-dir.pipeline ({src}) names {pdir}, not the pinned snapshot {snapshot}; "
                        "left untouched (point it at the pinned snapshot, or move that config aside, to use the pin)")
    if cfg.is_file():
        return "HOLD", f"{cfg} exists without a models-dir.pipeline entry; left untouched"
    cli = env_python(envs / "_mineru_cli")
    e = dict(os.environ, MINERU_MODEL_SOURCE="huggingface", HF_HUB_OFFLINE="1")
    rc = run([cli, "-m", "mineru.cli.models_download", "-s", "huggingface", "-m", "pipeline"], log, env=e)
    src, pdir, cfg = _mineru_pipeline_dir()
    if rc == 0 and pdir is not None and _same_dir(pdir, snapshot):
        return "PASS", f"MinerU wrote {cfg} (offline) and its models-dir.pipeline names the pinned snapshot"
    return "FAIL", (f"the reader's config {cfg} was not written with the pinned snapshot "
                    f"(models_download exit {rc}; models-dir.pipeline = {pdir}); the MinerU reader would not find it (see {log})")


PLACEABLE = ("huggingface", "github_release", "datalab_cdn")


def _settings_dir(envs: Path, sd: dict, log: Path) -> Path | None:
    """The model folder as the reader's own library computes it, read in that library's environment."""
    try:
        r = subprocess.run([str(env_python(envs / sd["env"])), "-I", "-c", sd["code"]], capture_output=True, text=True,
                           check=False)
    except OSError as exc:  # the environment is not built: a named FAIL upstream
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"could not start {sd['env']}: {exc}\n")
        return None
    with log.open("a", encoding="utf-8") as fh:
        fh.write(r.stdout + r.stderr)
    out = r.stdout.strip().splitlines()
    return Path(out[-1]) if r.returncode == 0 and out else None


def _package_dir(py: Path, pd: dict, log: Path) -> Path | None:
    """A folder inside an installed package of the reader's environment, found without importing the package."""
    code = "import importlib.util,sys;s=importlib.util.find_spec(sys.argv[1]);print(s.submodule_search_locations[0])"
    r = subprocess.run([str(py), "-I", "-c", code, pd["package"]], capture_output=True, text=True, check=False)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(r.stdout + r.stderr)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return Path(r.stdout.strip().splitlines()[-1]) / pd["sub"]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _bundled_check(rep: Report, label: str, m: dict, py: Path, log: Path) -> None:
    """Model files shipped inside a locked wheel (rapidocr's own models): nothing is fetched or written; each file
    the reader will load is hash-checked where the installed package keeps it."""
    pd = m["package_dir"]
    what = f"{pd['package']} built-in models"
    target = _package_dir(py, pd, log)
    if target is None:
        rep.row("FAIL", label, f"{what}: package {pd['package']} not found in the environment (see {log})")
        return
    bad = []
    for name, meta in sorted((m.get("files") or {}).items()):
        f = target / name
        if not f.is_file() or f.stat().st_size != meta.get("bytes") or _sha256(f) != meta.get("sha256"):
            bad.append(name)
    if bad or not m.get("files"):
        rep.row("FAIL", label, f"{what}: {len(bad)} of {len(m.get('files') or {})} files missing or not the pinned bytes at "
                f"{target} (first: {bad[0] if bad else 'none pinned'})")
        return
    rep.row("PASS", label, f"{what}: {len(m['files'])} files hash-checked in place at {target} (shipped in the locked wheel)")


def pinned_models(rep: Report, part: dict, spoke: Path, envs: Path, py: Path, log: Path) -> None:
    """HR 13/14: every Hugging Face model of this reader in models_pinned.json, at its pinned revision, each file
    hash-checked. Saved copies first, then the original site at the pinned commit; a file whose bytes do not
    match is never used. A reader with its own lock file gets that lock written in its own format, then its own
    fetch script re-checks every file (offline: it only verifies a matching lock)."""
    label = f"{part['name']} model"
    reader = json.loads((HERE / "models_pinned.json").read_text(encoding="utf-8")).get("readers", {}).get(part["name"])
    every = [m for m in (reader or {}).get("models", {}).values() if m.get("source") != "reference"]
    for m in every:  # a model this step cannot fetch yet (modelscope, a CDN not measured) is a FAIL, never skipped
        if m.get("unused_reason"):  # pinned and saved, but traced as not loaded by the installed reader
            rep.row("INFO", label, f"{', '.join(sorted(m.get('files') or {})[:2])}...: kept pinned and saved, not placed: {m['unused_reason']}")
            continue
        if m.get("source") == "package_bundled":  # shipped inside a locked wheel: checked in place below
            continue
        if m.get("source") not in PLACEABLE or m.get("not_placed_reason"):
            rep.row("FAIL", label, f"{', '.join(sorted(m.get('files') or {})[:2]) or m.get('source')}...: from "
                    f"{m.get('source')}, {m.get('not_placed_reason') or m.get('unmeasured_reason') or 'not measured yet'}; not installed")
    hf = [m for m in every if m.get("source") in PLACEABLE and not m.get("not_placed_reason") and not m.get("unused_reason")]
    if not every:
        rep.row("FAIL", label, f"no model pinned for {part['name']} in models_pinned.json")
        return
    for m in every:
        if m.get("source") == "package_bundled" and not m.get("unused_reason"):
            _bundled_check(rep, label, m, py, log)
    sc = _saved_copies()
    cfg = sc.load_config()  # every location, the original site last
    root = INSTALL_ROOT.get("root") or envs.parent
    for m in hf:
        what = f"{m['repo_id']}@{m['revision'][:7]}" if m.get("repo_id") else f"{m.get('source')} ({', '.join(sorted(m.get('files') or {})[:2])}{', ...' if len(m.get('files') or {}) > 2 else ''})"
        files = m.get("files") or {}
        unpinned = [p for p, meta in files.items() if not meta.get("sha256")]
        if not files or unpinned:
            rep.row("FAIL", label, f"{what}: {len(unpinned) or 'no'} file(s) without a pinned sha256; not installed")
            continue
        if m.get("local_dir"):
            target = _local_target(m)
            clash = _lock_conflict(m, target)
            if clash:
                rep.row("HOLD", label, f"{what}: {clash} at {target}; left untouched (move it aside to install the pinned one)")
                continue
        elif m.get("settings_dir"):  # a folder the reader's own library names (surya's MODEL_CACHE_DIR)
            target = _settings_dir(envs, m["settings_dir"], log)
            if target is None:
                rep.row("FAIL", label, f"{what}: could not read the model folder from {m['settings_dir']['env']} (see {log})")
                continue
        elif m.get("package_dir"):  # inside the reader's own environment (pix2tex reads model/checkpoints there)
            target = _package_dir(py, m["package_dir"], log)
            if target is None:
                rep.row("FAIL", label, f"{what}: package {m['package_dir']['package']} not found in the environment (see {log})")
                continue
        else:
            repo_dir = hf_hub_cache() / ("models--" + m["repo_id"].replace("/", "--"))
            target = repo_dir / "snapshots" / m["revision"]
        came: dict[str, int] = {}
        bad = []
        with log.open("a", encoding="utf-8") as fh:
            for path, meta in sorted(files.items()):
                src = sc.fetch(meta["sha256"], meta.get("bytes"), f"{m.get('repo_id', part['name'])}/{path}", target / path,
                               cfg, root, origin_url=meta.get("url") or hf_url(m["repo_id"], m["revision"], path),
                               say=lambda msg: _saved_say(msg, fh))
                if src is None:
                    bad.append(path)
                else:
                    came[src] = came.get(src, 0) + 1
        if bad:
            rep.row("FAIL", label, f"{what}: {len(bad)} of {len(files)} files not found with the pinned sha256 "
                    f"(first: {bad[0]}; see {log})")
            continue
        if not (m.get("local_dir") or m.get("package_dir") or m.get("settings_dir")):  # the standard cache: the ref the reader asks for
            (repo_dir / "refs").mkdir(parents=True, exist_ok=True)  # (main, or a tag such as v2.3.0) names the pin
            (repo_dir / "refs" / hf_ref(m)).write_text(m["revision"], encoding="utf-8")
        where = ", ".join(f"{n} from {k}" for k, n in sorted(came.items()))
        if any("on Jake's PC" in str(meta.get("sha256_source", "")) and "file listing" not in str(meta.get("sha256_source", ""))
               for meta in files.values()):  # a site that publishes its own hashes (ModelScope's listing) is not trust-on-first-use
            where += "; hashes measured on the PC, the site publishes none (trust on first use)"
        if m.get("reader_lock"):
            lock = target / m["reader_lock"]
            if not lock.is_file():
                lock.write_text(json.dumps({"repo": m["repo_id"], "revision": m["revision"],
                                            "files": {p: meta["sha256"] for p, meta in sorted(files.items())}}, indent=2),
                                encoding="utf-8")
            script = spoke / m.get("reader_check", "scripts/fetch_model.py")
            rc = run([py, script], log, cwd=spoke)
            last = (log.read_text(encoding="utf-8", errors="replace").strip().splitlines() or [""])[-1].strip()
            if rc != 0 or last != "PASS":
                rep.row("FAIL", label, f"{what}: files match the pin, but the reader's own check did not pass (see {log})")
                continue
            rep.row("PASS", label, f"{what}: {len(files)} files hash-checked ({where}); the reader's own lock check passed")
        else:
            if m.get("mineru_config"):
                cfg_state, cfg_why = _mineru_config(target, envs, log)
                if cfg_state != "PASS":
                    rep.row(cfg_state, label, f"{what}: files match the pin, but {cfg_why}")
                    continue
                where += f"; {cfg_why}"
            note = "" if m.get("local_dir") or m.get("package_dir") or m.get("settings_dir") or m.get("pinned_in_code") else \
                "; the reader's code does not name this revision yet (Conclave follow-up), so this pin holds offline"
            rep.row("PASS", label, f"{what}: {len(files)} files hash-checked ({where}) at {target}{note}")


def models(rep: Report, part: dict, src: Path, repo: Path, envs: Path, py: Path, log: Path) -> None:
    saved_models(rep, part, envs)
    mdir = envs / "_models"
    for m in part.get("models", []):
        label = f"{part['name']} model"
        step = m["step"]
        spoke = repo / part["roots"][0].split("[")[0]
        if step == "unpinned":
            rep.row("FAIL", label, f"{m['what']}: no pinned revision and hash in the project yet, so it is not installed")
        elif step == "pinned_models":
            pinned_models(rep, part, spoke, envs, py, log)
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
            try:  # Decision 30 A / HR 14: the saved copy first, so no internet is needed
                local = saved_model_wheel(m, envs, log)
            except Exception as exc:  # never silent: a FAIL row. Then the pinned URL on purpose: pip still checks its
                local = None          # sha256 and Obsidian's content pin decides below, so nothing unchecked goes in
                rep.row("FAIL", f"{m['name']} saved copy", f"reading the saved copies failed ({type(exc).__name__}: {exc}); "
                        "trying the original URL, hash-pinned")
            rc = run([py, "-m", "pip", "install", "--no-deps", "--no-index", local], log) if local else \
                run([py, "-m", "pip", "install", "--no-deps", f"{m['wheel']}#sha256={m['wheel_sha256']}"], log)
            chk = ("import sys, en_core_web_sm; from pathlib import Path; from obsidian.detect import PINNED_MODELS, model_sha256;"
                   "d = Path(en_core_web_sm.__file__).parent / sys.argv[1];"
                   "sys.exit(0 if model_sha256(d) == PINNED_MODELS[sys.argv[1]] else 3)")
            ok = rc == 0 and run([py, "-I", "-c", chk, m["name"]], log) == 0
            rep.row("PASS" if ok else "FAIL", label, f"{m['name']} matches Obsidian's own pin" if ok else f"{m['name']} missing or does not match the pin (see {log})")
        else:
            rep.row("FAIL", label, f"unknown model step {step!r}")


READER_ENVS_SCHEMA = 1
_MEASURE = (
    "import json,sys,importlib.metadata as m\n"
    "eps=sorted({e.name for e in m.entry_points(group='conclave.lenses')})\n"
    "try:\n    cv=m.version('conclave-contracts')\nexcept m.PackageNotFoundError:\n    cv=None\n"
    "print(json.dumps({'python_version':sys.version.split()[0],'executable':sys.executable,'lens_ids':eps,'contracts_version':cv}))\n"
)


def dir_bytes(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += (Path(root) / f).lstat().st_size
            except OSError:
                pass
    return total


def reader_entry(rep: Report, part: dict, envs: Path, outcome: str) -> dict:
    """Measure, with the reader's own Python in isolated mode, what LensRunner's launcher needs to start it there
    (design: installer/DESIGN_reader_env_launcher_2026-11-22.md section 2). Nothing is copied from parts.json."""
    name = part["name"]
    env = envs / name
    py = env_python(env)
    lst = f"{name}_py{part['python']}.txt"
    lp = LOCKS / "lists" / lst
    entry = {"part": name, "env": str(env), "python": str(py), "list": lst,
             "list_sha256": hashlib.sha256(lp.read_bytes()).hexdigest() if lp.is_file() else None,
             "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "status": outcome,
             "host_selftest": "NOT_RUN: not yet hand-shaken"}
    if not py.exists():
        rep.row("FAIL", f"{name} reader record", f"its Python is missing: {py}")
        entry["status"] = "FAIL"
        return entry
    got = subprocess.run([str(py), "-I", "-c", _MEASURE], capture_output=True, text=True)
    try:
        facts = json.loads(got.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        rep.row("FAIL", f"{name} reader record", f"its Python did not answer (exit {got.returncode}): {got.stderr.strip()[-300:]}")
        entry["status"] = "FAIL"
        return entry
    entry.update({k: facts[k] for k in ("python_version", "lens_ids", "contracts_version")})
    entry["size_bytes"] = dir_bytes(env)
    probs = []
    if not facts["lens_ids"]:
        probs.append("no reader is registered under conclave.lenses in its own environment")
    if not facts["contracts_version"]:
        probs.append("conclave-contracts is not installed in its own environment")
    if not facts["python_version"].startswith(part["python"] + "."):
        probs.append(f"runs Python {facts['python_version']}, the build declares {part['python']}")
    if os.path.normcase(os.path.realpath(facts["executable"])) != os.path.normcase(os.path.realpath(py)):
        probs.append(f"answered from {facts['executable']}, not {py}")
    for pr in probs:
        rep.row("FAIL", f"{name} reader record", pr)
    if probs:
        entry["status"] = "FAIL"
    else:
        rep.row("INFO", f"{name} reader record", f"{', '.join(facts['lens_ids'])} on Python {facts['python_version']}, "
                f"{entry['size_bytes'] / 1e6:,.0f} MB on disk; recorded as {entry['status']}")
    return entry


_FIND_HOST = "import os,conclave_lensrunner as m;print(os.path.join(os.path.dirname(m.__file__),'reader_host.py'))"


def host_selftest(rep: Report, entries: list[dict], envs: Path, run_env: str = "harness_adapters") -> None:
    """Hand-shake each reader environment with LensRunner's reader host, run by that reader's own Python in isolated
    mode (Conclave #2913, LensRunner 0.1.0a2; command and answer: reader-envs/HANDOFF_reader_host_2026-11-22.md).
    The host file comes from the Run environment, the one the Workbench starts. A host that answers anything but ok
    turns the entry to FAIL. A LensRunner without a reader host yet leaves NOT_RUN, said as such, never a pass."""
    rpy = env_python(envs / run_env)
    got = subprocess.run([str(rpy), "-I", "-c", _FIND_HOST], capture_output=True, text=True) if rpy.exists() else None
    host = Path(got.stdout.strip()) if got is not None and got.returncode == 0 else None
    if host is None or not host.is_file():
        why = f"the Run environment ({run_env}) is not installed" if got is None else \
            "the Run environment's LensRunner has no reader host (needs LensRunner 0.1.0a2, Conclave #2913)"
        for e in entries:
            e["host_selftest"] = f"NOT_RUN: {why}"
        rep.row("INFO", "reader host self-test", f"not run: {why}; LensRunner still hand-shakes every reader live at each run")
        return
    for e in entries:
        if e["status"] == "FAIL" or not e.get("lens_ids"):
            continue
        cmd = [e["python"], "-I", str(host), "--self-test"] + [x for i in e["lens_ids"] for x in ("--lens-id", i)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        try:
            ans = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            ans = None
        if not isinstance(ans, dict):
            e["host_selftest"] = {"ok": False, "exit": r.returncode, "stderr_tail": r.stderr.strip()[-300:]}
            rep.row("FAIL", f"{e['part']} reader host", f"no answer (exit {r.returncode}): {r.stderr.strip()[-300:]}")
            e["status"] = "FAIL"
            continue
        e["host_selftest"] = ans
        missing = sorted(set(e["lens_ids"]) - set(ans.get("lens_ids") or []))
        if r.returncode == 0 and ans.get("ok") is True and not missing:
            rep.row("PASS", f"{e['part']} reader host", f"{', '.join(e['lens_ids'])} import and pass the pre-run check in their own environment")
        else:
            bits = [f"{k}: {ans[k]}" for k in ("import_failures", "prerun_problems", "prerun_error") if ans.get(k)]
            if missing:
                bits.append(f"did not answer for {', '.join(missing)}")
            rep.row("FAIL", f"{e['part']} reader host", "; ".join(bits) or f"answered not ok (exit {r.returncode})")
            e["status"] = "FAIL"


def write_reader_envs(envs: Path, entries: list[dict]) -> Path:
    """envs/reader_envs.json: one entry per reader environment. A partial run (--only) replaces only the parts it
    rebuilt. Written whole to a temp file, then renamed, so a reader never sees half a file."""
    out = envs / "reader_envs.json"
    keep: dict[str, dict] = {}
    if out.is_file():
        try:
            keep = {e["part"]: e for e in json.loads(out.read_text(encoding="utf-8")).get("readers", [])}
        except (ValueError, KeyError, AttributeError):
            keep = {}  # unreadable: rebuilt from this run only; the parts not rebuilt are absent, so they read as not installed
    for e in entries:
        keep[e["part"]] = e
    lsum = LOCKS / "SOURCE_SHA256.txt"
    doc = {"schema": READER_ENVS_SCHEMA, "provisional": False,  # LensRunner 0.1.0a2 (Conclave #2913) refuses a provisional record
           "locks_sha256": hashlib.sha256(lsum.read_bytes()).hexdigest() if lsum.is_file() else None,
           "readers": [keep[k] for k in sorted(keep)]}
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, out)
    return out


def turn_on_reader_envs(rep: Report, record: Path, envs: Path, parts: list[dict], dry: bool) -> None:
    """Go-live: point the Workbench's harness.reader_envs setting at the record, so each reader runs from its own
    environment (otherwise the installed app runs only what the harness environment carries: the Fast preset).
    Gate (coordinator ruling 11/23, logged for Jake's audit): at least one reader PASS in the record and this run's
    Workbench Run-button row PASS; the preset probe then proves the setting before it stays on, and LensRunner
    itself refuses any reader that is not PASS in the record. Every reader is listed by name as usable or not, so a
    partial install never reads as a full one. Undo: clear "Reader environments record" in Settings > Harness."""
    label = "workbench reader environments"
    wb = next((p for p in parts if p.get("harness_from")), None) or next(
        (p for p in json.loads((HERE / "parts.json").read_text(encoding="utf-8"))["parts"] if p.get("harness_from")), None)
    if dry or wb is None:
        return
    hpy = env_python(envs / wb["harness_from"])
    try:
        entries = json.loads(record.read_text(encoding="utf-8"))["readers"]
        passed = sorted(e["part"] for e in entries if e.get("status") == "PASS")
        notok = sorted(f"{e['part']} ({e.get('status', 'no status')})" for e in entries if e.get("status") != "PASS")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        rep.row("FAIL", label, f"harness.reader_envs left off: the record {record} could not be read back ({exc})")
        return
    rep.row("INFO", "readers usable", f"{len(passed)}: {', '.join(passed) or 'none'}")
    if notok:
        rep.row("WARN", "readers NOT usable", f"{len(notok)} (LensRunner refuses each; see its rows above): {', '.join(notok)}")
    rb = RUN_BUTTON.get(wb["name"])
    why = ("no reader environment passed" if not passed else
           f"the {wb['name']} Run button was not checked in this run" if rb is None else
           f"the {wb['name']} Run button row failed" if not rb else
           f"the {wb['harness_from']} environment is not built" if not hpy.exists() else "")
    if why:
        rep.row("WARN", label, f"harness.reader_envs LEFT OFF ({why}); the installed app runs only what the "
                               f"{wb['harness_from']} environment carries")
        return
    wpy = env_python(envs / wb["name"])
    r = subprocess.run([wpy, "-I", HERE / "workbench_harness.py", "--reader-envs", str(record), str(hpy)],
                       capture_output=True, text=True)
    out = (r.stdout.strip().splitlines() or [r.stderr.strip()[-200:]])[-1]
    if r.returncode == 0 and out.startswith("WORKBENCH-READER-ENVS: OK"):
        part_note = f" ({len(notok)} not usable, listed above)" if notok else ""
        rep.row("PASS", label, f"harness.reader_envs on: {len(passed)} readers usable{part_note}; "
                + out.removeprefix("WORKBENCH-READER-ENVS: OK "))
    else:
        rep.row("FAIL", label, out.removeprefix("WORKBENCH-READER-ENVS: "))


def learning_folders(rep: Report, cfg: dict, root: Path, dry: bool) -> None:
    """<root>/learning/<aim>/ with inbox, approved, held-aside, feedback, an empty manifest.jsonl and a README.md.
    Create-only: anything already there is left exactly as it is (SEC-8), so upgrade and repair are safe."""
    lf = cfg.get("learning")
    if not lf:
        rep.row("FAIL", "learning folders", "parts.json declares no learning folders (SET-9)")
        return
    base = root / "learning"
    if dry:
        rep.row("TODO", "learning folders", f"{base}: {', '.join(lf['aims'])}")
        return
    made = 0
    try:
        for aim in lf["aims"]:
            d = base / aim
            for sub in lf["subdirs"]:
                if not (d / sub).is_dir():
                    (d / sub).mkdir(parents=True)
                    made += 1
            man = d / "manifest.jsonl"
            if not man.exists():
                man.write_text("", encoding="utf-8")
                made += 1
            readme = d / "README.md"
            if not readme.exists():
                readme.write_text(
                    f"# Learning folder: {aim}\n\nCreated by the installer. Layout and rules: learning-folders design "
                    "section 2.\n\n- inbox/: waiting for approval; the connector never reads here\n"
                    "- approved/: the only place the connector reads\n- held-aside/: items taken out, never deleted, "
                    "with the reason\n- feedback/: reports the connector wrote, one per run\n"
                    "- manifest.jsonl: one line per item (sha256, class, source, added_at, added_by, gate result)\n\n"
                    "Class P (derived from a real report) is never put in a package backup.\n", encoding="utf-8")
                made += 1
    except OSError as e:
        rep.row("FAIL", "learning folders", f"could not create under {base}: {e}")
        return
    rep.row("PASS", "learning folders", f"{len(lf['aims'])} aims under {base}; {made} new item(s), existing contents untouched")


LOCUTUS_KEY_ENV = "CONCLAVE_LOCUTUS_KEY_FILE"  # read by conclave_locutus_rulings.wiring (Conclave)
LAUNCHER_MARK = "REM adastra-launcher v1 (written by the Nestegg installer; safe to delete, the next install writes it again)"
REVIEW_SURFACES = (("Open Workbench.cmd", "workbench", "conclave-workbench"),
                   ("Open Review Console.cmd", "reviewconsole", "conclave-review-gui"))


def locutus_key_path() -> Path:
    """The capture key's home: the user profile itself (never redirected to OneDrive, unlike Documents or Desktop),
    outside the install folder (so no saved copy, backup bundle or repo under it ever holds it)."""
    return Path.home() / ".adastra_keys" / "locutus" / "partition_key_v1"


def _key_place_problem(key: Path, install_root: Path) -> str | None:
    """Why this folder must not hold the key, or None. Checked before the folder is made and again after.
    The path is always resolved (non-strict resolve follows every junction or symlink in the part that exists),
    so a link above a folder that does not exist yet (the first install) cannot point the key into OneDrive,
    the install folder or a repo. Both the raw and the resolved path are checked."""
    folders = [key.parent.resolve(), key.parent.absolute()]
    for folder in folders:
        for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
            od = os.environ.get(var, "").strip()
            if not od:
                continue
            for odp in {Path(od).absolute(), Path(od).resolve()}:
                if folder == odp or odp in folder.parents:
                    return f"{folder} is inside OneDrive ({var})"
        if "onedrive" in str(folder).lower():
            return f"{folder} looks like a OneDrive folder"
    folder = folders[0]
    root = install_root.resolve()
    if folder == root or root in folder.parents:
        return f"{folder} is inside the install folder {root}"
    for d in (folder, *folder.parents):
        if (d / ".git").exists():
            return f"{folder} is inside a git repository ({d})"
    return None


def make_locutus_key(key: Path) -> bool:
    """Write a new random key (64 hex characters from the OS random source) only if no file is there. The create is
    exclusive (O_EXCL), so an existing key can never be overwritten, even by a race. The key is never printed or
    logged. Returns False when a key already exists. The 0o600 mode applies on Linux/macOS only; Windows ignores it,
    so there the file carries the ACL of the user profile folder (the user, SYSTEM and Administrators by default)."""
    import secrets
    key.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(secrets.token_hex(32))
    return True


def _write_launcher(path: Path, key: Path, exe: Path) -> str | None:
    """A double-click launcher that starts one review surface with capture switched on (the variable is set for
    that window only; no Windows setting changes). A file there that this installer did not write is never
    replaced. Returns why it was not written, or None."""
    if path.exists() and LAUNCHER_MARK not in path.read_text(encoding="utf-8", errors="replace"):
        return f"{path.name} already exists and was not written by this installer; left untouched"
    path.write_text(f'@echo off\r\n{LAUNCHER_MARK}\r\nset "{LOCUTUS_KEY_ENV}={key}"\r\nstart "" "{exe}"\r\n',
                    encoding="utf-8", newline="")
    return None


def locutus_capture(rep: Report, envs: Path, install_root: Path, dry: bool) -> None:
    """Decision 57 A (Jake, 11:37 AM CT 11/23): make the Locutus capture key on this PC during the installer run he
    double-clicks, and set the review launchers to use it, so review screens read "Locutus capture: ON".
    The key: random, in the user profile outside OneDrive, the install folder and every repo; never shown, printed,
    logged or copied; an existing key is never overwritten (loud WARN, that key is kept). Any failed step leaves
    capture off and says why. Undo: delete the two launchers (capture is then off); the key is never deleted here."""
    label = "Locutus capture"
    key = locutus_key_path()
    off = "capture stays OFF; review still works and its screens say so"
    if dry:
        rep.row("INFO", label, f"would make the capture key at {key} (only if none is there) and write "
                f"{', '.join(n for n, _, _ in REVIEW_SURFACES)} in {install_root}")
        return
    problem = _key_place_problem(key, install_root)
    if problem:
        rep.row("FAIL", label, f"key not made: {problem}; {off}")
        return
    try:
        key.parent.mkdir(parents=True, exist_ok=True)
        problem = _key_place_problem(key, install_root)  # again, now that the folder exists and resolves fully
        if problem:
            rep.row("FAIL", label, f"key not made: {problem}; {off}")
            return
        made = make_locutus_key(key)
        if not key.is_file() or not key.read_bytes().strip():
            rep.row("FAIL", label, f"the key file at {key} is empty or not a file; {off}")
            return
    except OSError as exc:
        rep.row("FAIL", label, f"key not made ({type(exc).__name__}: {exc.strerror or exc}); {off}")
        return
    if made:
        rep.row("PASS", "Locutus capture key", f"made at {key} (random; never shown, logged or copied)")
    else:
        rep.row("WARN", "Locutus capture key", f"a key already exists at {key}; NOT overwritten, capture uses that key")
    wrote = []
    for fname, part, script in REVIEW_SURFACES:
        py = env_python(envs / part)
        exe = env_bin(envs / part, script)
        if not exe.exists():
            rep.row("WARN", f"{label} {part}", f"{part} environment not built, so {fname} was not written; {off} there")
            continue
        chk = ("import os,sys;from conclave_locutus_rulings.wiring import capture_state;from pathlib import Path;"
               "s=capture_state();ok=s=='Locutus capture: ON' and bool(Path(os.environ[sys.argv[1]]).read_bytes().strip());"
               "print(s);sys.exit(0 if ok else 3)")
        r = subprocess.run([str(py), "-I", "-c", chk, LOCUTUS_KEY_ENV], capture_output=True, text=True, check=False,
                           env=dict(os.environ, **{LOCUTUS_KEY_ENV: str(key)}))  # only the path; the key is never passed
        if r.returncode != 0:
            why = (r.stdout.strip().splitlines() or r.stderr.strip().splitlines() or ["no output"])[-1][-200:]
            rep.row("FAIL", f"{label} {part}", f"{part} did not read capture ON with the key ({why}); {fname} not written; {off} there")
            continue
        try:
            skip = _write_launcher(install_root / fname, key, exe)
        except OSError as exc:
            skip = f"could not write {fname} ({type(exc).__name__})"
        if skip:
            rep.row("FAIL", f"{label} {part}", f"{skip}; {off} there")
            continue
        wrote.append(fname)
    if wrote:
        rep.row("PASS", label, f"ON in {', '.join(wrote)} ({install_root}): each sets the key for its own window and "
                               "the screens read 'Locutus capture: ON'. Starting the app any other way leaves capture OFF, "
                               "and its screens say so")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, required=True)
    ap.add_argument("--envs", type=Path, required=True)
    ap.add_argument("--root", type=Path, default=None, help="install root for learning folders (default: the folder above --envs)")
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
    INSTALL_ROOT["root"] = a.root or a.envs.parent
    PROBE_CFG.update(cfg.get("probe", {}))
    readers = []
    for p in parts:
        f0, h0 = rep.fails, rep.holds
        build_part(rep, p, cfg, a.src, a.envs, a.dry_run, gpu, set(), sums)
        if is_reader(p) and not a.dry_run:  # a failed build is recorded as FAIL, never left on its last good entry
            outcome = "FAIL" if rep.fails > f0 else "HOLD" if rep.holds > h0 else "PASS"
            readers.append(reader_entry(rep, p, a.envs, outcome))
    if not only:
        learning_folders(rep, cfg, a.root or a.envs.parent, a.dry_run)
    if readers:
        host_selftest(rep, readers, a.envs)
        record = write_reader_envs(a.envs, readers)
        rep.row("INFO", "reader record", f"{record}: {len(readers)} reader environments")
        turn_on_reader_envs(rep, record, a.envs, parts, a.dry_run)
    if not only or only & {"workbench", "reviewconsole"}:
        locutus_capture(rep, a.envs, INSTALL_ROOT["root"], a.dry_run)
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
