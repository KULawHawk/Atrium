"""Read the Atrium contract registry and compare it with member-repo checkouts.

Every problem is a :class:`Finding` with a stable ``code``. Severities:

* ``error``: the registry and the member repos disagree on a contract. The run fails.
* ``warn``: a vendored mirror carries different bytes from the registered home file.
  The run passes unless ``strict`` is set.
* ``note``: information only (for example, a mirror pinned at an older commit whose
  contract files are still identical).

A member whose checkout is not supplied is an error, never a silent skip. Narrowing
the run is explicit (``only=``) and the result says what was left out.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # Python 3.11+
    from re import _parser as _re_parser
except ImportError:  # pragma: no cover - older interpreters
    import sre_parse as _re_parser  # type: ignore[no-redef]

REGISTRY_CONTRACT = "AtriumContractRegistry/1"
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
ID_PREFIX = "https://apex-suite/"
KINDS = ("json_schema", "data")
SEVERITIES = ("error", "warn", "note")


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    subject: str
    message: str

    def line(self) -> str:
        return f"{self.severity.upper():5} {self.code:22} {self.subject}: {self.message}"


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    contracts_checked: int = 0
    files_hashed: int = 0
    enums_compared: int = 0
    mirror_files_compared: int = 0
    members_examined: list[str] = field(default_factory=list)
    members_skipped: list[str] = field(default_factory=list)
    strict: bool = False

    def add(self, severity: str, code: str, subject: str, message: str) -> None:
        self.findings.append(Finding(severity, code, subject, message))

    def count(self, severity: str) -> int:
        return sum(1 for f in self.findings if f.severity == severity)

    @property
    def passed(self) -> bool:
        if self.contracts_checked == 0:
            return False
        if self.count("error"):
            return False
        return not (self.strict and self.count("warn"))

    def summary(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        parts = [
            f"ATRIUM-CHECK: {verdict}",
            f"errors={self.count('error')}",
            f"warnings={self.count('warn')}",
            f"notes={self.count('note')}",
            f"contracts={self.contracts_checked}",
            f"files_hashed={self.files_hashed}",
            f"enums={self.enums_compared}",
            f"mirror_files={self.mirror_files_compared}",
            f"members={','.join(self.members_examined) or '-'}",
        ]
        if self.members_skipped:
            parts.append(f"NOT_EXAMINED={','.join(self.members_skipped)}")
        if self.contracts_checked == 0:
            parts.append("reason=no contract was examined")
        return " ".join(parts)

    def to_json(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "strict": self.strict,
            "contracts_checked": self.contracts_checked,
            "files_hashed": self.files_hashed,
            "enums_compared": self.enums_compared,
            "mirror_files_compared": self.mirror_files_compared,
            "members_examined": self.members_examined,
            "members_skipped": self.members_skipped,
            "findings": [f.__dict__ for f in self.findings],
        }


class RegistryError(ValueError):
    """The registry file itself is malformed."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_pointer(doc: Any, pointer: str) -> Any:
    """Resolve an RFC 6901 JSON pointer. Raises KeyError when any step is absent."""
    if pointer == "":
        return doc
    if not pointer.startswith("/"):
        raise KeyError(pointer)
    node = doc
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            if not token.isdigit() or int(token) >= len(node):
                raise KeyError(pointer)
            node = node[int(token)]
        elif isinstance(node, dict) and token in node:
            node = node[token]
        else:
            raise KeyError(pointer)
    return node


def _anchor_positions(pat: str) -> list[int]:
    """Indices of each ``$`` in ``pat`` that is an end anchor (not escaped, not inside ``[...]``)."""
    out: list[int] = []
    i, in_class = 0, False
    while i < len(pat):
        ch = pat[i]
        if ch == "\\":
            i += 2
            continue
        if in_class:
            in_class = ch != "]"
        elif ch == "[":
            in_class = True
            if pat[i + 1 : i + 2] == "]":  # a leading ']' is a literal
                i += 1
        elif ch == "$":
            out.append(i)
        i += 1
    return out


NEWLINE_GUARDS = ("(?!\\n)", "(?![\\s\\S])")  # straight after a '$'
LEADING_GUARDS = ("^(?!.*\\n)", "^(?![\\s\\S]*\\n)")  # at the very start: no newline anywhere


