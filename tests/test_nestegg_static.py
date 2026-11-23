"""Static guards for tools/nestegg (Nestegg phase 0 is READ-ONLY by promise).

PowerShell does not run in CI, so these tests read the script text and hold it to
what its header promises: it installs nothing, changes no Windows setting, deletes
nothing, reads no secret, and always ends on one PASS/GAPS line.
"""

from __future__ import annotations

import re
from pathlib import Path

NESTEGG = Path(__file__).resolve().parents[1] / "tools" / "nestegg"
CHECK = NESTEGG / "Check-AdAstra.ps1"
CMD = NESTEGG / "Check AdAstra.cmd"

FORBIDDEN = {
    "deletes": r"\b(Remove-Item|rm|del|rmdir|rd|Clear-Content)\b",
    "installs": r"\b(winget\s+install|pip\s+install|Install-Package|Install-Module|msiexec|Start-Process)\b",
    "changes settings": r"\b(setx|Set-ItemProperty|New-ItemProperty|reg\s+add|Set-ExecutionPolicy|Enable-WindowsOptionalFeature|Set-Service)\b",
    "elevates": r"(-Verb\s+RunAs|runas\.exe)",
    "runs remote code": r"\b(Invoke-Expression|iex|DownloadString|Invoke-RestMethod)\b",
    "reads secrets": r"(ANTHROPIC_API_KEY|RUNPOD_API_KEY|Get-StoredCredential|CredRead|cmdkey|ConvertFrom-SecureString)",
}


def _code_lines(path: Path) -> list[str]:
    out = []
    for ln in path.read_text(encoding="ascii").splitlines():
        s = ln.strip()
        if s.startswith("#") or s.lower().startswith("rem "):
            continue
        out.append(ln)
    return out


def test_files_exist_and_are_ascii() -> None:
    # Windows PowerShell 5.1 misreads a BOM-less UTF-8 script; ASCII avoids that class.
    for p in (CHECK, CMD, NESTEGG / "README.md"):
        assert p.is_file(), p
    CHECK.read_text(encoding="ascii")
    CMD.read_text(encoding="ascii")


def test_check_script_is_read_only() -> None:
    code = "\n".join(_code_lines(CHECK))
    hits = {why: re.findall(pat, code, flags=re.IGNORECASE) for why, pat in FORBIDDEN.items()}
    assert {k: v for k, v in hits.items() if v} == {}


def test_only_write_is_its_own_report() -> None:
    code = "\n".join(_code_lines(CHECK))
    writes = re.findall(r"\b(Set-Content|Out-File|Add-Content|New-Item|Copy-Item|Move-Item)\b", code, flags=re.I)
    assert writes == ["Set-Content"]
    assert re.search(r"Set-Content -LiteralPath \$out\b", code)
    assert re.search(r"\$out = Join-Path \$dir \('nestegg_check_", code)


def test_network_is_head_only() -> None:
    code = "\n".join(_code_lines(CHECK))
    calls = re.findall(r"Invoke-WebRequest[^\n]*", code)
    assert calls and all("-Method Head" in c for c in calls)


def test_ends_on_one_verdict_line() -> None:
    code = CHECK.read_text(encoding="ascii")
    assert "'NESTEGG-CHECK: PASS'" in code
    assert '"NESTEGG-CHECK: GAPS $($script:gaps)"' in code
    assert code.rstrip().endswith("Write-Host $final")


def test_cmd_runs_the_check_beside_it() -> None:
    text = CMD.read_text(encoding="ascii")
    assert '"%~dp0Check-AdAstra.ps1"' in text
    assert b"\r\n" in CMD.read_bytes()  # cmd.exe files keep CRLF


# --- Phase 1: Install-Prereqs.ps1 -------------------------------------------------------------
PREREQS = NESTEGG / "Install-Prereqs.ps1"

PHASE1_FORBIDDEN = {k: v for k, v in FORBIDDEN.items() if k != "installs"}
PHASE1_FORBIDDEN["downloads by itself"] = r"\b(Invoke-WebRequest|Start-BitsTransfer|curl|wget|DownloadFile)\b"
PHASE1_FORBIDDEN["writes PATH permanently"] = r"SetEnvironmentVariable"


