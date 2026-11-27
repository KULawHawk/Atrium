# Install-Prereqs.ps1 - Nestegg phase 1: the Windows programs the APEX suite runs on.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File Install-Prereqs.ps1            (installs)
#   powershell -NoProfile -ExecutionPolicy Bypass -File Install-Prereqs.ps1 -DryRun    (says what it would do)
#
# Parts, in order: Python 3.13 (per user, no admin), Git, GitHub CLI, Tesseract OCR, Poppler, MuPDF mutool,
# Visual C++ runtime. A part that is already present is left alone (PASS, nothing installed).
# Everything comes through winget, which checks each download against the sha256 in its
# signed package manifest; nothing is fetched from a URL this script makes up. mutool comes from the saved copy first
# (Decision 174 B: the same zip, checked against the same sha256), winget at the same pin if no copy can be read.
#
# What stays the person's own step (this script only explains and waits):
#   - every Windows security (UAC) box: Git, GitHub CLI, Tesseract and the VC++ runtime install
#     machine-wide, so Windows asks the person. This script never clicks, skips or avoids one.
#   - winget's "do you agree" question for its package sources and package licences: winget asks
#     the person in this window. -AssumeYes answers it and exists ONLY for the clean-Windows test
#     machine; "Install AdAstra.cmd" never passes it.
#   - the Tesseract setup wizard (UB Mannheim's installer): the person clicks through it. Only behind
#     -AssumeYes (the test machine) is it run silently with /S.
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