def _widths(pat: str) -> tuple[int, int] | None:
    try:
        lo, hi = _re_parser.parse(pat).getwidth()
    except Exception:  # noqa: BLE001 - any parse failure means "cannot prove bounded"
        return None
    return lo, hi


def newline_leak(node: Mapping[str, Any]) -> str | None:
    """Why ``node`` (a schema with a string ``pattern``) accepts ``value + "\\n"``, or None.

    Python's ``jsonschema`` applies ``pattern`` with ``re.search``, where ``$`` also
    matches just before a final newline, so ``"<64 hex>\\n"`` passes ``^[0-9a-f]{64}$``.
    The gap is closed only when either

    * every ``$`` anchor is followed by a guard such as ``(?!\\n)``, or the pattern
      opens with ``^(?!.*\\n)`` (Locutus #25's form), or
    * ``maxLength`` is at most the pattern's minimum match width, so the extra
      character always overflows. A ``maxLength`` above that (for example 128 on a
      variable-width ``^[a-z_]+$``) does not close it.
    """
    pat = node["pattern"]
    anchors = _anchor_positions(pat)
    if not anchors:
        return None
    if pat.startswith(LEADING_GUARDS) or all(pat.startswith(NEWLINE_GUARDS, a + 1) for a in anchors):
        return None
    ml = node.get("maxLength")
    widths = _widths(pat)
    if widths is None:
        return "pattern does not parse, so its width cannot be bounded; add a (?!\\n) guard after '$'"
    lo, hi = widths
    if isinstance(ml, int) and not isinstance(ml, bool) and ml <= lo:
        return None
    fix = f"add maxLength {lo}" if lo == hi else "add a (?!\\n) guard after '$'"
    if ml is None:
        return f"no maxLength; {fix}"
    return f"maxLength {ml} exceeds the minimum match width {lo}, so a shorter value plus newline still fits; {fix}"


def unbounded_anchored_patterns(doc: Any, path: str = "") -> list[tuple[str, str]]:
    """(JSON pointer, reason) for every string schema whose ``pattern`` accepts a trailing newline."""
    found: list[tuple[str, str]] = []
    if isinstance(doc, dict):
        if isinstance(doc.get("pattern"), str):
            why = newline_leak(doc)
            if why is not None:
                found.append((path or "/", why))
        for k, v in doc.items():
            found.extend(unbounded_anchored_patterns(v, f"{path}/{k}"))
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            found.extend(unbounded_anchored_patterns(v, f"{path}/{i}"))
    return found


# --------------------------------------------------------------------------- registry


def _require(cond: bool, problems: list[str], message: str) -> bool:
    if not cond:
        problems.append(message)
    return cond


