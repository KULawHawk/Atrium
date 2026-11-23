//go:build windows

package winsvc

import (
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"golang.org/x/sys/windows"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/runner"
)

// t20EnvScript is the T-20 desk script's env item, verbatim.
const t20EnvScript = `$bad = 0
function R($n, $ok, $info) { if ($ok) { "CHECK $n PASS $info" } else { "CHECK $n FAIL $info"; $script:bad++ } }
$vals = Get-ChildItem env: | ForEach-Object { $_.Value }
R 'no-user-folders-in-environment' (-not ($vals | Where-Object { $_ -match '\\Users\\' })) ''
"ENV NAMES: " + ((Get-ChildItem env: | ForEach-Object { $_.Name }) -join ',')
$mp = @($env:PSModulePath -split ';' | Where-Object { $_ })
R 'module-path-system-only' (-not ($mp | Where-Object { $_ -match '\\Users\\|Documents' })) ($mp -join ';')
R 'runs-from-approved-copy' ($PSScriptRoot -like '*\PhoneRunner\approved\*') $PSScriptRoot
R 'temp-is-run-work-folder' ($env:TEMP -like '*\PhoneRunner\work\*') $env:TEMP
$w = $false; try { [IO.File]::WriteAllText((Join-Path $PSScriptRoot 'write-test.txt'), 'x'); $w = $true } catch {}
R 'cannot-write-into-approved-copy' (-not $w) ''
$t = $false; try { [IO.File]::WriteAllText((Join-Path $env:TEMP 'write-test.txt'), 'x'); $t = $true } catch {}
R 'can-write-temp' $t ''
$c = Start-Process -FilePath "$env:SystemRoot\System32\PING.EXE" -ArgumentList '-n 900 127.0.0.1' -WindowStyle Hidden -PassThru
[IO.File]::WriteAllText((Join-Path $env:TEMP 'child.pid'), "$($c.Id)")
"CHILD STARTED $($c.Id)"
"CHECKS FAILED: $bad"
"WAITING FOR STOP"
Start-Sleep -Seconds 900
"NOT STOPPED IN 15 MINUTES"
`

// t20EnvFixed is the same item with the check function renamed. In Windows
// PowerShell 5.1 "r" is a built-in alias of Invoke-History, and an alias wins
// over a function of the same name, so every "R ..." line in t20EnvScript ran
// Invoke-History instead of printing a CHECK line.
var t20EnvFixed = strings.ReplaceAll(strings.ReplaceAll(t20EnvScript, "function R(", "function Write-Check("), "\nR '", "\nWrite-Check '")