# --- Tesseract: locked to the version proven working (Jake 11/22 10:45 PM: "getting a version that we know is
# working ... always keep a copy of the last known working version, always."). Jake's PC: 5.4.0.20240606 from UB
# Mannheim's own installer. A present Tesseract of any other version is FAIL and is
# left as it is (changing it is the person's step). A missing one is installed only from the installer file whose
# sha256 was measured; until that hash is recorded below, it is FAIL "not locked", never installed unpinned.
# The installer file ships with the install bundle at <InstallRoot>\.adastra\kept\tesseract\ and stays there as the
# last known working copy. This script never downloads it.
$TessVersion = '5.4.0.20240606'
$TessSetupName = "tesseract-ocr-w64-setup-$TessVersion.exe"
# Jake 11/22 11:21 PM, Decision 17 A: the fingerprint below is written in although the publisher signature is NOT
# valid. Measured on Jake's PC 11/22: UB Mannheim's GitHub release file, 50,175,248 bytes; Microsoft's winget catalog
# lists the same InstallerSha256. Signed "Universitaet Mannheim" (GEANT Code Signing CA 4) with a certificate valid
# only 2022-12-08..2023-12-09, so expired before this 2024 build was signed (Windows: NotTimeValid, UnknownError) - a
# publisher-side lapse, not a hash mismatch. Because the signature cannot vouch for it, the kept copy is refused until
# it is shown to carry the same tesseract.exe as Jake's working install ($TessExeSha256): $TessMatchShown holds that
# evidence and stays '' until the check passes. A mismatch is a FAIL back to Jake. This script checks fingerprints,
# never the signature (a "signature must be Valid" rule would refuse this official file forever).
$TessSetupSha256 = 'c885fff6998e0608ba4bb8ab51436e1c6775c2bafc2559a19b423e18678b60c9'
$TessExeSha256 = 'babb405f4366b480d02cd8ff2bac8d497170f6c1711ce6f3d5d8bf0fb7fa6ed9'  # tesseract.exe on Jake's PC, 11/22
$TessMatchShown = 'TESS-MATCH: PASS 2026-11-22 11:23 PM CT on Jake''s PC (Check-TesseractMatch.ps1 f6efba74...ee5c): unpacked tesseract.exe 1,585,024 bytes, sha256 babb405f4366b480d02cd8ff2bac8d497170f6c1711ce6f3d5d8bf0fb7fa6ed9, nothing run'  # '' = not shown; not run
function Tesseract-Version([string]$Dir) {
    $line = Try-Cmd (Join-Path $Dir 'tesseract.exe') @('--version')
    if ($line -match 'v?(\d+\.\d+\.\d+(\.\d+)?)') { return $Matches[1] }
    return $null
}
function Check-TesseractData([string]$Dir) {
    $langs = & (Join-Path $Dir 'tesseract.exe') --list-langs 2>&1 | ForEach-Object { "$_".Trim() }
    if ($langs -contains 'eng') { Row 'PASS' 'Tesseract eng data' 'present (TableSurgeon and OcrTesseract refuse to run without it)' }
    else { Row 'FAIL' 'Tesseract eng data' 'missing: tesseract --list-langs has no eng; TableSurgeon (lens 0.2.4) and OcrTesseract refuse to run without it' }
}
function Ensure-Tesseract {
    $kept = Join-Path $InstallRoot ".adastra\kept\tesseract\$TessSetupName"
    $have = Find-Tesseract
    if ($have) {
        $v = Tesseract-Version $have
        if ($v -eq $TessVersion) { Row 'PASS' 'Tesseract OCR' "already present at the locked version $v`: $have"; $script:found['tesseract_dir'] = $have; Check-TesseractData $have }
        else { Row 'FAIL' 'Tesseract OCR' ("present at {0} ({1}), but the build is locked to {2}; left as it is (changing it is your step)" -f $(if ($v) { $v } else { 'an unreadable version' }), $have, $TessVersion) }
        return
    }
    if ($TessSetupSha256 -notmatch '^[0-9a-f]{64}$') { Row 'FAIL' 'Tesseract OCR' "not locked: the sha256 of $TessSetupName is not measured yet, so it is not installed"; return }
    if ($TessMatchShown -eq '') { Row 'FAIL' 'Tesseract OCR' "not yet shown that $TessSetupName carries the same tesseract.exe as the proven install (sha256 $TessExeSha256); its publisher signature expired in 2023, so it is not run until that match is recorded"; return }
    if ($DryRun) { Row 'TODO' 'Tesseract OCR' "would install $TessSetupName from $kept after checking sha256 $TessSetupSha256 (one Windows security box)"; return }
    if (-not (Test-Path -LiteralPath $kept)) { Row 'FAIL' 'Tesseract OCR' "the locked installer is not at $kept (it ships with the install bundle; this script never downloads by itself)"; return }
    $got = (Get-FileHash -LiteralPath $kept -Algorithm SHA256).Hash.ToLower()
    if ($got -ne $TessSetupSha256) { Row 'FAIL' 'Tesseract OCR' "kept installer's sha256 $got is not the measured $TessSetupSha256; not run"; return }
    Say ("....  {0,-20} running {1} (sha256 checked; one Windows security box)" -f 'Tesseract OCR', $TessSetupName)
    if ($AssumeYes) { $proc = Start-Process -FilePath $kept -ArgumentList '/S' -Wait -PassThru }  # test machine only
    else { $proc = Start-Process -FilePath $kept -Wait -PassThru }  # the person clicks through the setup wizard
    Refresh-Path
    $have = Find-Tesseract
    $v = if ($have) { Tesseract-Version $have } else { $null }
    if ($v -eq $TessVersion) {
        $exe = (Get-FileHash -LiteralPath (Join-Path $have 'tesseract.exe') -Algorithm SHA256).Hash.ToLower()
        if ($exe -ne $TessExeSha256) { Row 'FAIL' 'Tesseract OCR' "installed, but tesseract.exe sha256 $exe is not the proven $TessExeSha256; left as it is, for Jake"; return }
        Row 'PASS' 'Tesseract OCR' "installed $v`: $have (tesseract.exe matches the proven build; installer kept at $kept)"; $script:found['tesseract_dir'] = $have; Check-TesseractData $have
    }
    else { Row 'FAIL' 'Tesseract OCR' ("not at {0} after the installer (exit code {1}, found {2}). If the Windows security box was declined, run this again and choose Yes." -f $TessVersion, $proc.ExitCode, $(if ($v) { $v } else { 'nothing' })) }
}