def validate_registry(reg: Any) -> list[str]:
    """Return every structural problem in a registry document (empty when valid)."""
    problems: list[str] = []
    if not _require(isinstance(reg, dict), problems, "registry: not a JSON object"):
        return problems
    _require(reg.get("registry") == REGISTRY_CONTRACT, problems, f"registry: 'registry' must be {REGISTRY_CONTRACT!r}")
    _require(reg.get("owner") == "Atrium", problems, "registry: 'owner' must be 'Atrium'")
    roster = reg.get("tool_roster")
    roster_ok = _require(
        isinstance(roster, list) and roster and all(isinstance(t, str) and t for t in roster),
        problems,
        "tool_roster: must be a non-empty list of strings",
    )
    if roster_ok:
        _require(len(set(roster)) == len(roster), problems, "tool_roster: duplicate tool")

    members = reg.get("members")
    if not _require(isinstance(members, dict) and members, problems, "members: must be a non-empty object"):
        members = {}
    for name, m in members.items():
        subj = f"members.{name}"
        if not _require(isinstance(m, dict), problems, f"{subj}: must be an object"):
            continue
        for key in ("repo", "dir", "pinned_commit"):
            _require(isinstance(m.get(key), str) and m.get(key), problems, f"{subj}.{key}: required string")
        dirs = m.get("contract_dirs")
        _require(
            isinstance(dirs, list) and all(isinstance(d, str) and d for d in dirs),
            problems,
            f"{subj}.contract_dirs: must be a list of strings",
        )

    contracts = reg.get("contracts")
    if not _require(isinstance(contracts, list) and contracts, problems, "contracts: must be a non-empty list"):
        contracts = []
    seen: set[str] = set()
    for i, c in enumerate(contracts):
        subj = f"contracts[{i}]"
        if not _require(isinstance(c, dict), problems, f"{subj}: must be an object"):
            continue
        name = c.get("name")
        if _require(isinstance(name, str) and _split_name(name) is not None, problems, f"{subj}.name: must look like 'Name/<int>'"):
            _require(name not in seen, problems, f"{subj}.name: duplicate contract {name}")
            seen.add(name)
        _require(c.get("home") in members, problems, f"{subj}.home: not a registered member")
        _require(isinstance(c.get("path"), str) and c.get("path"), problems, f"{subj}.path: required string")
        _require(c.get("kind") in KINDS, problems, f"{subj}.kind: must be one of {KINDS}")
        ptr = c.get("const_pointer")
        _require(ptr is None or isinstance(ptr, str), problems, f"{subj}.const_pointer: string or null")
        cv = c.get("const_value")
        _require(cv is None or (isinstance(cv, str) and cv and ptr is not None), problems, f"{subj}.const_value: a string, and only with a const_pointer")
        sha = c.get("sha256")
        _require(
            isinstance(sha, str) and len(sha) == 64 and all(ch in "0123456789abcdef" for ch in sha),
            problems,
            f"{subj}.sha256: 64 lowercase hex characters",
        )

    enums = reg.get("tool_enums", [])
    if _require(isinstance(enums, list), problems, "tool_enums: must be a list"):
        for i, e in enumerate(enums):
            subj = f"tool_enums[{i}]"
            if not _require(isinstance(e, dict), problems, f"{subj}: must be an object"):
                continue
            _require(e.get("contract") in seen, problems, f"{subj}.contract: not a registered contract")
            _require(isinstance(e.get("pointer"), str), problems, f"{subj}.pointer: required string")
            exp = e.get("expect")
            _require(
                exp == "roster" or (isinstance(exp, list) and all(isinstance(t, str) for t in exp)),
                problems,
                f"{subj}.expect: 'roster' or a list of tool names",
            )
            if isinstance(exp, list):
                _require(isinstance(e.get("why"), str) and e.get("why"), problems, f"{subj}.why: a subset needs a reason")
                if roster_ok:
                    outside = sorted(set(exp) - set(roster))
                    _require(not outside, problems, f"{subj}.expect: not in tool_roster: {outside}")

    mirrors = reg.get("mirrors", [])
    if _require(isinstance(mirrors, list), problems, "mirrors: must be a list"):
        for i, mi in enumerate(mirrors):
            subj = f"mirrors[{i}]"
            if not _require(isinstance(mi, dict), problems, f"{subj}: must be an object"):
                continue
            _require(mi.get("home") in members, problems, f"{subj}.home: not a registered member")
            _require(mi.get("in") in members, problems, f"{subj}.in: not a registered member")
            for key in ("root", "manifest"):
                _require(isinstance(mi.get(key), str) and mi.get(key), problems, f"{subj}.{key}: required string")
    replicas = reg.get("replicas", [])
    if _require(isinstance(replicas, list), problems, "replicas: must be a list"):
        for i, rp in enumerate(replicas):
            subj = f"replicas[{i}]"
            if not _require(isinstance(rp, dict), problems, f"{subj}: must be an object"):
                continue
            _require(rp.get("contract") in seen, problems, f"{subj}.contract: not a registered contract")
            _require(rp.get("in") in members, problems, f"{subj}.in: not a registered member")
            _require(isinstance(rp.get("path"), str) and rp.get("path"), problems, f"{subj}.path: required string")
    return problems


def _split_name(name: str) -> tuple[str, int] | None:
    base, sep, ver = name.rpartition("/")
    if not sep or not base or not ver.isdigit() or ver.startswith("0"):
        return None
    return base, int(ver)


def load_registry(path: Path) -> dict[str, Any]:
    try:
        reg = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"{path}: {exc}") from exc
    problems = validate_registry(reg)
    if problems:
        raise RegistryError("; ".join(problems))
    return reg


