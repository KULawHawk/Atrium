# Check-AdAstra.ps1 - Nestegg phase 0: READ-ONLY readiness check for installing the APEX suite
# on a Windows PC. It is also the installer's -DryRun. It installs nothing, changes no Windows
# setting, deletes nothing, reads no key or secret, and writes only its own report file.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File Check-AdAstra.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File Check-AdAstra.ps1 -InstallRoot "D:\AdAstra"
#
# Each line is   PASS | GAP | INFO   <what>   <detail>.
#   PASS  present and usable.
#   GAP   missing or unusable; the installer would fix it (and says whether that needs the
#         person's own step, such as a Windows security box or a sign-in).
#   INFO  reported only (for example: no NVIDIA card means model readers use the CPU or the pod).
# Last line: NESTEGG-CHECK: PASS (no GAP)  or  NESTEGG-CHECK: GAPS n  (never a silent pass).
# Report: <InstallRoot>\.adastra\check_<timestamp>.txt if that folder exists, else %TEMP%.
# Plan: project share installer/PLAN_installer_2026-11-20.md (defaults I3/I4/I5 = A).

param(
    [string]$InstallRoot = (Join-Path $env:USERPROFILE 'AdAstra'),
    [int]$MinFreeGB = 20
)

$ErrorActionPreference = 'Continue'
$script:lines = @()
$script:gaps = 0

function Row([string]$Status, [string]$What, [string]$Detail) {
    if ($Status -eq 'GAP') { $script:gaps++ }
    $t = '{0,-5} {1,-28} {2}' -f $Status, $What, $Detail
    $script:lines += $t
    Write-Host $t
}

function Try-Cmd([string]$Exe, [string[]]$CmdArgs) {
    # Runs a read-only version query; returns trimmed first line or $null.
    try {
        $o = & $Exe @CmdArgs 2>$null
        if ($LASTEXITCODE -eq 0 -and $o) { return (($o | Select-Object -First 1) -as [string]).Trim() }
    } catch { }
    return $null
}

# --- Windows ---------------------------------------------------------------------------------
try {
    $os = Get-CimInstance Win32_OperatingSystem
    $build = [int]$os.BuildNumber
    if ($build -ge 22000) { Row 'PASS' 'Windows' "$($os.Caption) build $build" }
    elseif ($build -ge 19041) { Row 'INFO' 'Windows' "$($os.Caption) build $build (Windows 10; supported but untested)" }
    else { Row 'GAP' 'Windows' "$($os.Caption) build $build is older than Windows 10 2004" }
    if ($os.OSArchitecture -notmatch '64') { Row 'GAP' 'Architecture' "$($os.OSArchitecture) (64-bit required)" }
} catch { Row 'GAP' 'Windows' 'could not read the Windows version' }

