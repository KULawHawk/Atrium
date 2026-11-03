"""Command line: ``python -m atrium_check {check,repin} ...``.

Examples (cloud checkouts live side by side under one folder)::

    python -m atrium_check check --repos-root ..
    python -m atrium_check check --repo locutus=C:/Users/jmlee/Desktop/AL/Locutus --only locutus
    python -m atrium_check repin --repos-root ..           # plan only
    python -m atrium_check repin --repos-root .. --apply   # write the new pins

Exit codes: 0 pass, 1 findings fail the run, 2 the registry or arguments are unusable.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from atrium_check.check import (
    RegistryError,
    apply_repin,
    check,
    load_registry,
    plan_repin,
    resolve_checkouts,
)

DEFAULT_REGISTRY = Path(__file__).resolve().parents[2] / "registry" / "contracts.v1.json"


def _parse_overrides(items: list[str]) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for item in items:
        name, sep, path = item.partition("=")
        if not sep or not name or not path:
            raise ValueError(f"--repo expects NAME=PATH, got {item!r}")
        out[name] = Path(path)
    return out


def _git_head(path: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="atrium_check", description="Check the Atrium contract registry against member repos.")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("check", "repin"):
        s = sub.add_parser(name)
        s.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
        s.add_argument("--repos-root", type=Path, default=None, help="folder holding the member checkouts")
        s.add_argument("--repo", action="append", default=[], metavar="NAME=PATH", help="explicit checkout for one member")
        if name == "check":
            s.add_argument("--only", action="append", default=None, metavar="MEMBER", help="limit the run (reported as NOT_EXAMINED)")
            s.add_argument("--strict", action="store_true", help="warnings fail the run")
            s.add_argument("--json", action="store_true", help="print the report as JSON")
            s.add_argument(
                "--allow-unpinned-head",
                action="store_true",
                help="a checkout not at pinned_commit is a warning, not an error (feature-branch runs)",
            )
        else:
            s.add_argument("--apply", action="store_true", help="write the planned pins (default: print the plan only)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        reg = load_registry(args.registry)
        overrides = _parse_overrides(args.repo)
    except (RegistryError, ValueError) as exc:
        print(f"ATRIUM-CHECK: ERROR {exc}", file=sys.stderr)
        return 2
    checkouts = resolve_checkouts(reg, args.repos_root, overrides)

    if args.command == "check":
        heads = {m: _git_head(p) for m, p in checkouts.items()}
        report = check(
            reg, checkouts, only=args.only, strict=args.strict, heads=heads, allow_unpinned_head=args.allow_unpinned_head
        )
        if args.json:
            print(json.dumps(report.to_json(), indent=2))
        else:
            for f in report.findings:
                print(f.line())
            print(report.summary())
        return 0 if report.passed else 1

    changes = plan_repin(reg, checkouts)
    commits = {}
    for member, path in sorted(checkouts.items()):
        head = (_git_head(path) or "")[:7]
        if head and head != reg["members"][member]["pinned_commit"]:
            commits[member] = head
    for name, old, new in changes:
        print(f"PLAN  {name}: {old[:12]} -> {new[:12]}")
    for member, head in commits.items():
        print(f"PLAN  members.{member}.pinned_commit: {reg['members'][member]['pinned_commit']} -> {head}")
    if not changes and not commits:
        print("ATRIUM-REPIN: nothing to change")
        return 0
    if not args.apply:
        print("ATRIUM-REPIN: plan only; re-run with --apply to write")
        return 0
    apply_repin(args.registry, reg, changes, commits)
    print(f"ATRIUM-REPIN: wrote {args.registry}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
