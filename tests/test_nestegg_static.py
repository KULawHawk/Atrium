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
