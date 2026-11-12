"""One PASS / FAIL / INCOMPLETE check for any suite repo (locutus, sequoia, obsidian, atrium).

The logic lives here, once. The other three repos carry a ~20 line shim
(``scripts/check_all.py``) that finds this file and calls it, so there is one
copy to fix, not four. Standard library only; costs nothing on GitHub.

    python scripts/check_all.py            # from the root of the repo being changed

What it does, in order:
  1. runs that repo's own pytest suite (full, never a diff-guess: a partial run
     is how a break slips through);
  2. runs ``python -m atrium_check check`` across the sibling checkouts, so a
     contract that drifted between repos turns the result red;
  3. prints one final line to paste into the PR, e.g.
     CHECK-ALL: PASS repo=sequoia head=45043f2d9c10 dirty=no tests=12607 passed/3 skipped atrium_check=PASS

(Atrium's own pytest skips its strict-pin "live member" test unless ATRIUM_REPOS_ROOT is set;
we leave it unset on purpose, because step 2 is the same check made feature-branch-safe.)

Verdicts and exit codes:
  PASS (0)        everything ran and passed.
  FAIL (1)        a test failed, no tests were collected, or atrium_check failed.
  INCOMPLETE (3)  nothing failed but something this repo needs could not run here
                  (for example Obsidian without Tesseract); the missing pieces are
                  listed. INCOMPLETE is never a PASS: run it again on a machine that has them.
  2               the script itself could not start (usage / no checkout found).

Pin drift against the registry is a warning here (feature-branch runs), exactly as
``atrium_check --allow-unpinned-head``; pass ``--strict-pins`` to make it an error.
"""

from __future__ import annotations

import argparse
import os
import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

ATRIUM_ROOT = Path(__file__).resolve().parents[1]
MEMBERS = ("locutus", "sequoia", "obsidian", "atrium")

# Things a repo's suite silently skips without. HARD = INCOMPLETE if missing (the
# skipped tests guard clinical or de-identification behaviour); SOFT = noted only.
NEEDS = {
    "obsidian": {
        "hard": [("binary", "tesseract"), ("module", "PySide6"), ("module", "spacy")],
        "soft": [],
    },
    "sequoia": {"hard": [], "soft": [("module", "z3")]},
    "locutus": {"hard": [], "soft": []},
    "atrium": {"hard": [("module", "jsonschema")], "soft": []},
}


def _have(kind: str, name: str) -> bool:
    if kind == "binary":
        return shutil.which(name) is not None
    return importlib.util.find_spec(name) is not None


def _git(repo: Path, *args: str) -> str:
    try:
        out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return ""
    return out.stdout.strip()


def _counts(text: str) -> dict[str, int]:
    """Parse pytest's last summary line: '12607 passed, 3 skipped, 5 xfailed in 600s'."""
    found: dict[str, int] = {}
    for line in reversed(text.splitlines()):
        pairs = re.findall(r"(\d+) (passed|failed|skipped|xfailed|xpassed|error|errors|deselected)", line)
        if pairs and (" in " in line or "=" in line):
            for n, word in pairs:
                found[word.rstrip("s") if word == "errors" else word] = int(n)
            break
    return found


