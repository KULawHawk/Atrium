"""One learning folder per aim: ``<root>\\learning\\<aim>\\{inbox,approved,held-aside,feedback}`` + ``manifest.jsonl``.

Rules carried here (design §2, §3, §7, §8):

* The installer creates the folders; this code never creates an aim folder and refuses loudly if one is missing.
* ``manifest.jsonl`` is append-only, one JSON object per line, keys ``sha256, class, source, added_at,
  added_by, gate, event`` (``added`` | ``held_aside``) and ``reason`` only on ``held_aside``. No file names,
  no content values. An item's state is its latest event.
* Classes: ``S`` synthetic/public, ``M`` from a licensed manual (needs Jake's OK for that manual on record),
  ``P`` derived from a real report (needs the aim's own gate AND a human check: Decision 38 = A).
* Nothing is deleted (SEC-8): taking an item out moves it to ``held-aside``.
* Decision 53 ("A but give it a 30 day window"): an item Jake removed himself (``removed_by_jake``) stays out,
  except that for 30 days after his removal he may put that same item back by his own click
  (:meth:`LearningFolder.add_back`: a warning naming the days left, then the usual fresh check). After 30 days the
  refusal is permanent. The automatic path never re-adds anything that was held aside.
* An aim may keep its own side files in other subfolders (Obsidian keeps signed labels in ``labels\\``,
  named ``<sha256>.obsidian.json``). Only ``approved\\`` items and their manifest rows are ever copied out;
  other subfolders are never read by copy-out and never copied.
* An aim's gate returns a :class:`GateResult` or any object with bool ``passed``, bool ``human_checked`` and a
  string ``gate``; anything else is refused.
* "Add automatically" is a per-aim switch, OFF by default; each change writes an audit line. With it off,
  :meth:`LearningFolder.offer` adds nothing and the item waits for Jake's click.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

AIMS = (
    "readers-print",
    "handwriting",
    "formulas-tables",
    "obsidian",
    "obsidian-wording",
    "sequoia",
    "locutus",
    "conclave-voting",
    "install-health",
)
SUBFOLDERS = ("inbox", "approved", "held-aside", "feedback")
CLASSES = ("S", "M", "P")
HOLD_REASONS = (
    "removed_by_jake",
    "identifier_found",
    "recheck_failed",
    "manual_ok_withdrawn",
    "licence_problem",
)
ADD_BACK_DAYS = 30  # Decision 53 (Jake 11/23/2026): "A but give it a 30 day window"
MANIFEST = "manifest.jsonl"
SETTINGS = "settings.json"
AUDIT = "audit.jsonl"
MANUAL_OKS = "manual_oks.jsonl"

_AIM_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_SUFFIX = re.compile(r"^\.[a-z0-9]{1,8}$")
_SECRET_NAME = re.compile(
    r"(^\.env$|credential|secret|api[ _-]?key|token|password|\.kdbx$|\.pem$|\.key$|\.pfx$|\.p12$)",
    re.IGNORECASE,
)
_MAX_SOURCE = 200


class LearningFolderError(RuntimeError):
    """A refusal. The message starts with ``LEARNING: FAIL`` so it is never mistaken for a pass."""

    def __init__(self, why: str) -> None:
        super().__init__(f"LEARNING: FAIL {why}")


@dataclass(frozen=True)
class GateResult:
    """What an aim's gate says about one item. ``human_checked`` = a person looked it over (Decision 38)."""

    passed: bool
    gate: str
    human_checked: bool = False


Gate = Callable[[Path], GateResult]


def _verdict(result: object) -> GateResult:
    """Accept a :class:`GateResult` or any object shaped like one, so an aim (Obsidian) need not import this library.

    The shape is strict: ``passed`` and ``human_checked`` must be real ``bool`` values (not 1, "yes" or None) and
    ``gate`` a non-empty one-line string. Anything else is a refusal, never a pass.
    """
    passed = getattr(result, "passed", None)
    human = getattr(result, "human_checked", None)
    gate = getattr(result, "gate", None)
    if type(passed) is not bool or type(human) is not bool or not isinstance(gate, str):
        raise LearningFolderError(
            "the aim's gate did not return a GateResult (passed and human_checked must be bool, gate a string)"
        )
    return GateResult(passed=passed, gate=_text(gate, "gate"), human_checked=human)


