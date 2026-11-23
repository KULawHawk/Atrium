# PHONERUNNER_DESK_T20.ps1  -  phone Run button desk test (go-live item 33, test T-20)
#
# Jake runs it with one Win+R paste (it asks for the Windows admin box itself):
#   powershell -NoExit -NoProfile -ExecutionPolicy Bypass -File "C:\Users\jmlee\Desktop\AL\PC_ITEMS\phonerunner_t20\PHONERUNNER_DESK_T20.ps1"
# PC lane first (no admin, changes nothing):
#   powershell -NoProfile -ExecutionPolicy Bypass -File "...\PHONERUNNER_DESK_T20.ps1" -DryRun
#   Last line T20-DRYRUN: PASS - READY FOR JAKE only when the programs check out, this network
#   reaches Tailscale and (if installed) the service is up; otherwise NOT READY FOR JAKE (why).
#
# What the full run does, stopping on the first failure:
#   1  checks "Always notify" (T-01C), read only; Windows settings are never changed
#   2  checks every program file against SHA256SUMS.txt; joins the 3 parts of phonerunner-service.exe
#   3  stops the PhoneRunner service if it is there; copies the 4 programs to C:\Program Files\PhoneRunner
#   4  install (first time only), then Tailscale sign-in (first time only; YOUR sign-in, link printed)
#   5  starts the service; you open the page on the phone; it reads the phone's device ID from the log
#   6  pairs the phone (you type your Tailscale login and YES), restarts
#   7  adds the phone's passkey (you tap on the phone and type the code it shows)
#   8  turns the Run button on (re-checks T-01C), restarts
#   9  stages 3 synthetic test items and checks each run from the logs:
#        t20-500-*   prints 500 lines: all 500 + its PASS line must reach the PC-only output file
#        t20-env-*   checks its own clean environment, write rights and starts a child; you tap Stop;
#                    the child must be gone
#        t20-link-*  holds a hard link to a protected file: the phone must refuse Run, no copy made
#  10  writes phonerunner_t20_RESULT.txt next to this script; last line T20: PASS or T20: FAIL (<reason>)
# Steps 1-8 stop on the first failure (each one is needed by the next). The test steps in 9
# (500 lines, environment checks, Stop, hard link) each record PASS or FAIL and the run goes on,
# so one failed step never hides the result of a later one; any FAIL makes the last line FAIL.
#
# -SelfTestRoot <folder> is for the Windows test machine only (tools/phonerunner Go test): it
# skips steps 1-8, uses <folder> instead of C:\ProgramData\PhoneRunner, takes its answers from
# <folder>\selftest\answers.txt instead of the keyboard, and marks every result SELFTEST.
# Nothing is deleted. Test items stay in the inbox (you can remove them later if you decide to).
param([switch]$DryRun, [switch]$Elevated, [string]$SelfTestRoot = '', [int]$SelfTestTlsPort = 0)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Join-Path $env:ProgramData 'PhoneRunner'
$SelfTest = $SelfTestRoot -ne ''
if ($SelfTest) { $Root = $SelfTestRoot }
$Dest = Join-Path $env:ProgramFiles 'PhoneRunner'
$Svc = 'PhoneRunner'
$EventsPath = Join-Path $Root 'log\events.jsonl'
$Result = Join-Path $here 'phonerunner_t20_RESULT.txt'
if ($SelfTest) { $Result = Join-Path $Root 'selftest\result.txt' }
$Lines = New-Object System.Collections.Generic.List[string]
$Exes = @('phonerunner-service.exe', 'phonerunner-session.exe', 'phonerunner-copyoff.exe', 'phonerunner-check.exe')

function Say([string]$l) { Write-Host $l; [void]$Lines.Add($l) }
function Ask([string]$l) {
  Write-Host ""; Write-Host ">>> $l" -ForegroundColor Yellow; [void]$Lines.Add(">>> $l")
  if ($SelfTest) { [System.IO.File]::AppendAllText((Join-Path $Root 'selftest\ask.txt'), "$l`n") }
}
# Keyboard answer; in a self-test, the next line of selftest\answers.txt (waits up to 2 minutes).
$script:Answered = 0
function Read-Answer {
  if (-not $SelfTest) { return "$(Read-Host)" }
  $f = Join-Path $Root 'selftest\answers.txt'
  $end = (Get-Date).AddMinutes(2)
  while ((Get-Date) -lt $end) {
    $a = @(Read-Shared $f -KeepEmpty)
    if ($a.Count -gt $script:Answered) { $script:Answered++; return $a[$script:Answered - 1] }
    Start-Sleep -Milliseconds 300
  }
  throw "SELFTEST: no answer within 2 minutes"
}
function Finish([string]$l) {
  if ($SelfTest) { $l = "SELFTEST $l" }
  Say ""; Say $l
  try { [System.IO.File]::WriteAllLines($Result, $Lines) ; Write-Host "(result file: $Result)" } catch { Write-Host "(could not write $Result)" }
  if ($l -like '*: PASS*') { exit 0 } else { exit 1 }
}
function Fail([string]$why) { Finish "T20: FAIL ($why)" }
trap { Fail "unexpected error at line $($_.InvocationInfo.ScriptLineNumber): $($_.Exception.Message)" }

function Get-Sha([string]$p) { (Get-FileHash -Algorithm SHA256 -LiteralPath $p).Hash.ToLower() }