# --- Account and UAC (read only; nothing is changed) --------------------------------------------
try {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    # WindowsIdentity.Groups leaves out a deny-only SID, and an unelevated administrator's
    # token carries Administrators (S-1-5-32-544) as deny-only, so ask whoami instead.
    $isAdminGroup = $false
    try { $isAdminGroup = [bool]((& whoami /groups /fo csv 2>$null) -match 'S-1-5-32-544') } catch { }
    $elevated = (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    Row 'INFO' 'Account' ("administrator group: {0}; this window elevated: {1}" -f $isAdminGroup, $elevated)
    if ($elevated) { Row 'INFO' 'Elevation' 'this check does not need admin; the installer runs as the normal user' }
    $uac = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' -ErrorAction SilentlyContinue
    if ($uac) { Row 'INFO' 'UAC' ("EnableLUA={0} ConsentPromptBehaviorAdmin={1} PromptOnSecureDesktop={2}" -f $uac.EnableLUA, $uac.ConsentPromptBehaviorAdmin, $uac.PromptOnSecureDesktop) }
} catch { Row 'INFO' 'Account' 'could not read account details' }

# --- Disk ------------------------------------------------------------------------------------
try {
    $qual = Split-Path -Qualifier $InstallRoot
    $d = Get-CimInstance Win32_LogicalDisk -Filter ("DeviceID='{0}'" -f $qual)
    $free = [math]::Round($d.FreeSpace / 1GB, 1)
    if ($free -ge $MinFreeGB) { Row 'PASS' 'Disk space' "$free GB free on $qual (core needs about 5 GB; each model reader 1-16 GB more)" }
    else { Row 'GAP' 'Disk space' "$free GB free on $qual; at least $MinFreeGB GB recommended" }
} catch { Row 'INFO' 'Disk space' "could not read free space for $InstallRoot" }

# --- Install folder --------------------------------------------------------------------------
if (Test-Path -LiteralPath $InstallRoot) {
    $inv = Join-Path $InstallRoot '.adastra\install_inventory.json'
    if (Test-Path -LiteralPath $inv) { Row 'INFO' 'Install folder' "$InstallRoot already holds an install (inventory found); the installer would update beside it, never delete" }
    else { Row 'INFO' 'Install folder' "$InstallRoot exists without an inventory; the installer would not overwrite files it did not create" }
} else { Row 'PASS' 'Install folder' "$InstallRoot does not exist yet (will be created; no admin needed)" }

# --- Package manager -------------------------------------------------------------------------
$wg = Try-Cmd 'winget' @('--version')
if ($wg) { Row 'PASS' 'winget' $wg } else { Row 'GAP' 'winget' 'not found (App Installer from the Microsoft Store provides it)' }

# --- Python 3.13 -----------------------------------------------------------------------------
$py = $null
if (Get-Command py -ErrorAction SilentlyContinue) { $py = Try-Cmd 'py' @('-3.13', '-c', 'import sys; print("%d.%d.%d" % sys.version_info[:3])') }
if (-not $py -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $v = Try-Cmd 'python' @('-c', 'import sys; print("%d.%d.%d" % sys.version_info[:3])')
    if ($v -and $v.StartsWith('3.13.')) { $py = $v }
}
if ($py) { Row 'PASS' 'Python 3.13' $py } else { Row 'GAP' 'Python 3.13' 'not found; installer adds it per-user (no admin)' }

# --- Git -------------------------------------------------------------------------------------
$git = Try-Cmd 'git' @('--version')
if ($git) { Row 'PASS' 'Git' $git } else { Row 'GAP' 'Git' 'not found; installer adds it (one Windows security box, the person clicks it)' }

# --- Tesseract -------------------------------------------------------------------------------
$tessDir = $env:CONCLAVE_TESSERACT_DIR
if (-not $tessDir) { $tessDir = 'C:\Program Files\Tesseract-OCR' }
$tessExe = Join-Path $tessDir 'tesseract.exe'
if (Test-Path -LiteralPath $tessExe) {
    $tv = Try-Cmd $tessExe @('--version')
    Row 'PASS' 'Tesseract' ("{0} ({1})" -f $tv, $tessExe)
} elseif (Get-Command tesseract -ErrorAction SilentlyContinue) {
    Row 'PASS' 'Tesseract' ("on PATH: {0}" -f (Get-Command tesseract).Source)
} else { Row 'GAP' 'Tesseract' 'not found; installer adds it (one Windows security box)' }

# --- Poppler ---------------------------------------------------------------------------------
$pop = $null
foreach ($c in @($env:CONCLAVE_POPPLER_BIN, $env:CONCLAVE_POPPLER_DIR)) { if ($c -and (Test-Path -LiteralPath (Join-Path $c 'pdftoppm.exe'))) { $pop = $c } }
if (-not $pop) {
    foreach ($pat in @('C:\poppler*', 'C:\Program Files\poppler*', (Join-Path $InstallRoot 'tools\poppler*'))) {
        Get-ChildItem -Path $pat -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            $b = Join-Path $_.FullName 'Library\bin'
            if (-not $pop -and (Test-Path -LiteralPath (Join-Path $b 'pdftoppm.exe'))) { $pop = $b }
        }
    }
}
if ($pop) { Row 'PASS' 'Poppler' $pop } else { Row 'GAP' 'Poppler' 'not found; installer unpacks a sha-checked copy under the install folder (no admin)' }