def find_repo_name(repo_dir: Path) -> str | None:
    name = repo_dir.name.lower()
    return name if name in MEMBERS else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo-dir", type=Path, default=Path.cwd(), help="root of the repo to check (default: current folder)")
    ap.add_argument("--repos-root", type=Path, default=None, help="folder holding all the checkouts (default: parent of --repo-dir)")
    ap.add_argument("--name", choices=MEMBERS, default=None, help="which repo this is (default: from the folder name)")
    ap.add_argument("--strict-pins", action="store_true", help="a checkout not at its registry pin is an error")
    ap.add_argument("--skip-atrium-check", action="store_true", help="tests only (the final line says atrium_check=SKIPPED and the verdict cannot be PASS)")
    ap.add_argument("pytest_args", nargs="*", help="extra arguments for pytest (put them after --)")
    args = ap.parse_args(argv)

    repo = args.repo_dir.resolve()
    name = args.name or find_repo_name(repo)
    if name is None or not (repo / "pyproject.toml").exists():
        print(f"CHECK-ALL: ERROR cannot tell which repo {repo} is (need a folder named {'/'.join(MEMBERS)} with a pyproject.toml, or --name)", file=sys.stderr)
        return 2
    root = (args.repos_root or repo.parent).resolve()
    head = _git(repo, "rev-parse", "HEAD") or "unknown"
    dirty = "yes" if _git(repo, "status", "--porcelain") else "no"

    missing_hard = [n for k, n in NEEDS[name]["hard"] if not _have(k, n)]
    missing_soft = [n for k, n in NEEDS[name]["soft"] if not _have(k, n)]

    # pytest's own `pythonpath = ["src"]` is not seen by tests that spawn a child python, so mirror it.
    src = repo / "src"
    penv = {**os.environ}
    if src.is_dir():
        penv["PYTHONPATH"] = os.pathsep.join(filter(None, [str(src), penv.get("PYTHONPATH", "")]))
    print(f"== {name}: pytest ({repo})", flush=True)
    proc = subprocess.Popen(
        [sys.executable, "-m", "pytest", "-rs", "--no-header", *args.pytest_args],
        cwd=repo, env=penv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    lines: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="", flush=True)
        lines.append(line)
    rc = proc.wait()
    counts = _counts("".join(lines))
    passed, skipped = counts.get("passed", 0), counts.get("skipped", 0)
    failed = counts.get("failed", 0) + counts.get("error", 0)
    tests_ok = rc == 0 and passed > 0
    tests_txt = f"{passed} passed/{skipped} skipped" + (f"/{failed} failed" if failed else "")
    if rc == 5 or passed == 0 and rc == 0:
        tests_txt += " (NO TESTS RAN)"

    if args.skip_atrium_check:
        ac_txt = "SKIPPED"
        ac_ok = False
        first_error = ""
    else:
        first_error = ""
        print(f"\n== atrium_check across {root}", flush=True)
        cmd = [sys.executable, "-m", "atrium_check", "check", "--repos-root", str(root)]
        if not args.strict_pins:
            cmd.append("--allow-unpinned-head")
        env_path = str(ATRIUM_ROOT / "src")
        ac = subprocess.run(cmd, cwd=ATRIUM_ROOT, env={**os.environ, "PYTHONPATH": env_path}, capture_output=True, text=True)
        out = ac.stdout + ac.stderr
        for line in out.splitlines():
            if line.startswith(("ERROR", "WARN", "ATRIUM-CHECK")):
                print(line)
        summary = next((l for l in reversed(out.splitlines()) if l.startswith("ATRIUM-CHECK")), "")
        ac_ok = ac.returncode == 0
        first_err = next((l for l in out.splitlines() if l.startswith("ERROR")), "")
        if first_err:
            parts = first_err.split(None, 3)  # ERROR CODE subject: detail
            first_error = " ".join(parts[1:3]).rstrip(":")
        ac_txt = ("PASS" if ac_ok else "FAIL") + (f" ({summary.replace('ATRIUM-CHECK: ', '')})" if summary else "")

    if not tests_ok or (not ac_ok and not args.skip_atrium_check):
        verdict, rc_out = "FAIL", 1
    elif missing_hard or args.skip_atrium_check:
        verdict, rc_out = "INCOMPLETE", 3
    else:
        verdict, rc_out = "PASS", 0

    notes = []
    if missing_hard:
        notes.append("could not run here (tests for these were skipped): " + ", ".join(missing_hard))
    if missing_soft:
        notes.append("optional, not installed: " + ", ".join(missing_soft))
    if missing_hard and not tests_ok:
        notes.append("tests failed AND these were missing, so the failures may be caused by the missing tools; re-run on a machine that has them before trusting this FAIL: " + ", ".join(missing_hard))
    if dirty == "yes":
        notes.append("working tree has uncommitted changes; the result is not tied to the head sha")
    print()
    for n in notes:
        print(f"NOTE: {n}")
    fe = f" first_error={first_error}" if first_error else ""
    inc = f" missing={','.join(missing_hard)}" if missing_hard else ""
    print(f"CHECK-ALL: {verdict} repo={name} head={head[:12]} dirty={dirty} tests={tests_txt} atrium_check={ac_txt}{inc}{fe}")
    return rc_out


if __name__ == "__main__":
    raise SystemExit(main())
