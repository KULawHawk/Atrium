# Install-Prereqs.ps1 - Nestegg phase 1: the Windows programs the APEX suite runs on.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File Install-Prereqs.ps1            (installs)
#   powershell -NoProfile -ExecutionPolicy Bypass -File Install-Prereqs.ps1 -DryRun    (says what it would do)
#
# Parts, in order: Python 3.13 (per user, no admin), Git, GitHub CLI, Tesseract OCR, Poppler,
# Visual C++ runtime. A part that is already present is left alone (PASS, nothing installed).
# Everything comes through winget, which checks each download against the sha256 in its
# signed package manifest; nothing is fetched from a URL this script makes up.
#
# What stays the person's own step (this script only explains and waits):
#   - every Windows security (UAC) box: Git, GitHub CLI, Tesseract and the VC++ runtime install
#     machine-wide, so Windows asks the person. This script never clicks, skips or avoids one.
#   - winget's "do you agree" question for its package sources and package licences: winget asks
#     the person in this window. -AssumeYes answers it and exists ONLY for the clean-Windows test
#     machine; "Install AdAstra.cmd" never passes it.
# It never deletes anything, never changes a Windows setting (no permanent PATH or environment
# change: winget's own installers manage their PATH entries), and never reads a key or secret.
# Log: <InstallRoot>\.adastra\install_log\prereqs_<timestamp>.log, written line by line.
# Paths it found: <InstallRoot>\.adastra\prereqs.json (read by later phases).
# Last line: NESTEGG-PREREQS: PASS   or   NESTEGG-PREREQS: FAIL n   (never a silent pass).

param(
    [string]$InstallRoot = (Join-Path $env:USERPROFILE 'AdAstra'),
    [switch]$DryRun,
    [switch]$AssumeYes
)

$ErrorActionPreference = 'Continue'
$script:fails = 0
$script:found = [ordered]@{}
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$script:log = $null

if (-not $DryRun) {
    $logDir = Join-Path $InstallRoot '.adastra\install_log'
    try {
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
        $script:log = Join-Path $logDir ("prereqs_{0}.log" -f $stamp)
    } catch { Write-Host "log folder could not be made at $logDir ($($_.Exception.Message)); continuing without a log file" }
}

function Say([string]$Text) {
    Write-Host $Text
    if ($script:log) { try { Add-Content -LiteralPath $script:log -Value $Text -Encoding UTF8 } catch { } }
}

function Row([string]$Status, [string]$What, [string]$Detail) {
    if ($Status -eq 'FAIL') { $script:fails++ }
    Say ('{0,-5} {1,-20} {2}' -f $Status, $What, $Detail)
}

function Refresh-Path {
    # Picks up PATH entries a winget installer just added, for THIS window only (read-only:
    # reads the stored Machine and User PATH; writes nothing back).
    $m = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $u = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = (@($m, $u) | Where-Object { $_ }) -join ';'
}

function Try-Cmd([string]$Exe, [string[]]$CmdArgs) {
    try {
        $o = & $Exe @CmdArgs 2>$null
        if ($LASTEXITCODE -eq 0 -and $o) { return (($o | Select-Object -First 1) -as [string]).Trim() }
    } catch { }
    return $null
}