# --- MuPDF mutool: from the saved copy first (Jake 7:53 PM CT 11/26, Decision 174 B: "we always back up our
# functionality ... and all components"). The Hierarchy reader and the printed-text check accept ONLY 1.23.0. The
# zip winget's signed manifest names for 1.23.0 is kept in the private saved-copies release programs-v1 (and the
# home copy pulled from it) under its sha256; it is unpacked into this installer's own folder
# %LOCALAPPDATA%\AdAstra\tools\mupdf-1.23.0 (never over an existing file). If no saved copy can be read, winget
# installs the same pinned version. A mutool on PATH at another version is left as it is (yours), and is not used.
$MutoolVersion = '1.23.0'
$MutoolZipName = 'mupdf-1.23.0-windows.zip'
$MutoolZipRoot = 'mupdf-1.23.0-windows'
$MutoolZipSha256 = '702386666f0d5a7d968102759843509c2549c1a206489add6cd284f657393ff8'  # = programs_pinned.json mutool.sha256
$MutoolDir = Join-Path $env:LOCALAPPDATA "AdAstra\tools\mupdf-$MutoolVersion"
function Mutool-Version([string]$Dir) {
    $exe = Join-Path $Dir 'mutool.exe'
    if (-not (Test-Path -LiteralPath $exe)) { return $null }
    try { $o = (& $exe -v 2>&1 | ForEach-Object { "$_" }) -join ' ' } catch { return $null }
    if ($o -match 'mutool version (\d+\.\d+\.\d+)') { return $Matches[1] }
    return $null
}
function Expand-MutoolZip([string]$Zip, [string]$To) {
    # Unpacks <zip_root>/... into $To, refusing any entry that would land outside it; never overwrites a file.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $z = [IO.Compression.ZipFile]::OpenRead($Zip)
    try {
        $full = [IO.Path]::GetFullPath($To).TrimEnd('\') + '\'
        foreach ($e in $z.Entries) {
            $rel = $e.FullName -replace '/', '\'
            if (-not $rel.StartsWith("$MutoolZipRoot\")) { throw "unexpected entry $($e.FullName) (not under $MutoolZipRoot/)" }
            $rel = $rel.Substring($MutoolZipRoot.Length + 1)
            if (-not $rel) { continue }
            $dest = [IO.Path]::GetFullPath((Join-Path $To $rel))
            if (-not $dest.StartsWith($full)) { throw "entry $($e.FullName) would land outside $To" }
            if ($rel.EndsWith('\')) { New-Item -ItemType Directory -Force -Path $dest | Out-Null; continue }
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
            [IO.Compression.ZipFileExtensions]::ExtractToFile($e, $dest, $false)
        }
    } finally { $z.Dispose() }
}
function Ensure-Mutool {
    $v = Mutool-Version $MutoolDir
    if ($v -eq $MutoolVersion) { Row 'PASS' 'MuPDF mutool' "saved copy already in place at the locked version $v`: $MutoolDir"; $script:found['mutool_dir'] = $MutoolDir; return }
    if (Test-Path -LiteralPath $MutoolDir) { Row 'FAIL' 'MuPDF mutool' ("{0} exists but does not hold mutool {1} (found {2}); left as it is" -f $MutoolDir, $MutoolVersion, $(if ($v) { $v } else { 'nothing runnable' })); return }
    $other = Find-Mutool
    $ov = if ($other) { Mutool-Version $other } else { $null }
    if ($ov -eq $MutoolVersion) { Row 'PASS' 'MuPDF mutool' "already present at the locked version $ov`: $other"; $script:found['mutool_dir'] = $other; return }
    if ($other) { Say ("....  {0,-20} a mutool at {1} is on this PC ({2}); it is left as it is and not used" -f 'MuPDF mutool', $(if ($ov) { $ov } else { 'an unreadable version' }), $other) }
    if ($DryRun) { Row 'TODO' 'MuPDF mutool' "would take $MutoolZipName (sha256 $MutoolZipSha256) from the saved copies and unpack it to $MutoolDir; winget $MutoolVersion if no saved copy can be read"; return }
    $zip = Join-Path $InstallRoot ".adastra\kept\mupdf\$MutoolZipName"
    $py = Get-Command py -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath $zip) -and $py) {
        Say ("....  {0,-20} looking for {1} in the saved copies (home copy, then your private release)" -f 'MuPDF mutool', $MutoolZipName)
        & py -3.13 -I (Join-Path $PSScriptRoot 'saved_copies.py') fetch $MutoolZipSha256 $zip --name $MutoolZipName --root $InstallRoot 2>&1 | ForEach-Object { Say ("      " + $_) }
    }
    if (Test-Path -LiteralPath $zip) {
        $got = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLower()
        if ($got -ne $MutoolZipSha256) { Row 'FAIL' 'MuPDF mutool' "$zip has sha256 $got, not the pinned $MutoolZipSha256; not used, left as it is"; return }
        # Unpacked into a new sibling working folder, checked there, then renamed into place: a cut-off unpack never
        # leaves a half-filled mupdf-1.23.0 behind (reviewer 3 on #114). A failed working folder is left, never deleted.
        $work = "$MutoolDir.unpack-$stamp"
        try { Expand-MutoolZip $zip $work } catch { Row 'FAIL' 'MuPDF mutool' "could not unpack $zip to $work`: $($_.Exception.Message) (that working folder is left as it is; the next run uses a new one)"; return }
        $v = Mutool-Version $work
        if ($v -ne $MutoolVersion) { Row 'FAIL' 'MuPDF mutool' ("unpacked to {0}, but it reports {1}, not {2}; left as it is, not used" -f $work, $(if ($v) { $v } else { 'no version' }), $MutoolVersion); return }
        try { Rename-Item -LiteralPath $work -NewName (Split-Path -Leaf $MutoolDir) -ErrorAction Stop } catch { Row 'FAIL' 'MuPDF mutool' "checked in $work but could not rename it to $MutoolDir`: $($_.Exception.Message)"; return }
        Row 'PASS' 'MuPDF mutool' "installed $v from the saved copy (sha256 checked, unpacked, version read, then put in place): $MutoolDir"; $script:found['mutool_dir'] = $MutoolDir
        return
    }
    Say ("....  {0,-20} no saved copy could be read; installing through winget at the same pinned version" -f 'MuPDF mutool')
    Ensure 'MuPDF mutool' ${function:Find-MutoolLocked} 'ArtifexSoftware.mutool' '1.23.0' @() '(Hierarchy reader)' 'mutool_dir'  # = $MutoolVersion; written out so CI's winget check reads it
}
function Find-MutoolLocked {
    # after winget: only a mutool that reports the locked version counts
    $d = Find-Mutool
    if ($d -and (Mutool-Version $d) -eq $MutoolVersion) { return $d }
    $hit = Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages\ArtifexSoftware.mutool*') -Recurse -Filter 'mutool.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($hit -and (Mutool-Version $hit.DirectoryName) -eq $MutoolVersion) { return $hit.DirectoryName }
    return $null
}

Say ("Nestegg phase 1 (prerequisites) {0}  install folder: {1}{2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm'), $InstallRoot, $(if ($DryRun) { '  [DRY RUN: nothing installed]' } else { '' }))

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Row 'FAIL' 'winget' 'not found. Install "App Installer" from the Microsoft Store (the person''s own step), then run this again.'
} else {
    # Versions: Poppler and mutool as on Jake's working PC (read 11/22/2026); the rest as found working on the GitHub
    # Windows runner 11/21-22/2026. Tesseract: see Ensure-Tesseract above. CI checks winget still offers
    # each one ('winget show --version'). '' = not measured yet, so that program is never installed by this script.
    Ensure 'Python 3.13'      ${function:Find-Python}    'Python.Python.3.13'           '3.13.17'         @('--scope', 'user') '(per user, no Windows security box)' 'python'
    Ensure 'Python 3.12'      ${function:Find-Python312} 'Python.Python.3.12'           '3.12.10'         @('--scope', 'user') '(per user; HtrLens, MinerU and Paddle need it)' 'python312'
    Ensure 'Git'              ${function:Find-Git}       'Git.Git'                      '2.56.1'        @()                  '(one Windows security box)'          'git'
    Ensure 'GitHub CLI'       ${function:Find-Gh}        'GitHub.cli'                   '2.104.0'       @()                  '(one Windows security box)'          'gh'
    Ensure-Tesseract  # locked to 5.4.0.20240606 from UB Mannheim's own installer at a measured sha256 (Jake 11/22 10:45 PM)
    Ensure 'Poppler'          ${function:Find-Poppler}   'oschwartz10612.Poppler'       '25.07.0-0'     @('--scope', 'user') '(per user, no Windows security box)' 'poppler_bin'
    Ensure-Mutool  # locked to 1.23.0, from the saved copy first, winget at the same pin as the fallback (Decision 174 B)
    Ensure 'VC++ runtime x64' ${function:Find-VC}        'Microsoft.VCRedist.2015+.x64' '14.52.37029.0' @()                  '(one Windows security box)'          'vcredist'
}

# The mutool this script chose comes first on PATH for THIS window and the install steps it starts (never a permanent
# PATH change), so a different mutool elsewhere on PATH cannot shadow it. Later runs read mutool_dir in prereqs.json.
if ($script:found['mutool_dir']) { $env:Path = "$($script:found['mutool_dir']);$env:Path" }

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
