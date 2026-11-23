# Install-AdAstra.ps1 - the ONE command that installs the APEX suite (Jake 11/22 5:34 PM: "Anytime you can run one
# command that will take care of all the parts at once, that's the way it should be done.")
#
#   Double-click "Install AdAstra.cmd"          (installs)
#   ... Install AdAstra.cmd -DryRun              (says what each phase would do; installs nothing)
#
# It runs, in order, stopping at the first phase that does not pass:
#   phase 1  Install-Prereqs.ps1   the Windows programs (Python 3.13, Git, Tesseract, Poppler, ...) through winget
#   phase 2  install_parts.py      every part in its own environment from exact, hash-checked versions, then the
#                                  reader record (envs\reader_envs.json) and each reader's self-test
# Every Windows security box and winget agreement stays the person's own answer: this script never passes
# -AssumeYes, never clicks, skips or avoids one. It deletes nothing, changes no Windows setting, reads no key.
# Sources: <InstallRoot>\src must hold Conclave, locutus, sequoia, obsidian and atrium; a missing one is a FAIL
# before anything is installed. Last line: NESTEGG-INSTALL: PASS | HOLD n | FAIL (never a silent pass).
param(
    [string]$InstallRoot = (Join-Path $env:USERPROFILE 'AdAstra'),
    [string]$Src = '',
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Src) { $Src = Join-Path $InstallRoot 'src' }
$envs = Join-Path $InstallRoot 'envs'

function Done([string]$Line, [int]$Code) { Write-Host ''; Write-Host $Line; exit $Code }

$missing = @('Conclave', 'locutus', 'sequoia', 'obsidian', 'atrium') | Where-Object { -not (Test-Path -LiteralPath (Join-Path $Src $_) -PathType Container) }
if ($missing) { Done ("NESTEGG-INSTALL: FAIL - source folders missing in {0}: {1}" -f $Src, ($missing -join ', ')) 1 }

Write-Host "=== phase 1 of 2: Windows programs ==="
$p1 = @{ InstallRoot = $InstallRoot }
if ($DryRun) { $p1.DryRun = $true }
$last1 = ''
& (Join-Path $here 'Install-Prereqs.ps1') @p1 *>&1 | ForEach-Object { $s = "$_"; Write-Host $s; if ($s -like 'NESTEGG-PREREQS:*') { $last1 = $s } }
if ($last1 -ne 'NESTEGG-PREREQS: PASS') {
    Done ("NESTEGG-INSTALL: FAIL - phase 1 ended '{0}'; phase 2 not started" -f $(if ($last1) { $last1 } else { 'with no result line' })) 1
}

Write-Host "=== phase 2 of 2: parts ==="
$a2 = @('-3.13', '-I', (Join-Path $here 'install_parts.py'), '--src', $Src, '--envs', $envs)
if ($DryRun) { $a2 += '--dry-run' }
& py @a2
$rc = $LASTEXITCODE
switch ($rc) {
    0 { Done 'NESTEGG-INSTALL: PASS' 0 }
    2 { Done 'NESTEGG-INSTALL: HOLD - installed, but some parts wait on a measurement or a decision (see the HOLD rows above)' 2 }
    default { Done ("NESTEGG-INSTALL: FAIL - phase 2 exit {0} (see the FAIL rows above)" -f $rc) 1 }
}