# --------------------------------------------------------------------------- checkouts


def resolve_checkouts(
    reg: Mapping[str, Any],
    repos_root: Path | None = None,
    overrides: Mapping[str, Path] | None = None,
) -> dict[str, Path]:
    """Map member name -> checkout directory.

    An explicit override wins. Otherwise ``repos_root/<dir>`` is used, matched
    case-insensitively (the cloud checkouts are lower-case, Jake's PC uses the
    registry's spelling). A member with no existing directory is left out.
    """
    found: dict[str, Path] = {}
    overrides = dict(overrides or {})
    listing: dict[str, Path] = {}
    if repos_root is not None and Path(repos_root).is_dir():
        listing = {p.name.lower(): p for p in Path(repos_root).iterdir() if p.is_dir()}
    for name, m in reg["members"].items():
        if name in overrides:
            p = Path(overrides[name])
            if p.is_dir():
                found[name] = p
            continue
        p = listing.get(m["dir"].lower())
        if p is not None:
            found[name] = p
    return found


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- check


def check(
    reg: Mapping[str, Any],
    checkouts: Mapping[str, Path],
    *,
    only: Iterable[str] | None = None,
    strict: bool = False,
    heads: Mapping[str, str | None] | None = None,
    allow_unpinned_head: bool = False,
) -> Report:
    """Compare the registry with the member checkouts and return a :class:`Report`.

    ``heads`` maps a member to the commit its checkout has checked out (None when it
    is not a git checkout). When given, a checkout whose HEAD is not the member's
    ``pinned_commit`` is an error (``HEAD_NOT_PINNED``), so a run cannot silently
    check the wrong commit; ``allow_unpinned_head`` lowers it to a warning for
    deliberate runs against a feature branch. Without ``heads`` the run says so
    (``HEAD_NOT_CHECKED``).
    """
    report = Report(strict=strict)
    members = reg["members"]
    scope = set(only) if only is not None else set(members)
    for name in sorted(scope - set(members)):
        report.add("error", "UNKNOWN_MEMBER", name, "not a registered member")
    scope &= set(members)

    for name in sorted(members):
        if name not in scope:
            report.members_skipped.append(name)
        elif name not in checkouts:
            report.add("error", "MEMBER_MISSING", name, f"no checkout found for {members[name]['repo']}")
            report.members_skipped.append(name)
        else:
            report.members_examined.append(name)

    examined = set(report.members_examined)
    _check_heads(report, members, sorted(examined), heads, allow_unpinned_head)
    docs: dict[str, Any] = {}
    registered_paths: dict[str, set[str]] = {m: set() for m in members}

    for c in reg["contracts"]:
        registered_paths[c["home"]].add(c["path"])
        if c["home"] not in examined:
            continue
        doc = _check_contract(report, c, checkouts[c["home"]])
        if doc is not None:
            docs[c["name"]] = doc

    for name in sorted(examined):
        _check_unregistered(report, name, members[name], checkouts[name], registered_paths[name])

    roster = list(reg["tool_roster"])
    for e in reg.get("tool_enums", []):
        if e["contract"] in docs:
            _check_enum(report, e, docs[e["contract"]], roster)

    for mi in reg.get("mirrors", []):
        if mi["in"] in examined:
            _check_mirror(report, reg, mi, checkouts[mi["in"]])

    by_name = {c["name"]: c for c in reg["contracts"]}
    for rp in reg.get("replicas", []):
        if rp["in"] in examined:
            _check_replica(report, by_name[rp["contract"]], rp, checkouts[rp["in"]])
    return report


def _check_heads(
    report: Report,
    members: Mapping[str, Any],
    examined: list[str],
    heads: Mapping[str, str | None] | None,
    allow_unpinned_head: bool,
) -> None:
    if heads is None:
        if examined:
            report.add("note", "HEAD_NOT_CHECKED", ",".join(examined), "checkout commits were not compared with pinned_commit")
        return
    for name in examined:
        pin = members[name]["pinned_commit"]
        head = heads.get(name)
        if head is None:
            report.add("warn", "HEAD_UNKNOWN", name, f"not a git checkout; cannot confirm it is at pinned_commit {pin}")
        elif not (head.startswith(pin) or pin.startswith(head)):
            report.add(
                "warn" if allow_unpinned_head else "error",
                "HEAD_NOT_PINNED",
                name,
                f"checkout is at {head[:12]}, registry pins {pin}; check out the pin, or `repin` if the member moved",
            )