function Read-Sums {
  $f = Join-Path $here 'SHA256SUMS.txt'
  if (-not (Test-Path -LiteralPath $f)) { Fail "SHA256SUMS.txt is not next to this script" }
  $m = @{}
  foreach ($l in Get-Content -LiteralPath $f) {
    if ($l -match '^([0-9a-f]{64})\s+\*?(\S+)$') { $m[$Matches[2]] = $Matches[1] }
  }
  return $m
}

# Checks the files and builds phonerunner-service.exe from its parts in $outDir. Returns the folder.
function Prepare-Programs([string]$outDir) {
  $sums = Read-Sums
  foreach ($n in @('phonerunner-service.exe.part0', 'phonerunner-service.exe.part1', 'phonerunner-service.exe.part2', 'phonerunner-session.exe', 'phonerunner-copyoff.exe', 'phonerunner-check.exe')) {
    $p = Join-Path $here $n
    if (-not (Test-Path -LiteralPath $p)) { Fail "$n is missing next to this script" }
    if (-not $sums.ContainsKey($n)) { Fail "$n has no line in SHA256SUMS.txt" }
    if ((Get-Sha $p) -ne $sums[$n]) { Fail "$n does not match SHA256SUMS.txt (copy it again)" }
  }
  Say "PASS all 6 files match SHA256SUMS.txt"
  New-Item -ItemType Directory -Force -Path $outDir | Out-Null
  $svcOut = Join-Path $outDir 'phonerunner-service.exe'
  $fs = [System.IO.File]::Create($svcOut)
  try {
    foreach ($i in 0..2) { $b = [System.IO.File]::ReadAllBytes((Join-Path $here "phonerunner-service.exe.part$i")); $fs.Write($b, 0, $b.Length) }
  } finally { $fs.Close() }
  if ((Get-Sha $svcOut) -ne $sums['phonerunner-service.exe']) { Fail "joined phonerunner-service.exe does not match SHA256SUMS.txt" }
  foreach ($n in @('phonerunner-session.exe', 'phonerunner-copyoff.exe', 'phonerunner-check.exe')) { Copy-Item -LiteralPath (Join-Path $here $n) -Destination (Join-Path $outDir $n) -Force }
  Say "PASS phonerunner-service.exe joined from its 3 parts and matches ($($sums['phonerunner-service.exe'].Substring(0,12))...)"
  return $outDir
}

function Test-AlwaysNotify {
  $k = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System'
  try { $v = Get-ItemProperty -Path $k } catch { return "could not read the UAC settings" }
  if ($v.EnableLUA -ne 1) { return "UAC is off (EnableLUA is not 1)" }
  if ($v.ConsentPromptBehaviorAdmin -ne 2) { return "UAC is not on Always notify (ConsentPromptBehaviorAdmin is $($v.ConsentPromptBehaviorAdmin), needs 2)" }
  if ($v.PromptOnSecureDesktop -ne 1) { return "the dimmed secure desktop is off (PromptOnSecureDesktop is not 1)" }
  return $null
}