def test_prereqs_is_ascii_and_never_deletes_or_changes_settings() -> None:
    PREREQS.read_text(encoding="ascii")
    code = "\n".join(_code_lines(PREREQS))
    hits = {why: re.findall(pat, code, flags=re.IGNORECASE) for why, pat in PHASE1_FORBIDDEN.items()}
    assert {k: v for k, v in hits.items() if v} == {}


def test_prereqs_installs_only_through_winget_with_exact_ids() -> None:
    code = "\n".join(_code_lines(PREREQS))
    assert "@('install', '--id', $WingetId, '--exact', '--version', $Version, '--source', 'winget')" in code
    assert "if (-not $Version) { Row 'FAIL' $Name (\"not locked:" in code
    rows = re.findall(r"^\s*Ensure '[^']+'\s+\$\{function:Find-\w+\}\s+'([^']+)'\s+'([^']*)'", code, flags=re.M)
    ids = [i for i, _ in rows]
    assert dict(rows)["ArtifexSoftware.mutool"] == "1.23.0"
    assert ids == [
        "Python.Python.3.13",
        "Python.Python.3.12",
        "Git.Git",
        "GitHub.cli",
        "oschwartz10612.Poppler",
        "ArtifexSoftware.mutool",
        "Microsoft.VCRedist.2015+.x64",
    ]


def test_agreements_are_answered_only_behind_assume_yes() -> None:
    code = "\n".join(_code_lines(PREREQS))
    lines = [ln for ln in code.splitlines() if "accept-package-agreements" in ln or "accept-source-agreements" in ln]
    assert len(lines) == 1 and lines[0].strip().startswith("if ($AssumeYes)")
    for f in NESTEGG.glob("*.cmd"):
        assert "AssumeYes" not in f.read_text(encoding="ascii"), f


def test_dry_run_writes_nothing() -> None:
    code = PREREQS.read_text(encoding="ascii")
    # Every write (log folder, log lines, prereqs.json) sits behind "if (-not $DryRun)" or the
    # log path, which is only set inside that block; the installer call returns early on DryRun.
    assert code.count("if (-not $DryRun) {") == 2
    assert "if ($DryRun) { Row 'TODO'" in code
    assert code.index("$script:log = Join-Path $logDir") > code.index("if (-not $DryRun) {")


def test_prereqs_ends_on_one_verdict_line() -> None:
    code = PREREQS.read_text(encoding="ascii")
    assert "'NESTEGG-PREREQS: PASS'" in code
    assert '"NESTEGG-PREREQS: FAIL $($script:fails)"' in code
    assert code.rstrip().endswith("Say $final")


def test_no_double_quotes_inside_python_dash_c_text():
    """Windows PowerShell 5.1 strips embedded double quotes when calling a program,
    so a -c text with them becomes a Python syntax error (clean-Windows run 4)."""
    import re
    for name in ("Check-AdAstra.ps1", "Install-Prereqs.ps1"):
        text = (NESTEGG / name).read_text(encoding="utf-8")
        for m in re.finditer(r"'-c',\s*'([^']|'')*'", text):
            assert '"' not in m.group(0), (name, m.group(0))


def test_tesseract_is_locked_to_the_proven_version_and_never_downloaded() -> None:
    """Jake 11/22 10:45 PM: a version known to work, always keep the last known working copy. Tesseract
    5.4.0.20240606 (his PC) from UB Mannheim's own installer at a measured sha256, kept with the bundle."""
    code = "\n".join(_code_lines(PREREQS))
    assert "$TessVersion = '5.4.0.20240606'" in code
    assert re.search(r"^\s*Ensure-Tesseract\b", code, flags=re.M)
    assert "if ($v -eq $TessVersion)" in code and "left as it is" in code  # other versions FAIL, never changed
    assert "if ($TessSetupSha256 -notmatch '^[0-9a-f]{64}$')" in code and "not locked:" in code
    assert code.index("Get-FileHash -LiteralPath $kept") < code.index("Start-Process -FilePath $kept")
    assert "Check-TesseractData" in code and "--list-langs" in code and "'eng'" in code