// runT20Env runs one env item through the real runner (fixed PowerShell command
// line, clean environment, line reader, key filter) and returns the kept lines
// once WAITING FOR STOP has been seen, plus whether the item was still running
// at that moment (output visible mid-run, not only at exit). The root sits
// outside C:\Users so the path checks judge the same thing they judge on the PC.
func runT20Env(t *testing.T, script string) (lines []string, midRun bool) {
	t.Helper()
	base, err := os.MkdirTemp(os.Getenv("SystemDrive")+`\`, "pr-t20-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(base) })
	root := filepath.Join(base, "PhoneRunner")
	copyDir := filepath.Join(root, "approved", "t20-env-11231404-20261123T200945-8dfa99ab")
	workDir := filepath.Join(root, "work", "t20-env-11231404-20261123T200945-8dfa99ab")
	for _, d := range []string{copyDir, workDir} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(filepath.Join(copyDir, "run.ps1"), []byte(strings.ReplaceAll(script, "\n", "\r\n")), 0o644); err != nil {
		t.Fatal(err)
	}
	sysRoot, _ := windows.GetSystemWindowsDirectory()
	spec := runner.Command(sysRoot, copyDir, workDir, "run.ps1")
	var mu sync.Mutex
	var kept []string
	var proc *waitOnly
	start := func(s runner.Spec) (runner.Proc, error) {
		c := exec.Command(s.Exe, s.Args...)
		c.Dir, c.Env = s.Dir, s.Env
		r, w := io.Pipe()
		c.Stdout, c.Stderr = w, w
		if err := c.Start(); err != nil {
			return nil, err
		}
		done := make(chan int, 1)
		go func() { c.Wait(); w.Close(); done <- c.ProcessState.ExitCode() }()
		proc = &waitOnly{c: c, out: r, done: done}
		return proc, nil
	}
	rn := runner.New(start, func(string, map[string]any) {}, func(_ string, l string) { mu.Lock(); kept = append(kept, l); mu.Unlock() }, time.Now)
	if err := rn.Start("t20-env", "x", spec, runner.Options{}); err != nil {
		t.Fatal(err)
	}
	seen := func() bool {
		mu.Lock()
		defer mu.Unlock()
		for _, l := range kept {
			if l == "WAITING FOR STOP" {
				return true
			}
		}
		return false
	}
	deadline := time.Now().Add(2 * time.Minute)
	for time.Now().Before(deadline) && !seen() {
		time.Sleep(200 * time.Millisecond)
	}
	midRun = seen() && rn.Current().Running()
	_ = rn.Stop()
	// The test starter has no job object, so end the ping child by its pid.
	if b, err := os.ReadFile(filepath.Join(workDir, "child.pid")); err == nil {
		exec.Command("taskkill", "/F", "/PID", strings.TrimSpace(string(b))).Run()
	}
	mu.Lock()
	lines = append([]string{}, kept...)
	mu.Unlock()
	for _, l := range lines {
		t.Logf("LINE %q", l)
	}
	return lines, midRun
}

// deskCount applies the desk script's own matching ('CHECK *', 'CHECK * PASS*').
func deskCount(lines []string) (checks []string, pass int) {
	for _, l := range lines {
		if strings.HasPrefix(l, "CHECK ") {
			checks = append(checks, l)
			if strings.Contains(l, " PASS") {
				pass++
			}
		}
	}
	return checks, pass
}

// TestT20EnvDeskFailureReproduced reruns the exact script from the 11/23 desk
// run: it reaches WAITING FOR STOP yet prints no CHECK line, which is the
// desk's "expected 6 CHECK PASS lines" failure.
func TestT20EnvDeskFailureReproduced(t *testing.T) {
	lines, _ := runT20Env(t, t20EnvScript)
	checks, _ := deskCount(lines)
	if len(checks) != 0 {
		t.Fatalf("expected the 11/23 script to print no CHECK line, got %d", len(checks))
	}
	hist := false
	for _, l := range lines {
		if strings.Contains(l, "Invoke-History") {
			hist = true
		}
	}
	if !hist {
		t.Fatalf("expected Invoke-History errors in the output (the R alias); none found")
	}
}

// TestT20EnvItemFixed runs the corrected item: all six CHECK lines arrive while
// the item is still running. The approved-copy write check depends on the PC's
// folder permissions (the service locks that folder for Jake's account), which
// this test does not set up, so it is reported, not judged; the other five must
// PASS.
func TestT20EnvItemFixed(t *testing.T) {
	lines, midRun := runT20Env(t, t20EnvFixed)
	if !midRun {
		t.Fatalf("WAITING FOR STOP was not visible while the item was still running")
	}
	checks, _ := deskCount(lines)
	if len(checks) != 6 {
		t.Fatalf("expected 6 CHECK lines, got %d", len(checks))
	}
	for _, c := range checks {
		if strings.HasPrefix(c, "CHECK cannot-write-into-approved-copy ") {
			t.Logf("reported only (needs the PC's folder lock): %s", c)
			continue
		}
		if !strings.Contains(c, " PASS") {
			t.Errorf("check failed: %s", c)
		}
	}
}

// waitOnly: Wait returns when the process ends; the pipe closes after.
type waitOnly struct {
	c    *exec.Cmd
	out  io.Reader
	done chan int
}

func (p *waitOnly) Output() io.Reader  { return p.out }
func (p *waitOnly) Wait() (int, error) { return <-p.done, nil }
func (p *waitOnly) Kill() error        { return p.c.Process.Kill() }
func (p *waitOnly) Close()             {}
