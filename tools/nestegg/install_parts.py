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
    if part.get("test_env"):
        shutil.rmtree(envs / f"{name}-test", ignore_errors=True)  # used only for the proof; never left installed
    if rc == 0:
        rep.row("PASS", name, f"{done}; {status}; its own tests pass under {where}")
    else:
        rep.row("FAIL", name, f"{done}; its own tests fail under {where} (exit {rc}, see {log})")


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
    shutil.rmtree(env, ignore_errors=True)
    base = base_python(part["python"])
    if base is None or run(base + ["-m", "venv", env], log):
        rep.row("HOLD", name, f"{done}; {status}; could not create its test environment (see {log})")
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
            src = sc.fetch(h, None, fn, wheelhouse / fn, {"locations": locs}, root, say=lambda m: fh.write(m + "\n"))
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
    try:  # how an installed program finds the install root (learning folders etc.): <env>/adastra.json, read-only for it
        env.mkdir(parents=True, exist_ok=True)
        (env / "adastra.json").write_text(json.dumps({"install_root": str(INSTALL_ROOT.get("root") or envs.parent),
                                                      "envs": str(envs), "part": name}, indent=1) + "\n", encoding="utf-8")
    except OSError as e:
        rep.row("FAIL", f"{name} root marker", f"could not write {env / 'adastra.json'}: {e}")
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
    if part.get("harness_from"):
        harness(rep, part, envs, py, log)
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
        rep.row("FAIL", f"{part['name']} side env not locked",
                "the spoke's own script installs from the open index without hashes (a known-good list exists in locks/lists "
                "but the script cannot take it yet); needs a hashed install in the spoke (Conclave PR)")


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
    else:
        rep.row("FAIL", label, out.removeprefix("WORKBENCH-HARNESS: "))


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
        rep.row("INFO", "reader record", f"{write_reader_envs(a.envs, readers)}: {len(readers)} reader environments")
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