# --- Detectors: each returns a path or version string, or $null --------------------------------
function Find-PythonVer([string]$Want) {
    # $Want is '3.13' or '3.12'. Some readers (HtrLens/kraken, MinerU, Paddle) refuse 3.13.
    $cands = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $p = Try-Cmd 'py' @("-$Want", '-c', 'import sys; print(sys.executable)')
        if ($p) { $cands += $p }
    }
    $cands += (Join-Path $env:LOCALAPPDATA ('Programs\Python\Python{0}\python.exe' -f $Want.Replace('.', '')))
    foreach ($c in $cands) {
        if ($c -and (Test-Path -LiteralPath $c)) {
            # No double quotes inside the -c text: Windows PowerShell 5.1 strips them when it calls a
            # program, which turned the old check into a Python syntax error (clean-Windows run 4).
            $v = Try-Cmd $c @('-c', 'import sys; print(''.''.join(map(str, sys.version_info[:3])))')
            if ($v -and $v.StartsWith("$Want.")) { return "$c ($v)" }
        }
    }
    return $null
}
function Find-Python { return (Find-PythonVer '3.13') }
function Find-Python312 { return (Find-PythonVer '3.12') }
function Find-Git { $v = Try-Cmd 'git' @('--version'); if ($v) { return $v }; return $null }
function Find-Gh {
    $v = Try-Cmd 'gh' @('--version'); if ($v) { return $v }
    $c = Join-Path $env:ProgramFiles 'GitHub CLI\gh.exe'
    if (Test-Path -LiteralPath $c) { return $c }
    return $null
}
function Find-Tesseract {
    $d = $env:CONCLAVE_TESSERACT_DIR
    if (-not $d) { $d = Join-Path $env:ProgramFiles 'Tesseract-OCR' }
    $exe = Join-Path $d 'tesseract.exe'
    if (Test-Path -LiteralPath $exe) { return $d }
    $g = Get-Command tesseract -ErrorAction SilentlyContinue
    if ($g) { return (Split-Path -Parent $g.Source) }
    return $null
}
function Find-Poppler {
    foreach ($c in @($env:CONCLAVE_POPPLER_BIN, $env:CONCLAVE_POPPLER_DIR)) {
        if ($c -and (Test-Path -LiteralPath (Join-Path $c 'pdftoppm.exe'))) { return $c }
    }
    $g = Get-Command pdftoppm -ErrorAction SilentlyContinue
    if ($g) { return (Split-Path -Parent $g.Source) }
    $roots = @('C:\poppler*', (Join-Path $env:ProgramFiles 'poppler*'),
               (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages\oschwartz10612.Poppler*'))
    foreach ($r in $roots) {
        $hit = Get-ChildItem -Path $r -Recurse -Filter 'pdftoppm.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($hit) { return $hit.DirectoryName }
    }
    return $null
}
function Find-Mutool {
    $g = Get-Command mutool -ErrorAction SilentlyContinue
    if ($g) { return (Split-Path -Parent $g.Source) }
    $roots = @((Join-Path $env:ProgramFiles 'MuPDF*'), (Join-Path $env:ProgramFiles 'Artifex*'),
               (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages\ArtifexSoftware.*'))
    foreach ($r in $roots) {
        $hit = Get-ChildItem -Path $r -Recurse -Filter 'mutool.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($hit) { return $hit.DirectoryName }
    }
    return $null
}
function Find-VC {
    foreach ($k in @('HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64',
                     'HKLM:\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\X64')) {
        $vc = Get-ItemProperty $k -ErrorAction SilentlyContinue
        if ($vc -and $vc.Installed -eq 1) { return $vc.Version }
    }
    return $null
}

# --- One part: detect, install through winget if missing, detect again -------------------------
# Every install is pinned to one measured version (--version). A program with no measured version
# yet is FAIL "not locked" when it would have to be installed, and is never installed unpinned.
function Ensure([string]$Name, [scriptblock]$Find, [string]$WingetId, [string]$Version, [string[]]$Extra, [string]$Note, [string]$Key) {
    $have = & $Find
    if ($have) { Row 'PASS' $Name "already present: $have"; $script:found[$Key] = $have; return }
    if (-not $Version) { Row 'FAIL' $Name ("not locked: no measured version of winget package {0} yet, so it is not installed" -f $WingetId); return }
    if ($DryRun) { Row 'TODO' $Name ("would install winget package {0} {1} {2}" -f $WingetId, $Version, $Note); return }
    Say ("....  {0,-20} installing winget package {1} {2} {3}" -f $Name, $WingetId, $Version, $Note)
    $a = @('install', '--id', $WingetId, '--exact', '--version', $Version, '--source', 'winget') + $Extra
    if ($AssumeYes) { $a += @('--accept-source-agreements', '--accept-package-agreements', '--disable-interactivity') }
    & winget @a 2>&1 | ForEach-Object { Say ("      " + $_) }
    $rc = $LASTEXITCODE
    Refresh-Path
    $have = & $Find
    if ($have) { Row 'PASS' $Name "installed: $have"; $script:found[$Key] = $have }
    else { Row 'FAIL' $Name ("not found after winget (exit code {0}). If a Windows security box was declined, run this again and choose Yes." -f $rc) }
}

Say ("Nestegg phase 1 (prerequisites) {0}  install folder: {1}{2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm'), $InstallRoot, $(if ($DryRun) { '  [DRY RUN: nothing installed]' } else { '' }))

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Row 'FAIL' 'winget' 'not found. Install "App Installer" from the Microsoft Store (the person''s own step), then run this again.'
} else {
    # Versions: the ones found working on the GitHub Windows runner 11/21-22/2026; CI checks winget still offers
    # each one ('winget show --version'). '' = not measured yet, so that program is never installed by this script.
    Ensure 'Python 3.13'      ${function:Find-Python}    'Python.Python.3.13'           '3.13.17'         @('--scope', 'user') '(per user, no Windows security box)' 'python'
    Ensure 'Python 3.12'      ${function:Find-Python312} 'Python.Python.3.12'           '3.12.10'         @('--scope', 'user') '(per user; HtrLens, MinerU and Paddle need it)' 'python312'
    Ensure 'Git'              ${function:Find-Git}       'Git.Git'                      '2.56.1'        @()                  '(one Windows security box)'          'git'
    Ensure 'GitHub CLI'       ${function:Find-Gh}        'GitHub.cli'                   '2.104.0'       @()                  '(one Windows security box)'          'gh'
    Ensure 'Tesseract OCR'    ${function:Find-Tesseract} 'UB-Mannheim.TesseractOCR'     ''              @()                  '(one Windows security box)'          'tesseract_dir'
    Ensure 'Poppler'          ${function:Find-Poppler}   'oschwartz10612.Poppler'       '26.09.0'       @('--scope', 'user') '(per user, no Windows security box)' 'poppler_bin'
    Ensure 'MuPDF mutool'     ${function:Find-Mutool}    'ArtifexSoftware.mutool'       '1.28.5'        @()                  '(Hierarchy reader)'                   'mutool_dir'
    Ensure 'VC++ runtime x64' ${function:Find-VC}        'Microsoft.VCRedist.2015+.x64' '14.52.37029.0' @()                  '(one Windows security box)'          'vcredist'
}

if (-not $DryRun) {
    $out = Join-Path $InstallRoot '.adastra\prereqs.json'
    try {
        $obj = [ordered]@{ written = (Get-Date -Format 'o'); fails = $script:fails; found = $script:found }
        Set-Content -LiteralPath $out -Value ($obj | ConvertTo-Json -Depth 3) -Encoding UTF8
        Say "paths recorded: $out"
    } catch { Say "paths not recorded: $($_.Exception.Message)" }
    if ($script:log) { Say "log: $($script:log)" }
}

$final = if ($script:fails -eq 0) { 'NESTEGG-PREREQS: PASS' } else { "NESTEGG-PREREQS: FAIL $($script:fails)" }
Say $final