def _check_replica(report: Report, c: Mapping[str, Any], rp: Mapping[str, Any], root: Path) -> None:
    """A single-file copy of a contract kept by another member (for example a test fixture)."""
    subj = f"{rp['in']}:{rp['path']}"
    f = root / rp["path"]
    if not f.is_file():
        report.add("warn", "REPLICA_MISSING", subj, f"replica of {c['name']} does not exist")
        return
    report.mirror_files_compared += 1
    actual = sha256_file(f)
    if actual != c["sha256"]:
        report.add(
            "warn",
            "REPLICA_STALE",
            subj,
            f"{c['name']}: replica sha256 {actual[:12]} != registry {c['sha256'][:12]} (re-pin the replica)",
        )


def _check_contract(report: Report, c: Mapping[str, Any], root: Path) -> Any:
    name = c["name"]
    path = root / c["path"]
    report.contracts_checked += 1
    if not path.is_file():
        report.add("error", "FILE_MISSING", name, f"{c['home']}:{c['path']} does not exist")
        return None
    actual = sha256_file(path)
    report.files_hashed += 1
    if actual != c["sha256"]:
        report.add(
            "error",
            "PIN_DRIFT",
            name,
            f"{c['home']}:{c['path']} sha256 {actual[:12]} != registry {c['sha256'][:12]}; "
            "a contract change must update the registry in the same change (run `repin`)",
        )
    try:
        doc = _load_json(path)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        report.add("error", "JSON_INVALID", name, f"{c['path']}: {exc}")
        return None

    if c["const_pointer"] is not None:
        try:
            const = resolve_pointer(doc, c["const_pointer"])
        except KeyError:
            report.add("error", "CONST_MISSING", name, f"no value at {c['const_pointer']}")
        else:
            expected = c.get("const_value") or name
            if const != expected:
                report.add("error", "CONST_MISMATCH", name, f"file declares {const!r} at {c['const_pointer']}, expected {expected!r}")
            elif expected != name:
                report.add("note", "CONST_NONSTANDARD", name, f"declares {const!r}, not the suite form {name!r}")

    if c["kind"] == "json_schema":
        if not isinstance(doc, dict):
            report.add("error", "SCHEMA_NOT_OBJECT", name, "a JSON Schema must be an object")
            return doc
        if doc.get("$schema") != SCHEMA_DIALECT:
            report.add("error", "DIALECT", name, f"$schema is {doc.get('$schema')!r}, expected 2020-12")
        expected_id = f"{ID_PREFIX}{c['home']}/contracts/{Path(c['path']).name}"
        if doc.get("$id") != expected_id:
            report.add("error", "ID_MISMATCH", name, f"$id is {doc.get('$id')!r}, expected {expected_id!r}")
        for where, why in unbounded_anchored_patterns(doc):
            report.add(
                "warn",
                "PATTERN_UNBOUNDED",
                name,
                f"{where}: accepts a trailing newline under Python's jsonschema (re.search): {why}",
            )
        _, version = _split_name(name)  # type: ignore[misc]
        if f".v{version}." not in Path(c["path"]).name:
            report.add("error", "VERSION_FILENAME", name, f"file name {Path(c['path']).name} does not carry .v{version}.")
    return doc


def _check_unregistered(report: Report, member: str, m: Mapping[str, Any], root: Path, registered: set[str]) -> None:
    for d in m["contract_dirs"]:
        base = root / d
        if not base.is_dir():
            report.add("error", "CONTRACT_DIR_MISSING", member, f"{d} does not exist")
            continue
        for f in sorted(base.glob("*.json")):
            rel = f.relative_to(root).as_posix()
            if rel not in registered:
                report.add(
                    "error",
                    "UNREGISTERED_FILE",
                    member,
                    f"{rel} is a contract file the Atrium registry does not name",
                )