# The event log is read with FileShare.ReadWrite and only new bytes are read each time, so the
# service can keep appending while this waits (a plain read would block its writes).
$script:EvPos = [long]0
$script:Ev = New-Object System.Collections.Generic.List[object]
function Update-Events {
  if (-not (Test-Path -LiteralPath $EventsPath)) { return }
  $fs = New-Object System.IO.FileStream($EventsPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
  try {
    if ($fs.Length -lt $script:EvPos) { $script:EvPos = [long]0 }
    $len = [int]($fs.Length - $script:EvPos)
    if ($len -le 0) { return }
    [void]$fs.Seek($script:EvPos, [System.IO.SeekOrigin]::Begin)
    $buf = New-Object byte[] $len
    $got = 0
    while ($got -lt $len) { $r = $fs.Read($buf, $got, $len - $got); if ($r -le 0) { break }; $got += $r }
  } finally { $fs.Close() }
  $cut = [Array]::LastIndexOf($buf, [byte]10, $got - 1)
  if ($cut -lt 0) { return }
  $script:EvPos += ($cut + 1)
  foreach ($l in ([System.Text.Encoding]::UTF8.GetString($buf, 0, $cut + 1) -split "`n")) {
    if ($l.Trim() -eq '') { continue }
    try { $e = $l | ConvertFrom-Json } catch { continue }
    try {
      if ($e.at -is [datetime]) { $at = $e.at.ToUniversalTime() }
      else { $at = [datetime]::Parse(($e.at -replace '(\.\d{1,7})\d*', '$1'), [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::AdjustToUniversal) }
    } catch { continue }
    $script:Ev.Add([pscustomobject]@{ At = $at; E = $e })
  }
}

# Events at or after $since (UTC).
function Get-Events([datetime]$since) {
  Update-Events
  return @($script:Ev | Where-Object { $_.At -ge $since } | ForEach-Object { $_.E })
}

# Waits up to $mins minutes for an event matching $test (scriptblock taking the event). Returns it or $null.
function Wait-For([datetime]$since, [scriptblock]$test, [int]$mins, [string]$what) {
  $end = (Get-Date).AddMinutes($mins)
  $n = 0
  while ((Get-Date) -lt $end) {
    foreach ($e in (Get-Events $since)) { if (& $test $e) { return $e } }
    Start-Sleep -Seconds 2
    $n++; if ($n % 15 -eq 0) { Write-Host "  still waiting for $what ..." }
  }
  return $null
}

# Reads a file the service may be appending to, without blocking its writes.
# -KeepEmpty (the self-test answers file): keeps empty lines (an empty answer is a plain
# Enter) and returns only complete lines (text after the last line break is still being written).
function Read-Shared([string]$p, [switch]$KeepEmpty) {
  if (-not (Test-Path -LiteralPath $p)) { return @() }
  $fs = New-Object System.IO.FileStream($p, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
  try { $sr = New-Object System.IO.StreamReader($fs, [System.Text.Encoding]::UTF8); $t = $sr.ReadToEnd() } finally { $fs.Close() }
  $parts = @($t -split "\r?\n")
  if ($KeepEmpty) { return @($parts | Select-Object -First ($parts.Count - 1)) }
  return @($parts | Where-Object { $_ -ne '' })
}

# A test step's failure: recorded, the run goes on.
$script:StepFails = New-Object System.Collections.Generic.List[string]
function Add-StepFail([string]$why) { Say "FAIL $why"; [void]$script:StepFails.Add($why) }
# Turns what a test step's catch block caught into a recorded failure.
function Add-StepError($err, [string]$step) {
  $m = "$($err.Exception.Message)"
  if ($m -like 'STEP: *') { Add-StepFail $m.Substring(6) } else { Add-StepFail "$step stopped by an unexpected error at line $($err.InvocationInfo.ScriptLineNumber): $m" }
}

function Restart-PR {
  Stop-Service -Name $Svc -ErrorAction SilentlyContinue
  (Get-Service -Name $Svc).WaitForStatus('Stopped', [TimeSpan]::FromSeconds(60))
  $t = (Get-Date).ToUniversalTime()
  Start-Service -Name $Svc
  $shown = $false
  $end = (Get-Date).AddMinutes(10)
  while ((Get-Date) -lt $end) {
    foreach ($e in (Get-Events $t)) {
      if ($e.event -eq 'service.listening') {
        if (-not $e.url) { Fail "the service is up but has no page address (turn on HTTPS Certificates in the Tailscale admin DNS page)" }
        return $e
      }
      if ($e.event -eq 'tailscale.unreachable' -and $e.blocked -eq $true) { Fail "$($e.problem)" }
      if ($e.event -eq 'service.config_error') { Fail "the service did not start: $($e.event) $($e.error)" }
      # Windows restarts the service by itself after a failed start; keep waiting for it.
      if ($e.event -eq 'tailscale.not_up' -and -not $script:NotUpSeen) { $script:NotUpSeen = $true; Say "WARN the service could not join Tailscale yet ($($e.error)); it restarts by itself, still waiting" }
      if (-not $shown -and $e.event -eq 'tailscale' -and "$($e.msg)" -match 'https://\S+') {
        $shown = $true
        Ask "Tailscale needs your sign-in for the PhoneRunner device. Open this link and sign in with YOUR account: $($Matches[0])   This window continues by itself (up to 10 minutes)."
      }
    }
    Start-Sleep -Seconds 2
  }
  Fail "the service did not report back within 10 minutes (see $EventsPath)"
}

function Read-Config { Get-Content -Raw -LiteralPath (Join-Path $Root 'private\config.json') | ConvertFrom-Json }

# Looks once at whether this network lets Tailscale through: one secure connection to
# Tailscale's coordination server, checked against this PC's own trusted certificates, then
# closed. Looks only: no other DNS, no other address, no certificate trusted that Windows does
# not trust. Returns $null when Tailscale is reachable, otherwise the problem in plain words.
function Get-TailscaleBlock([string]$h = 'controlplane.tailscale.com', [int]$port = 443) {
  $script:TsIssuer = ''; $script:TsErrors = ''
  try { $ips = (@([System.Net.Dns]::GetHostAddresses($h)) | ForEach-Object { $_.IPAddressToString }) -join ',' }
  catch { return "cannot look up $h ($($_.Exception.Message)): no internet, or this network blocks Tailscale" }
  $tcp = New-Object System.Net.Sockets.TcpClient
  try {
    $iar = $tcp.BeginConnect($h, $port, $null, $null)
    if (-not $iar.AsyncWaitHandle.WaitOne(10000)) { return "cannot reach $h ($ips): no internet, or this network blocks Tailscale" }
    $tcp.EndConnect($iar)
    $check = [System.Net.Security.RemoteCertificateValidationCallback] {
      param($sender, $cert, $chain, $errors)
      $script:TsIssuer = "$($cert.Issuer)"; $script:TsErrors = "$errors"
      return ($errors -eq [System.Net.Security.SslPolicyErrors]::None)
    }
    $ssl = New-Object System.Net.Security.SslStream($tcp.GetStream(), $false, $check)
    try { $ssl.AuthenticateAsClient($h); return $null }
    catch {
      if ($script:TsIssuer -and $script:TsErrors -ne 'None') { return "this network blocks Tailscale: $h ($ips) was answered by a certificate from '$($script:TsIssuer)', not Tailscale's ($($script:TsErrors)). A Tailscale sign-in will not help. The network's filter has to allow *.tailscale.com, or the PC needs another network" }
      return "the secure connection to $h ($ips) failed: $($_.Exception.Message)"
    }
    finally { $ssl.Dispose() }
  } catch { return "cannot reach $h ($ips): $($_.Exception.Message)" }
  finally { $tcp.Close() }
}

# $null when the service's latest start reached service.listening (its page address goes in
# $script:UpURL); otherwise why not. A start is the event with seq 1 (each start counts from 1).
$script:UpURL = ''
function Get-ServiceUpProblem {
  $ev = @(Get-Events ([datetime]::MinValue))
  $last = -1
  for ($i = 0; $i -lt $ev.Count; $i++) { if ("$($ev[$i].seq)" -eq '1') { $last = $i } }
  if ($last -lt 0) { return "no service start in its log yet" }
  $after = @($ev[$last..($ev.Count - 1)])
  $up = @($after | Where-Object { $_.event -eq 'service.listening' })
  if ($up.Count -gt 0) {
    if (-not $up[-1].url) { return "the service is up but has no page address (turn on HTTPS Certificates in the Tailscale admin DNS page)" }
    $script:UpURL = "$($up[-1].url)"; return $null
  }
  $bl = @($after | Where-Object { $_.event -eq 'tailscale.unreachable' })
  if ($bl.Count -gt 0) { return "$($bl[-1].problem)" }
  $no = @($after | Where-Object { $_.event -eq 'tailscale.not_up' -or $_.event -eq 'service.config_error' })
  if ($no.Count -gt 0) { return "$($no[-1].event): $($no[-1].error)" }
  return "it started at $($after[0].at) and has not joined Tailscale yet"
}

# Do the 4 programs in Program Files already match SHA256SUMS.txt?
function Test-ProgramsMatch {
  $sums = Read-Sums
  foreach ($n in $Exes) {
    $p = Join-Path $Dest $n
    if (-not (Test-Path -LiteralPath $p) -or -not $sums.ContainsKey($n) -or (Get-Sha $p) -ne $sums[$n]) { return $false }
  }
  return $true
}

# Pre-flight: changes nothing and asks for nothing. Fails (before any admin box or tap) when
# Tailscale is blocked here, or when the service is installed, up to date and still not up.
# Returns $true when the service is healthy and already runs these exact programs.
function Invoke-Preflight {
  $b = Get-TailscaleBlock
  if ($b) { Fail "PRE-FLIGHT: $b. Nothing was changed" }
  Say "PASS pre-flight: this network reaches Tailscale (genuine certificate)"
  $s = Get-Service -Name $Svc -ErrorAction SilentlyContinue
  if (-not $s) { Say "INFO pre-flight: PhoneRunner is not installed yet; the run installs it"; return $false }
  $match = Test-ProgramsMatch
  if ($s.Status -ne 'Running') { Say "INFO pre-flight: the PhoneRunner service is $($s.Status); the run starts it"; return $false }
  try { $p = Get-ServiceUpProblem } catch { Say "INFO pre-flight: cannot read the service log from this window ($($_.Exception.Message)); checked again after the admin box"; return $false }
  if ($p) {
    if (-not $match) { Say "INFO pre-flight: the service is not up ($p); the run updates its programs, which may fix it"; return $false }
    Say "  the service is not up yet ($p); waiting up to 3 minutes for it to come up by itself"
    $end = (Get-Date).AddMinutes(3)
    while ($p -and (Get-Date) -lt $end) { Start-Sleep -Seconds 5; $p = Get-ServiceUpProblem }
    if ($p) { Fail "PRE-FLIGHT: the PhoneRunner service is running these exact programs but is not up: $p. Nothing was changed" }
  }
  Say "PASS pre-flight: the PhoneRunner service is up. Page address: $script:UpURL"
  if ($match) { Say "PASS pre-flight: the installed programs already match; the service will not be stopped or reinstalled" }
  return $match
}

# Same shortening the service uses in its log: first letter, ***, then @domain.
function Mask-Login([string]$l) {
  if ([string]::IsNullOrEmpty($l)) { return '' }
  $at = $l.LastIndexOf('@')
  if ($at -le 0) { return $l.Substring(0, 1) + '***' }
  return $l.Substring(0, 1) + '***' + $l.Substring($at)
}

function New-TestItem([string]$id, [string]$title, [string]$script) {
  $d = Join-Path $Root "inbox\$id"
  New-Item -ItemType Directory -Path $d | Out-Null
  $hdr = [ordered]@{ title = $title; claimed_by = 'T-20 desk test (synthetic)'; entry = 'run.ps1'; estimate_time = 'under 1 minute'; estimate_cost = '$0'; needs_desktop = $false; output_may_copy = $false }
  [System.IO.File]::WriteAllText((Join-Path $d 'item.json'), ($hdr | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))
  [System.IO.File]::WriteAllText((Join-Path $d 'run.ps1'), $script, (New-Object System.Text.UTF8Encoding($false)))
  return $d
}

function Get-OutputLines([string]$id) { return (Read-Shared (Join-Path $Root "private\output\$id.log")) }

# ---------------------------------------------------------------- dry run (PC lane)
if ($DryRun) {
  Say "PhoneRunner T-20 dry run (changes nothing) $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
  $tmp = Join-Path $env:TEMP ('phonerunner-t20-dryrun-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
  $dir = Prepare-Programs $tmp
  # Continue, not Stop, around a program call: in Windows PowerShell 5.1 any stderr text from a
  # program turns into a stopping error under Stop.
  $ErrorActionPreference = 'Continue'
  $v = & (Join-Path $dir 'phonerunner-service.exe') version 2>&1
  $ErrorActionPreference = 'Stop'
  if ($LASTEXITCODE -ne 0 -or "$v" -notlike 'phonerunner-service *') { Fail "phonerunner-service.exe version did not run ($v)" }
  Say "PASS $v"
  $u = Test-AlwaysNotify
  if ($u) { Say "WARN T-01C: $u (the full run will stop here; Jake changes this himself)" } else { Say "PASS T-01C Always notify is on" }
  $s = Get-Service -Name $Svc -ErrorAction SilentlyContinue
  if ($s) { Say "INFO the PhoneRunner service already exists ($($s.Status)); the full run will update it" } else { Say "INFO no PhoneRunner service yet; the full run installs it" }
  # Ready for Jake? The same looks the full run's pre-flight takes, reported only (no waiting).
  $notReady = @()
  $b = Get-TailscaleBlock
  if ($b) { Say "NOT READY: $b"; $notReady += 'network blocks Tailscale' } else { Say "PASS this network reaches Tailscale (genuine certificate)" }
  if ($s -and $s.Status -eq 'Running') {
    try { $p = Get-ServiceUpProblem } catch { $p = "cannot read the service log from this window ($($_.Exception.Message))" }
    if ($p) { Say "NOT READY: the PhoneRunner service is not up: $p"; $notReady += 'service not up' } else { Say "PASS the PhoneRunner service is up at $script:UpURL" }
    if (Test-ProgramsMatch) { Say "INFO installed programs match; the full run will leave the service alone" } else { Say "INFO installed programs differ; the full run updates them (one admin box)" }
  } elseif ($s) { Say "INFO the service is $($s.Status); the full run starts it" }
  Say "INFO test copies left in $tmp (nothing deleted)"
  if ($notReady.Count -gt 0) { Finish "T20-DRYRUN: NOT READY FOR JAKE ($($notReady -join '; ')); the programs themselves PASS" }
  Finish "T20-DRYRUN: PASS - READY FOR JAKE"
}

# ---------------------------------------------------------------- full run (Jake)
$me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
# Only one T-20 window at a time: a second one stopping the service would break the first.
if (-not $SelfTest -and $isAdmin) {
  $script:OneWindow = New-Object System.Threading.Mutex($false, 'Global\PhoneRunnerT20Desk')
  if (-not $script:OneWindow.WaitOne(0)) { Write-Host "T20: another T-20 window is already running. Close this one; nothing was changed."; exit 1 }
}
# Pre-flight before the admin box: nothing is asked of Jake if Tailscale is blocked here or the
# service is up to date and not up.
$healthy = $false
if (-not $SelfTest) { $healthy = Invoke-Preflight }
if (-not $SelfTest -and -not $isAdmin) {
  if ($Elevated) { Write-Host "T20: FAIL (still not running as administrator)"; exit 1 }
  Write-Host "Windows will now ask you to allow PowerShell to make changes. That box is yours: click Yes."
  Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Verb RunAs -ArgumentList @('-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", '-Elevated')
  Write-Host "Continue in the new window. You can close this one."
  exit 0
}
if (-not $SelfTest) { $host.UI.RawUI.WindowTitle = 'PhoneRunner T-20 desk test' }
$start = (Get-Date).ToUniversalTime()
$stamp = (Get-Date -Format 'MMddHHmm')
Say "PhoneRunner T-20 desk test $(Get-Date -Format 'yyyy-MM-dd HH:mm') (Chicago time on this PC)"
if ($SelfTest) {
  Say "SELFTEST on the Windows test machine: steps 1-8 skipped, store $Root, taps simulated"
  $p = Get-ServiceUpProblem
  if ($p) { Fail "SELFTEST service-up check: $p" }
  Say "PASS service-up check from the log: up at $script:UpURL"
  $b = Get-TailscaleBlock
  if ($b) { Fail "SELFTEST the real Tailscale server was not reachable from the test machine: $b" }
  Say "PASS network check: the real controlplane.tailscale.com answered with a genuine certificate"
  if ($SelfTestTlsPort -gt 0) {
    $b = Get-TailscaleBlock '127.0.0.1' $SelfTestTlsPort
    if ("$b" -notlike 'this network blocks Tailscale:*') { Fail "SELFTEST a filter-style certificate was not reported as a block: $b" }
    Say "PASS network check: a stand-in filter certificate is reported as: $b"
  }
  $exe = 'phonerunner-service.exe'
} else {

# 1 T-01C
$u = Test-AlwaysNotify
if ($u) { Fail "T-01C: $u. Change it yourself in Windows (Control Panel > User Accounts > Change User Account Control settings > top notch), then run this again" }
Say "PASS T-01C Always notify is on"

# 2-3 programs (skipped when the pre-flight found them installed, matching and up)
$existing = Get-Service -Name $Svc -ErrorAction SilentlyContinue
if ($healthy) {
  Say "PASS programs already installed and matching; service left running (not stopped or reinstalled)"
} else {
$prep = Prepare-Programs (Join-Path $env:TEMP ('phonerunner-t20-' + (Get-Date -Format 'yyyyMMdd-HHmmss')))
if ($existing -and $existing.Status -ne 'Stopped') {
  Stop-Service -Name $Svc
  $existing.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(60))
  Say "PASS stopped the running PhoneRunner service to update it"
}
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
$sums = Read-Sums
foreach ($n in $Exes) {
  Copy-Item -LiteralPath (Join-Path $prep $n) -Destination (Join-Path $Dest $n) -Force
  if ((Get-Sha (Join-Path $Dest $n)) -ne $sums[$n]) { Fail "$n in $Dest does not match after copying" }
}
Say "PASS the 4 programs are in $Dest and match"
}
$exe = Join-Path $Dest 'phonerunner-service.exe'

# 4 install + sign-in
if (-not $existing) {
  & $exe install --user $env:USERNAME | ForEach-Object { Say "  $_" }
  if ($LASTEXITCODE -ne 0) { Fail "install did not finish (see the lines above)" }
  Say "PASS installed"
} elseif (-not $healthy) { Say "PASS already installed (programs updated)" }
if (-not (Test-Path -LiteralPath (Join-Path $Root 'tsnet\tailscaled.state'))) {
  Ask "Tailscale sign-in: a link appears below. Open it (on this PC or your phone), sign in with YOUR Tailscale account (approve the new device 'phonerunner' if Tailscale asks). This window continues by itself."
  & $exe login | ForEach-Object { Say "  $_" }
  if ($LASTEXITCODE -ne 0) { Fail "Tailscale sign-in did not finish (see the lines above)" }
} else { Say "PASS already signed in to Tailscale" }

# 5 start, phone visits, read its device ID
if ($healthy) { $url = $script:UpURL } else { $up = Restart-PR; $url = $up.url }
Say "PASS service running. Page address: $url"
$cfg = Read-Config
$paired = [bool](@($cfg.allowed_node_ids) | Where-Object { $_ })
if ($paired) {
  Ask "A phone is already paired. Type R to pair again, or just press Enter to keep it"
  if ("$(Read-Host)".Trim().ToUpper() -eq 'R') { $paired = $false }
}
if (-not $paired) {
  $t = (Get-Date).ToUniversalTime()
  Ask "On your PHONE: open the Tailscale app and make sure it is connected, then open this address in Chrome: $url   You should see 'Not allowed' with a Device ID. That is expected. This window waits up to 10 minutes."
  $e = Wait-For $t { param($e) $e.event -eq 'gate.refused' -and $e.node_id } 10 'your phone to open the page'
  if ($null -eq $e) { Fail "no visit from a phone within 10 minutes (is the phone's Tailscale app connected, and MagicDNS + HTTPS on in the Tailscale admin?)" }
  Say "PASS phone seen: device '$($e.node_name)', ID $($e.node_id), login $($e.login)"
  $hint = ''
  if ("$($e.login)" -like '*@github') { $hint = ' You signed up through GitHub, so it is your GitHub user name followed by @github (for example  name@github ), not an email.' }
  Ask "Check: the Device ID on your phone's page is $($e.node_id). If it is not, close this window. Otherwise type your Tailscale login exactly as Tailscale shows it (the log shows it shortened as $($e.login)).$hint You can see it on your phone: Tailscale app, tap your account at the top. Then press Enter."
  $login = ''
  for ($try = 1; $try -le 3; $try++) {
    $login = "$(Read-Host)".Trim()
    if ($login -eq '') { Ask "Nothing was typed. Type your Tailscale login (shortened in the log as $($e.login)) and press Enter"; continue }
    if ($e.login -and (Mask-Login $login) -cne $e.login) { Ask "That does not match: what you typed shortens to $(Mask-Login $login), the phone's is $($e.login) (capital letters count). Try again"; $login = ''; continue }
    break
  }
  if ($login -eq '') { Fail "no matching Tailscale login typed after 3 tries (nothing was changed; run this again to retry pairing)" }
  & $exe pair $e.node_id $login
  if ($LASTEXITCODE -ne 0) { Fail "pairing did not finish" }
  Say "PASS paired device $($e.node_id)"
  $up = Restart-PR
  Say "PASS service restarted with the phone paired"
}

# 7 passkey
Ask "Add (or replace) the phone's passkey now? Press Enter for yes, or type S to skip if you already added one"
if ("$(Read-Host)".Trim().ToUpper() -ne 'S') {
  Ask "Reload the page on your phone (it now shows the PhoneRunner page). Follow the lines below."
  & $exe passkey
  if ($LASTEXITCODE -ne 0) { Fail "the passkey step did not finish (see the lines above)" }
  Say "PASS passkey stored"
} else { Say "SKIP passkey (you said one is already added)" }

# 8 Run button (no restart when it is already on)
if ((Read-Config).run_button -eq $true) {
  Say "PASS Run button already on (service not restarted)"
} else {
  & $exe run-button on | ForEach-Object { Say "  $_" }
  if ($LASTEXITCODE -ne 0) { Fail "the Run button did not turn on" }
  $up = Restart-PR
  Say "PASS Run button on, service restarted"
}

}

# 9 synthetic items
$id500 = "t20-500-$stamp"; $idEnv = "t20-env-$stamp"; $idLink = "t20-link-$stamp"
New-TestItem $id500 'T-20 test: print 500 lines' "1..500 | ForEach-Object { `"line `$_`" }`r`n'PASS T20-500'`r`n" | Out-Null
$envScript = @'
$bad = 0
function Write-Check($n, $ok, $info) { if ($ok) { "CHECK $n PASS $info" } else { "CHECK $n FAIL $info"; $script:bad++ } }
$vals = Get-ChildItem env: | ForEach-Object { $_.Value }
Write-Check 'no-user-folders-in-environment' (-not ($vals | Where-Object { $_ -match '\\Users\\' })) ''
"ENV NAMES: " + ((Get-ChildItem env: | ForEach-Object { $_.Name }) -join ',')
$mp = @($env:PSModulePath -split ';' | Where-Object { $_ })
Write-Check 'module-path-system-only' (-not ($mp | Where-Object { $_ -match '\\Users\\|Documents' })) ($mp -join ';')
Write-Check 'runs-from-approved-copy' ($PSScriptRoot -like '*\PhoneRunner\approved\*') $PSScriptRoot
Write-Check 'temp-is-run-work-folder' ($env:TEMP -like '*\PhoneRunner\work\*') $env:TEMP
$w = $false; try { [IO.File]::WriteAllText((Join-Path $PSScriptRoot 'write-test.txt'), 'x'); $w = $true } catch {}
Write-Check 'cannot-write-into-approved-copy' (-not $w) ''
$t = $false; try { [IO.File]::WriteAllText((Join-Path $env:TEMP 'write-test.txt'), 'x'); $t = $true } catch {}
Write-Check 'can-write-temp' $t ''
$c = Start-Process -FilePath "$env:SystemRoot\System32\PING.EXE" -ArgumentList '-n 900 127.0.0.1' -WindowStyle Hidden -PassThru
[IO.File]::WriteAllText((Join-Path $env:TEMP 'child.pid'), "$($c.Id)")
"CHILD STARTED $($c.Id)"
"CHECKS FAILED: $bad"
"WAITING FOR STOP"
Start-Sleep -Seconds 900
"NOT STOPPED IN 15 MINUTES"
'@
New-TestItem $idEnv 'T-20 test: clean environment, then wait for Stop' $envScript | Out-Null
$linkDir = New-TestItem $idLink 'T-20 test: hard link must be refused' "'this must never run'`r`n"
$canary = Join-Path $Root 'private\t20_canary.txt'
if (-not (Test-Path -LiteralPath $canary)) { [System.IO.File]::WriteAllText($canary, 'T-20 canary (synthetic). If you can read this through the inbox, the hard-link check failed.') }
New-Item -ItemType HardLink -Path (Join-Path $linkDir 'data.txt') -Target $canary | Out-Null
Say "PASS staged 3 synthetic items: $id500, $idEnv, $idLink"
$old = @(Get-ChildItem -LiteralPath (Join-Path $Root 'inbox') -Directory -Filter 't20-*' | Where-Object { $_.Name -notlike "*-$stamp" })
if ($old.Count -gt 0) { Say "INFO $($old.Count) older T-20 test items are still on the phone page (not deleted). Tap only the ones ending in -$stamp." }

# 9a 500 lines
try {
  $t = (Get-Date).ToUniversalTime()
  Ask "On your phone: reload the page. Find '$id500' (T-20 test: print 500 lines; it ends in -$stamp, not an older one), tap Run, and unlock the phone when it asks. This window waits up to 10 minutes."
  $e = Wait-For $t { param($e) $e.event -eq 'run.ended' -and $e.item -eq $id500 } 10 "$id500 to finish"
  if ($null -eq $e) { throw "STEP: $id500 did not finish within 10 minutes (look at the phone for a refusal message)" }
  Start-Sleep -Seconds 2
  $out = @(Get-OutputLines $id500)
  $n = @($out | Where-Object { $_ -match '^line \d+$' }).Count
  $miss = @(1..500 | Where-Object { $out -notcontains "line $_" }).Count
  if ($n -ne 500 -or $miss -ne 0 -or $out -notcontains 'PASS T20-500') { throw "STEP: $id500 output: $n of 500 lines, $miss missing, PASS line $(if ($out -contains 'PASS T20-500') {'present'} else {'MISSING'})" }
  if ([int]$e.lines -ne 501 -or [int]$e.exit_code -ne 0) { throw "STEP: $id500 ended with $($e.lines) lines (expected 501) and exit code $($e.exit_code)" }
  Say "PASS $id500 ran: all 500 lines and its PASS line reached the PC-only output file"
  $ap = @(Get-ChildItem -LiteralPath (Join-Path $Root 'approved') -Directory -Filter "$id500-*")
  if ($ap.Count -lt 1) { throw "STEP: no approved copy folder for $id500" }
  Say "PASS approved copy made: $($ap[-1].Name)"
} catch { Add-StepError $_ '9a (500 lines)' }

# 9b clean environment (the Stop test below runs whatever happens here)
$envStarted = $false
try {
  $t = (Get-Date).ToUniversalTime()
  Ask "On your phone: tap Run on '$idEnv' (T-20 test: clean environment; ends in -$stamp) and unlock. Wait for this window to say TAP STOP NOW."
  $e = Wait-For $t { param($e) $e.event -eq 'run.started' -and $e.item -eq $idEnv } 10 "$idEnv to start"
  if ($null -eq $e) { throw "STEP: $idEnv did not start within 10 minutes" }
  $envStarted = $true
  $end = (Get-Date).AddMinutes(5)
  while ((Get-Date) -lt $end -and -not (@(Get-OutputLines $idEnv) -contains 'WAITING FOR STOP')) {
    if (@(Get-Events $t | Where-Object { $_.event -eq 'run.ended' -and $_.item -eq $idEnv }).Count -gt 0) { break }
    Start-Sleep -Seconds 1
  }
  $out = @(Get-OutputLines $idEnv)
  foreach ($l in @($out | Where-Object { $_ -like 'CHECK *' })) { Say "  $l" }
  $pass = @($out | Where-Object { $_ -like 'CHECK * PASS*' }).Count
  $bad = @($out | Where-Object { $_ -like 'CHECK * FAIL*' }).Count
  if ($out -notcontains 'WAITING FOR STOP' -or $pass -ne 6) {
    Say "  The item printed instead (first 15 other lines):"
    foreach ($l in @($out | Where-Object { $_ -notlike 'CHECK *' -and $_ -notlike 'ENV NAMES:*' } | Select-Object -First 15)) { Say "    $l" }
  }
  if ($out -notcontains 'WAITING FOR STOP') { throw "STEP: $idEnv did not reach its waiting point within 5 minutes ($pass of 6 checks passed, $bad failed)" }
  if ($bad -gt 0) { throw "STEP: ${idEnv}: $bad environment check(s) failed (lines above)" }
  if ($pass -ne 6) { throw "STEP: ${idEnv}: expected 6 CHECK PASS lines, saw $pass" }
  Say "PASS $idEnv environment checks: 6 of 6"
} catch { Add-StepError $_ '9b (clean environment)' }

# 9b Stop ends the item and its child
try {
  if (-not $envStarted) { throw "STEP: Stop not tested: $idEnv never started" }
  $childId = 0
  $wf = @(Get-ChildItem -LiteralPath (Join-Path $Root 'work') -Directory -Filter "$idEnv-*" | Sort-Object Name)
  if ($wf.Count -gt 0) {
    $pidText = (@(Read-Shared (Join-Path $wf[-1].FullName 'child.pid')) -join '').Trim()
    if ($pidText -match '^\d+$') { $childId = [int]$pidText }
  }
  if ($childId -le 0) {
    # Second source: the item's own "CHILD STARTED <pid>" line.
    $cl = @(@(Get-OutputLines $idEnv) | Where-Object { $_ -match '^CHILD STARTED (\d+)$' } | Select-Object -Last 1)
    if ($cl.Count -gt 0 -and $cl[0] -match '^CHILD STARTED (\d+)$') { $childId = [int]$Matches[1] }
  }
  if ($childId -le 0) { Add-StepFail "${idEnv}: no child process id was written, so Stop is tested on the item alone" }
  elseif (-not (Get-Process -Id $childId -ErrorAction SilentlyContinue)) { Add-StepFail "${idEnv}: its child process ($childId) was not running before Stop"; $childId = 0 }
  $t = (Get-Date).ToUniversalTime()
  if (@(Get-Events $start | Where-Object { $_.event -eq 'run.ended' -and $_.item -eq $idEnv }).Count -gt 0) { throw "STEP: $idEnv had already ended by itself, so Stop cannot be tested" }
  Ask "TAP STOP NOW on your phone (the run panel), and unlock when it asks. This window waits up to 5 minutes."
  $e = Wait-For $t { param($e) $e.event -eq 'run.ended' -and $e.item -eq $idEnv } 5 "$idEnv to stop"
  if ($null -eq $e) { throw "STEP: $idEnv did not end within 5 minutes of asking for Stop" }
  # The service writes run.stop just after the tree is ended; give it a moment to land.
  $stopSeen = $false
  $end = (Get-Date).AddSeconds(15)
  while (-not $stopSeen -and (Get-Date) -lt $end) {
    $stopSeen = @(Get-Events $t | Where-Object { $_.event -eq 'run.stop' -and $_.item -eq $idEnv }).Count -gt 0
    if (-not $stopSeen) { Start-Sleep -Milliseconds 500 }
  }
  if (-not ($e.stopped -eq $true -and $stopSeen)) { throw "STEP: $idEnv ended but no Stop was recorded (did it end by itself?)" }
  if ($childId -gt 0) {
    $end = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $end -and (Get-Process -Id $childId -ErrorAction SilentlyContinue)) { Start-Sleep -Milliseconds 500 }
    if (Get-Process -Id $childId -ErrorAction SilentlyContinue) { throw "STEP: Stop ended the item but its child process $childId is still running" }
    Say "PASS Stop ended $idEnv and its child process ($childId)"
  } else { Say "PASS Stop ended $idEnv (child not checked, see the FAIL above)" }
} catch { Add-StepError $_ '9b (Stop)' }

# 9c hard link refused
try {
  Ask "On your phone: reload, open '$idLink' (ends in -$stamp). It should list a problem for data.txt and Run should be refused. Try tapping Run once. Then press Enter here."
  [void](Read-Answer)
  if (@(Get-ChildItem -LiteralPath (Join-Path $Root 'approved') -Directory -Filter "$idLink-*").Count -ne 0) { throw "STEP: an approved copy of $idLink was made: the hard-link check did not stop it" }
  if (@(Get-Events $start | Where-Object { $_.event -eq 'run.started' -and $_.item -eq $idLink }).Count -ne 0) { throw "STEP: $idLink was started" }
  Say "PASS $idLink was not copied or started (hard link refused)"
  $yn = ''
  Ask "What did the phone show for '$idLink'? Type Y if it listed a problem for data.txt and refused Run, N if not"
  for ($try = 1; $try -le 5 -and $yn -ne 'Y' -and $yn -ne 'N'; $try++) {
    if ($try -gt 1) { Ask "Please type Y or N, then press Enter" }
    $yn = "$(Read-Answer)".Trim().ToUpper()
  }
  if ($yn -ne 'Y') { throw "STEP: the phone did not show the hard-link problem as expected (answer: '$yn')" }
  Say "PASS phone showed the hard-link problem and refused Run"
} catch { Add-StepError $_ '9c (hard link)' }

Say ""
Say "INFO the Run button stays ON. To turn it off later: elevated window, then: & '$exe' run-button off ; Restart-Service PhoneRunner"
Say "INFO the 3 test items stay in $Root\inbox (nothing deleted)."
if ($script:StepFails.Count -eq 0) { Finish "T20: PASS (Run, 500-line output, clean environment, Stop of the whole tree, hard-link refusal)" }
Fail "$($script:StepFails.Count) test step(s) failed: $($script:StepFails -join ' | ')"