def add_back_warning(days_left: int) -> str:
    """The words shown before Jake puts back an item he removed (Decision 53)."""
    day = "day" if days_left == 1 else "days"
    return (f"You took this out of the learning folder yourself. You can put it back by your own click for "
            f"{days_left} more {day}; after that it stays out for good.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _text(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise LearningFolderError(f"{what} must be one non-empty line")
    if len(value) > _MAX_SOURCE:
        raise LearningFolderError(f"{what} is longer than {_MAX_SOURCE} characters")
    return value


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            raise LearningFolderError(f"{path.name} line {n} is not JSON") from None
        if not isinstance(row, dict):
            raise LearningFolderError(f"{path.name} line {n} is not an object")
        rows.append(row)
    return rows


def _append(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def find_install_root(prefix: str | os.PathLike | None = None) -> Path:
    """Read ``install_root`` from the environment's ``adastra.json`` (Atrium #54). Refuse if missing; never guess."""
    marker = Path(prefix if prefix is not None else sys.prefix) / "adastra.json"
    if not marker.is_file():
        raise LearningFolderError(f"no adastra.json in {marker.parent}; this environment was not installed by AdAstra")
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise LearningFolderError(f"{marker} is not readable JSON") from None
    root = data.get("install_root") if isinstance(data, dict) else None
    if not isinstance(root, str) or not root.strip():
        raise LearningFolderError(f"{marker} has no install_root")
    return Path(root)


def manual_oks(root: Path) -> set[str]:
    """Manuals Jake has OK'd for learning folders (LF-3), from ``<root>\\learning\\manual_oks.jsonl``."""
    state: dict[str, str] = {}
    for row in _read_jsonl(Path(root) / "learning" / MANUAL_OKS):
        state[str(row.get("manual"))] = str(row.get("event"))
    return {m for m, ev in state.items() if ev == "ok"}


def record_manual_ok(
    root: Path,
    manual: str,
    by: str,
    ok: bool = True,
    words: str | None = None,
    revisit: str | None = None,
    list_sha256: str | None = None,
) -> list[str]:
    """Record Jake's OK for one manual, or withdraw it. Withdrawing moves that manual's items aside in every aim.

    ``words`` is his answer verbatim (one line) and ``revisit`` an ISO date to look again; both are kept on the
    OK line so the record shows exactly what he said and when. ``list_sha256`` is the sha256 of the list the
    OK came from, when it came from one. Returns the sha256 of every item moved aside.
    """
    learning = Path(root) / "learning"
    if not learning.is_dir():
        raise LearningFolderError(f"{learning} does not exist; run the AdAstra installer")
    row = {"manual": _text(manual, "manual"), "event": "ok" if ok else "withdrawn", "at": _now(), "by": _text(by, "by")}
    if words is not None:
        row["words"] = _text(words, "words")
    if revisit is not None:
        try:
            row["revisit"] = date.fromisoformat(revisit).isoformat()
        except (TypeError, ValueError):
            raise LearningFolderError(f"revisit {revisit!r} is not a YYYY-MM-DD date") from None
    if list_sha256 is not None:
        if not re.fullmatch(r"[0-9a-f]{64}", str(list_sha256)):
            raise LearningFolderError("list_sha256 must be 64 lower-case hex characters")
        row["list_sha256"] = list_sha256
    _append(learning / MANUAL_OKS, row)
    moved: list[str] = []
    if not ok:
        for aim_dir in sorted(p for p in learning.iterdir() if p.is_dir() and _AIM_NAME.match(p.name)):
            folder = LearningFolder(root, aim_dir.name)
            for sha, row in folder.state().items():
                if row.get("event") == "added" and row.get("class") == "M" and row.get("source") == manual:
                    folder.hold_aside(sha, "manual_ok_withdrawn", by)
                    moved.append(sha)
    return moved


class LearningFolder:
    """One aim's folder. Construct with the install root (see :func:`find_install_root`) and the aim name."""

    def __init__(self, root: str | os.PathLike, aim: str) -> None:
        if not isinstance(aim, str) or not _AIM_NAME.match(aim):
            raise LearningFolderError(f"aim name {aim!r} is not a folder name (lower case, digits, dashes)")
        self.root = Path(root)
        self.aim = aim
        self.dir = self.root / "learning" / aim
        missing = [s for s in (*SUBFOLDERS,) if not (self.dir / s).is_dir()]
        if not (self.dir / MANIFEST).is_file():
            missing.append(MANIFEST)
        if missing:
            raise LearningFolderError(f"{self.dir} is missing {', '.join(missing)}; run the AdAstra installer")

    # ---- reading -------------------------------------------------------------------------------------

    def events(self) -> list[dict]:
        rows = _read_jsonl(self.dir / MANIFEST)
        for n, row in enumerate(rows, 1):
            if row.get("event") not in ("added", "held_aside") or not isinstance(row.get("sha256"), str):
                raise LearningFolderError(f"{MANIFEST} entry {n} has no valid event/sha256")
        return rows

    def state(self) -> dict[str, dict]:
        latest: dict[str, dict] = {}
        for row in self.events():
            latest[row["sha256"]] = row
        return latest

    def approved(self) -> list[str]:
        return sorted(sha for sha, row in self.state().items() if row["event"] == "added")

    def _file(self, sub: str, sha: str) -> Path:
        hits = sorted(p for p in (self.dir / sub).iterdir() if p.is_file() and p.name.split(".")[0] == sha)
        if len(hits) != 1:
            raise LearningFolderError(f"{sub}\\ holds {len(hits)} files for item {sha[:12]}, expected 1")
        return hits[0]

    # ---- the switch ----------------------------------------------------------------------------------

    @property
    def auto_add(self) -> bool:
        path = self.dir / SETTINGS
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise LearningFolderError(f"{path} is not readable JSON") from None
        value = data.get("auto_add", False) if isinstance(data, dict) else None
        if not isinstance(value, bool):
            raise LearningFolderError(f"{path} auto_add is not true/false")
        return value

    def set_auto_add(self, on: bool, by: str) -> None:
        if not isinstance(on, bool):
            raise LearningFolderError("auto_add must be true or false")
        by = _text(by, "by")
        tmp = self.dir / (SETTINGS + ".tmp")
        tmp.write_text(json.dumps({"auto_add": on}, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, self.dir / SETTINGS)
        _append(self.dir / AUDIT, {"at": _now(), "by": by, "setting": "auto_add", "value": on})

    # ---- gate ----------------------------------------------------------------------------------------

    def _check(self, item: Path, cls: str, source: str, gate: Gate | None) -> str:
        if cls not in CLASSES:
            raise LearningFolderError(f"class {cls!r} is not one of {', '.join(CLASSES)}")
        if _SECRET_NAME.search(item.name):
            raise LearningFolderError("the item's name looks like a secret or key file; refused (SEC-3)")
        if not item.is_file():
            raise LearningFolderError("the item is not a file")
        if cls == "M" and source not in manual_oks(self.root):
            raise LearningFolderError("no OK from Jake on record for this manual (LF-3)")
        if cls == "P" and gate is None:
            raise LearningFolderError("a real-report item needs its aim's own gate")
        if gate is None:
            return "manual_ok" if cls == "M" else "provenance"
        result = _verdict(gate(item))
        if not result.passed:
            raise LearningFolderError(f"gate {result.gate} refused the item")
        if cls == "P" and not result.human_checked:
            raise LearningFolderError("a real-report item must be checked by a person first (Decision 38 = A)")
        return _text(result.gate, "gate")

    # ---- writing -------------------------------------------------------------------------------------

    def add(self, item: str | os.PathLike, cls: str, source: str, added_by: str, gate: Gate | None = None) -> str:
        """Copy one item into ``approved\\`` after its class's gate passes. Returns its sha256."""
        item = Path(item)
        source = _text(source, "source")
        added_by = _text(added_by, "added_by")
        gate_name = self._check(item, cls, source, gate)
        sha = _sha256(item)
        if self.state().get(sha, {}).get("event") == "added":
            raise LearningFolderError(f"item {sha[:12]} is already in approved\\")
        left = self.add_back_days_left(sha)
        if left == 0:
            raise LearningFolderError(
                f"Jake removed item {sha[:12]} more than {ADD_BACK_DAYS} days ago; it can no longer be added back"
            )
        if left is not None:
            raise LearningFolderError(f"Jake removed item {sha[:12]} earlier. {add_back_warning(left)}")
        suffix = item.suffix.lower() if _SUFFIX.match(item.suffix.lower()) else ""
        target = self.dir / "approved" / f"{sha}{suffix}"
        tmp = target.with_name(target.name + ".tmp")
        shutil.copyfile(item, tmp)
        os.replace(tmp, target)
        _append(
            self.dir / MANIFEST,
            {"sha256": sha, "class": cls, "source": source, "added_at": _now(), "added_by": added_by,
             "gate": gate_name, "event": "added"},
        )
        return sha

    def offer(self, item: str | os.PathLike, cls: str, source: str, gate: Gate | None = None) -> str | None:
        """Automatic path. Switch off (default): adds nothing, returns None; the item waits for Jake's click.
        Never re-adds an item that was held aside, for any reason (Decision 53: only his own click can)."""
        if not self.auto_add:
            return None
        if Path(item).is_file() and self.state().get(_sha256(Path(item)), {}).get("event") == "held_aside":
            raise LearningFolderError("this item was taken out of the learning folder; automatic adding never puts it back")
        return self.add(item, cls, source, "auto", gate)

    # ---- Decision 53: putting back an item Jake removed ----------------------------------------------

    def add_back_days_left(self, sha: str, now: datetime | None = None) -> int | None:
        """Whole days left (rounded up) in which Jake may put ``sha`` back; 0 once the 30 days have passed.
        ``None`` when the item's latest event is not his own removal (``removed_by_jake``)."""
        row = self.state().get(sha)
        if row is None or row["event"] != "held_aside" or row.get("reason") != "removed_by_jake":
            return None
        try:
            removed = datetime.fromisoformat(str(row.get("added_at")))
        except ValueError:
            return 0  # an unreadable removal time proves nothing: the window counts as closed
        if removed.tzinfo is None:
            return 0
        left = removed + timedelta(days=ADD_BACK_DAYS) - (now or datetime.now(timezone.utc))
        if left <= timedelta(0):
            return 0
        return -(-int(left.total_seconds()) // 86400)

    def add_back(self, sha: str, by: str, gate: Gate | None = None, now: datetime | None = None) -> str:
        """Put an item Jake removed back into ``approved\\`` by his own click, within 30 days of his removal.

        The held-aside copy itself moves back (no second copy is made), after its sha256 and its class's gate are
        checked afresh. ``by`` may not be ``auto``. Returns the warning text shown with the result.
        """
        by = _text(by, "by")
        if by == "auto":
            raise LearningFolderError("automatic adding can never put back an item Jake removed (Decision 53)")
        left = self.add_back_days_left(sha, now)
        if left is None:
            raise LearningFolderError(f"item {str(sha)[:12]} was not removed by Jake, so it cannot be put back this way")
        if left == 0:
            raise LearningFolderError(
                f"item {sha[:12]} was removed more than {ADD_BACK_DAYS} days ago; it can no longer be added back"
            )
        row = self.state()[sha]
        src = self._file("held-aside", sha)
        if _sha256(src) != sha:
            raise LearningFolderError(f"item {sha[:12]} changed on disk since it was taken out")
        gate_name = self._check(src, str(row.get("class")), str(row.get("source")), gate)
        if any(p.name.split(".")[0] == sha for p in (self.dir / "approved").iterdir()):
            raise LearningFolderError(f"approved\\ already holds a file for item {sha[:12]}")
        os.replace(src, self.dir / "approved" / src.name)
        _append(
            self.dir / MANIFEST,
            {"sha256": sha, "class": row.get("class"), "source": row.get("source"), "added_at": _now(),
             "added_by": by, "gate": gate_name, "event": "added"},
        )
        _append(self.dir / AUDIT, {"at": _now(), "by": by, "event": "added_back", "sha256": sha, "days_left": left})
        return add_back_warning(left)

    def hold_aside(self, sha: str, reason: str, by: str) -> None:
        """Move one approved item to ``held-aside\\`` (never deleted, SEC-8) and log why."""
        if reason not in HOLD_REASONS:
            raise LearningFolderError(f"reason {reason!r} is not one of {', '.join(HOLD_REASONS)}")
        by = _text(by, "by")
        row = self.state().get(sha)
        if row is None or row["event"] != "added":
            raise LearningFolderError(f"item {str(sha)[:12]} is not in approved\\")
        src = self._file("approved", sha)
        os.replace(src, self.dir / "held-aside" / src.name)
        _append(
            self.dir / MANIFEST,
            {"sha256": sha, "class": row.get("class"), "source": row.get("source"), "added_at": _now(),
             "added_by": by, "gate": row.get("gate"), "event": "held_aside", "reason": reason},
        )

    def items_for_copy(self, gate: Gate | None = None, classes: tuple[str, ...] = CLASSES) -> list[Path]:
        """Approved items of the given classes, each re-checked (sha256 + gate). Any failure stops the whole aim."""
        out = []
        for sha, row in sorted(self.state().items()):
            if row["event"] != "added" or row.get("class") not in classes:
                continue
            path = self._file("approved", sha)
            if _sha256(path) != sha:
                raise LearningFolderError(f"item {sha[:12]} changed on disk since it was added")
            self._check(path, str(row.get("class")), str(row.get("source")), gate)
            out.append(path)
        return out