def _check_enum(report: Report, e: Mapping[str, Any], doc: Any, roster: list[str]) -> None:
    subj = f"{e['contract']} {e['pointer']}"
    report.enums_compared += 1
    try:
        values = resolve_pointer(doc, e["pointer"])
    except KeyError:
        report.add("error", "ENUM_POINTER_MISSING", subj, "pointer does not resolve")
        return
    if not isinstance(values, list):
        report.add("error", "ENUM_POINTER_MISSING", subj, "pointer does not resolve to a list")
        return
    if len(set(values)) != len(values):
        report.add("error", "ENUM_DUPLICATE", subj, "duplicate tool value")
    unknown = sorted(set(values) - set(roster))
    if unknown:
        report.add("error", "ENUM_UNKNOWN_TOOL", subj, f"not in the Atrium tool roster: {unknown}")
    expected = roster if e["expect"] == "roster" else e["expect"]
    if set(values) != set(expected):
        missing = sorted(set(expected) - set(values))
        extra = sorted(set(values) - set(expected))
        report.add("error", "ENUM_MISMATCH", subj, f"missing {missing}, unexpected {extra}")


def _check_mirror(report: Report, reg: Mapping[str, Any], mi: Mapping[str, Any], root: Path) -> None:
    subj = f"{mi['in']}:{mi['root']}"
    base = root / mi["root"]
    if not base.is_dir():
        report.add("warn", "MIRROR_MISSING", subj, "mirror directory does not exist")
        return
    manifest_path = base / mi["manifest"]
    pinned = None
    if manifest_path.is_file():
        try:
            manifest = _load_json(manifest_path)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            report.add("warn", "MIRROR_MANIFEST", subj, f"{mi['manifest']}: {exc}")
        else:
            pinned = manifest.get("upstream_commit") if isinstance(manifest, dict) else None
    else:
        report.add("warn", "MIRROR_MANIFEST", subj, f"{mi['manifest']} not found")

    stale = 0
    for c in reg["contracts"]:
        if c["home"] != mi["home"]:
            continue
        f = base / c["path"]
        if not f.is_file():
            report.add("note", "MIRROR_SUBSET", subj, f"does not carry {c['name']} ({c['path']})")
            continue
        report.mirror_files_compared += 1
        actual = sha256_file(f)
        if actual != c["sha256"]:
            stale += 1
            report.add(
                "warn",
                "MIRROR_STALE",
                subj,
                f"{c['name']}: vendored sha256 {actual[:12]} != registry {c['sha256'][:12]} (re-vendor)",
            )
    home_pin = reg["members"][mi["home"]]["pinned_commit"]
    if pinned and not _same_commit(pinned, home_pin):
        level = "warn" if stale else "note"
        report.add(
            level,
            "MIRROR_PIN",
            subj,
            f"vendored at {pinned}, registry pins {mi['home']} at {home_pin}"
            + ("" if stale else "; every registered contract file is still identical"),
        )


def _same_commit(a: str, b: str) -> bool:
    n = min(len(a), len(b))
    return n >= 7 and a[:n].lower() == b[:n].lower()


# --------------------------------------------------------------------------- repin


def plan_repin(reg: Mapping[str, Any], checkouts: Mapping[str, Path]) -> list[tuple[str, str, str]]:
    """Return ``(contract, old_sha, new_sha)`` for every registered file whose bytes changed.

    Members without a checkout and missing files are left out (``check`` reports them).
    """
    changes: list[tuple[str, str, str]] = []
    for c in reg["contracts"]:
        root = checkouts.get(c["home"])
        if root is None:
            continue
        p = root / c["path"]
        if p.is_file():
            new = sha256_file(p)
            if new != c["sha256"]:
                changes.append((c["name"], c["sha256"], new))
    return changes


def apply_repin(
    registry_path: Path,
    reg: dict[str, Any],
    changes: list[tuple[str, str, str]],
    commits: Mapping[str, str] | None = None,
) -> None:
    """Write the new pins (and member commits) atomically: temp file, then replace."""
    new = {name: sha for name, _, sha in changes}
    for c in reg["contracts"]:
        if c["name"] in new:
            c["sha256"] = new[c["name"]]
    for member, commit in (commits or {}).items():
        reg["members"][member]["pinned_commit"] = commit
    text = json.dumps(reg, indent=2, ensure_ascii=False) + "\n"
    tmp = Path(registry_path).with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(registry_path)