# --- Visual C++ runtime ----------------------------------------------------------------------
$vc = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64' -ErrorAction SilentlyContinue
if ($vc -and $vc.Installed -eq 1) { Row 'PASS' 'VC++ runtime x64' $vc.Version } else { Row 'GAP' 'VC++ runtime x64' 'not found; installer adds it (one Windows security box)' }

# --- GPU (report only) -----------------------------------------------------------------------
try {
    $gpus = @(Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name })
    $nv = $gpus | Where-Object { $_ -match 'NVIDIA' }
    if ($nv) {
        $smi = Try-Cmd 'nvidia-smi' @('--query-gpu=driver_version', '--format=csv,noheader')
        Row 'INFO' 'GPU' ("NVIDIA: {0}; driver {1} -> model readers can use the CUDA build" -f ($nv -join ', '), $smi)
    } else {
        Row 'INFO' 'GPU' ("no NVIDIA card ({0}) -> model readers run on CPU (slow) or on the pod" -f ($gpus -join ', '))
    }
} catch { Row 'INFO' 'GPU' 'could not list display adapters' }

# --- Windows Hello / TPM (report only; used by Obsidian recovery) ----------------------------
$tpm = $null
try { $tpm = Get-PnpDevice -Class SecurityDevices -PresentOnly -ErrorAction Stop | Where-Object { $_.FriendlyName -match 'Trusted Platform Module' } | Select-Object -First 1 } catch { $tpm = $null }
if ($tpm) { Row 'INFO' 'TPM' ("{0} ({1}); Windows Hello setup stays the person's own step" -f $tpm.FriendlyName, $tpm.Status) }
else { Row 'INFO' 'TPM' 'no TPM listed under security devices; Obsidian''s Hello recovery layer needs TPM 2.0 + Hello set up by the person' }

# --- Network reach (HEAD requests; nothing downloaded) ---------------------------------------
foreach ($u in @('https://github.com', 'https://pypi.org/simple/', 'https://files.pythonhosted.org', 'https://huggingface.co')) {
    try {
        $r = Invoke-WebRequest -Uri $u -Method Head -UseBasicParsing -TimeoutSec 10
        Row 'PASS' ("Reach " + ([uri]$u).Host) ("HTTP {0}" -f [int]$r.StatusCode)
    } catch {
        # A server that answers with an HTTP error (files.pythonhosted.org returns 404 at its
        # root) is still reachable: only "no answer at all" is a gap.
        $resp = $null
        try { $resp = $_.Exception.Response } catch { $resp = $null }
        if ($resp -and $resp.StatusCode) {
            Row 'PASS' ("Reach " + ([uri]$u).Host) ("reachable (server answered HTTP {0})" -f [int]$resp.StatusCode)
        } else {
            $msg = $_.Exception.Message
            if ($msg.Length -gt 80) { $msg = $msg.Substring(0, 80) }
            Row 'GAP' ("Reach " + ([uri]$u).Host) $msg
        }
    }
}

# --- GitHub sign-in (presence only; the person signs in themselves) -------------------------
$gh = Try-Cmd 'gh' @('--version')
if ($gh) {
    & gh auth status 1>$null 2>$null
    if ($LASTEXITCODE -eq 0) { Row 'PASS' 'GitHub sign-in' 'gh is signed in' }
    else { Row 'GAP' 'GitHub sign-in' 'gh present but not signed in; the person runs the sign-in in their browser' }
} else { Row 'GAP' 'GitHub sign-in' 'GitHub CLI not found; installer adds it, then the person signs in in their browser' }

# --- Report ----------------------------------------------------------------------------------
$final = if ($script:gaps -eq 0) { 'NESTEGG-CHECK: PASS' } else { "NESTEGG-CHECK: GAPS $($script:gaps)" }
$script:lines += $final
$dir = Join-Path $InstallRoot '.adastra'
if (-not (Test-Path -LiteralPath $dir)) { $dir = $env:TEMP }
$out = Join-Path $dir ('nestegg_check_{0}.txt' -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
try { Set-Content -LiteralPath $out -Value $script:lines -Encoding UTF8; Write-Host "report: $out" } catch { Write-Host "report not written: $($_.Exception.Message)" }
Write-Host $final
