"""Guards for tools/nestegg/htrlens_models.py (Jake 11/21: every install includes the
HtrLens model files; a missing or changed file fails loudly, never silently)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

NESTEGG = Path(__file__).resolve().parents[1] / "tools" / "nestegg"
SCRIPT = NESTEGG / "htrlens_models.py"
MANIFEST = NESTEGG / "htrlens_models.json"


def _mod():
    spec = importlib.util.spec_from_file_location("htrlens_models", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_manifest_pins_are_well_formed() -> None:
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert re.fullmatch(r"[0-9a-f]{64}", man["kraken"]["sha256"])
    assert man["kraken"]["cache_name"] == man["kraken"]["doi"].replace("/", "_")
    t = man["trocr"]
    assert re.fullmatch(r"[0-9a-f]{40}", t["revision"]), "TrOCR must be pinned to a commit, not a branch"
    assert t["license_expected"] == "mit"
    assert "model.safetensors" in t["files"]
    for name, f in t["files"].items():
        assert isinstance(f["bytes"], int) and f["bytes"] > 0, name
        assert f["sha256"] is None or re.fullmatch(r"[0-9a-f]{64}", f["sha256"]), name


def test_check_file_fails_loudly_on_every_mismatch(tmp_path: Path, capsys) -> None:
    m = _mod()
    f = tmp_path / "w.bin"
    f.write_bytes(b"weights")
    good = hashlib.sha256(b"weights").hexdigest()
    rep = m.Report()
    assert not m.check_file(rep, "absent", tmp_path / "nope.bin", good, 7)
    assert not m.check_file(rep, "size", f, good, 8)
    assert not m.check_file(rep, "no pin", f, None, 7)
    assert not m.check_file(rep, "wrong sha", f, "0" * 64, 7)
    assert rep.fails == 4
    assert m.check_file(rep, "right", f, good, 7)
    assert rep.fails == 4
    assert rep.final() == 1
    out = capsys.readouterr().out
    assert sum(ln.startswith("FAIL ") for ln in out.splitlines()) == 4 and out.rstrip().endswith("NESTEGG-HTRLENS: FAIL 4")


def test_dry_run_writes_nothing_and_passes(tmp_path: Path, monkeypatch, capsys) -> None:
    before = sorted(p.name for p in NESTEGG.iterdir())
    monkeypatch.chdir(tmp_path)
    assert _mod().main(["--dry-run"]) == 0
    assert sorted(p.name for p in NESTEGG.iterdir()) == before
    assert list(tmp_path.iterdir()) == []
    assert capsys.readouterr().out.rstrip().endswith("NESTEGG-HTRLENS: PASS")


def test_measure_mode_can_never_pass() -> None:
    src = SCRIPT.read_text(encoding="utf-8")
    assert '"measure mode only prints hashes; it never verifies"' in src
    assert 'rep.row("FAIL", "TrOCR files"' in src


def test_no_secret_reads_or_settings_changes() -> None:
    src = SCRIPT.read_text(encoding="utf-8")
    for bad in ("ANTHROPIC_API_KEY", "RUNPOD_API_KEY", "keyring", "CredRead", "HF_TOKEN", "setx", "winreg",
                "os.environ[\"PATH\"]", "trust_remote_code"):
        assert bad not in src, bad
    # the offline switch is set only in the child process's own copy of the environment
    assert "dict(os.environ, HF_HUB_OFFLINE=\"1\"" in src
    assert "os.environ[\"HF_HUB_OFFLINE\"]" not in src
