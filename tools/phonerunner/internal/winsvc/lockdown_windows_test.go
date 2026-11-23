//go:build windows

package winsvc

import (
	"fmt"
	"io"
	"os"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/pccheck"
)

// The child half: busy goroutines (so the runtime preempts threads), a few
// garbage collections and new threads, then a clean exit. A Go program that
// cannot manage its own threads under the lock-down crashes here instead.
func TestMain(m *testing.M) {
	if os.Getenv("PHONERUNNER_LOCKDOWN_CHILD") == "1" {
		var wg sync.WaitGroup
		stop := time.Now().Add(2 * time.Second)
		for i := 0; i < 4*runtime.NumCPU(); i++ {
			wg.Add(1)
			go func() {
				defer wg.Done()
				x := 0
				for time.Now().Before(stop) {
					x++
				}
				_ = x
			}()
		}
		for time.Now().Before(stop) {
			runtime.GC()
			time.Sleep(50 * time.Millisecond)
		}
		wg.Wait()
		os.Exit(0)
	}
	os.Exit(m.Run())
}

var procCreateRestrictedToken = windows.NewLazySystemDLL("advapi32.dll").NewProc("CreateRestrictedToken")

// startLocked starts this test binary as a child with the same process rights,
// thread rights and token default rights that Launch gives the session part and
// items, using a copy of the test's own token (no SYSTEM needed). It returns the
// exit code and the first part of the child's error output.
func startLocked(t *testing.T) (uint32, string) {
	return startOpt(t, opt{procSD: true, threadSD: true, launchDefault: true})
}

// The runner's own token is already High, so the tests run the child at Medium
// (lowering needs no privilege) and play the attacker one step lower, at Low:
// the same one-step gap as High session part vs Medium agents on the PC.
const testChildLevel = "S-1-16-8192"
const lowIL = "S-1-16-4096"

// opt turns each part of the lock-down on or off (the diagnostics below).
type opt struct {
	procSD, threadSD bool
	launchDefault    bool         // the session part's default rights + level, as Launch sets them (level: testChildLevel)
	item             bool         // an item's default rights, as Launch sets them (level unchanged)
	argv             []string     // run this program instead of the test binary's child half
	defMask          uint32       // else, if non-zero: default rights giving Jake this mask
	probe            func(uint32) // called with the child's process id while it runs
}

func startOpt(t *testing.T, o opt) (uint32, string) {
	t.Helper()
	var self windows.Token
	if err := windows.OpenProcessToken(windows.CurrentProcess(), windows.TOKEN_DUPLICATE|windows.TOKEN_QUERY|windows.TOKEN_ASSIGN_PRIMARY|windows.TOKEN_ADJUST_DEFAULT, &self); err != nil {
		t.Fatal(err)
	}
	defer self.Close()
	var tok windows.Token // a restricted copy (nothing removed) may be used without extra privileges
	if r, _, e := procCreateRestrictedToken.Call(uintptr(self), 0, 0, 0, 0, 0, 0, 0, uintptr(unsafe.Pointer(&tok))); r == 0 {
		t.Fatal(e)
	}
	defer tok.Close()
	tu, err := tok.GetTokenUser()
	if err != nil {
		t.Fatal(err)
	}
	user := tu.User.Sid.String()
	switch {
	case o.launchDefault:
		if err := setDefault(tok, defaultDACL(user)); err != nil {
			t.Fatal(err)
		}
		tml := windows.Tokenmandatorylabel{Label: windows.SIDAndAttributes{Sid: mustSid(t, testChildLevel), Attributes: windows.SE_GROUP_INTEGRITY}}
		if err := windows.SetTokenInformation(tok, windows.TokenIntegrityLevel, (*byte)(unsafe.Pointer(&tml)), tml.Size()); err != nil {
			t.Fatal(err)
		}
	case o.item:
		if err := applyLockdown(tok, user, false); err != nil {
			t.Fatal(err)
		}
	case o.defMask != 0:
		if err := setDefault(tok, fmt.Sprintf("D:P(A;;GA;;;SY)(A;;0x%X;;;%s)(A;;0x%X;;;OW)", o.defMask, user, o.defMask)); err != nil {
			t.Fatal(err)
		}
	}
	saP, saT, err := lockdownAttrs(user)
	if err != nil {
		t.Fatal(err)
	}
	if !o.procSD {
		saP = nil
	}
	if !o.threadSD {
		saT = nil
	}
	inherit := &windows.SecurityAttributes{Length: uint32(unsafe.Sizeof(windows.SecurityAttributes{})), InheritHandle: 1}
	var er, ew windows.Handle
	if err := windows.CreatePipe(&er, &ew, inherit, 0); err != nil {
		t.Fatal(err)
	}
	windows.SetHandleInformation(er, windows.HANDLE_FLAG_INHERIT, 0)
	exe, _ := os.Executable()
	argv := []string{exe}
	if len(o.argv) > 0 {
		exe, argv = o.argv[0], o.argv
	}
	env := append(os.Environ(), "PHONERUNNER_LOCKDOWN_CHILD=1")
	si := &windows.StartupInfo{Cb: uint32(unsafe.Sizeof(windows.StartupInfo{})), Flags: windows.STARTF_USESTDHANDLES, StdOutput: ew, StdErr: ew}
	exe16, _ := windows.UTF16PtrFromString(exe)
	cmd16, _ := windows.UTF16PtrFromString(windows.ComposeCommandLine(argv))
	var pi windows.ProcessInformation
	err = windows.CreateProcessAsUser(tok, exe16, cmd16, saP, saT, true, windows.CREATE_UNICODE_ENVIRONMENT|windows.CREATE_NO_WINDOW, envBlock(env), nil, si, &pi)
	windows.CloseHandle(ew)
	if err != nil {
		windows.CloseHandle(er)
		t.Fatal(err)
	}
	defer windows.CloseHandle(pi.Process)
	windows.CloseHandle(pi.Thread)
	f := os.NewFile(uintptr(er), "child-errors")
	defer f.Close()
	done := make(chan string, 1)
	go func() {
		b, _ := io.ReadAll(io.LimitReader(f, 2000))
		io.Copy(io.Discard, f)
		done <- strings.TrimSpace(string(b))
	}()
	if o.probe != nil {
		time.Sleep(700 * time.Millisecond)
		o.probe(pi.ProcessId)
	}
	if ev, _ := windows.WaitForSingleObject(pi.Process, 60000); ev != windows.WAIT_OBJECT_0 {
		windows.TerminateProcess(pi.Process, 1)
		t.Fatal("child still running after 60 s")
	}
	var code uint32
	windows.GetExitCodeProcess(pi.Process, &code)
	return code, <-done
}

func setDefault(tok windows.Token, sddl string) error {
	sd, err := windows.SecurityDescriptorFromString(sddl)
	if err != nil {
		return err
	}
	dacl, _, err := sd.DACL()
	if err != nil {
		return err
	}
	tdd := tokenDefaultDACL{DefaultDacl: dacl}
	return windows.SetTokenInformation(tok, windows.TokenDefaultDacl, (*byte)(unsafe.Pointer(&tdd)), uint32(unsafe.Sizeof(tdd)))
}

// threadAccess tries to open every thread of pid for suspend + set-context (what
// code injection needs), as this test's own token at the given integrity level
// ("" = unchanged). It returns how many threads opened out of how many exist.
func threadAccess(t *testing.T, pid uint32, level string) (opened, total int) {
	return threadMask(t, pid, level, windows.THREAD_SUSPEND_RESUME|windows.THREAD_SET_CONTEXT)
}

func threadMask(t *testing.T, pid uint32, level string, mask uint32) (opened, total int) {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	if level != "" {
		var self, imp windows.Token
		if err := windows.OpenProcessToken(windows.CurrentProcess(), windows.TOKEN_DUPLICATE|windows.TOKEN_QUERY, &self); err != nil {
			t.Fatal(err)
		}
		defer self.Close()
		if err := windows.DuplicateTokenEx(self, windows.TOKEN_ALL_ACCESS, nil, windows.SecurityImpersonation, windows.TokenImpersonation, &imp); err != nil {
			t.Fatal(err)
		}
		defer imp.Close()
		sid, err := windows.StringToSid(level)
		if err != nil {
			t.Fatal(err)
		}
		tml := windows.Tokenmandatorylabel{Label: windows.SIDAndAttributes{Sid: sid, Attributes: windows.SE_GROUP_INTEGRITY}}
		if err := windows.SetTokenInformation(imp, windows.TokenIntegrityLevel, (*byte)(unsafe.Pointer(&tml)), tml.Size()); err != nil {
			t.Fatal(err)
		}
		if err := windows.SetThreadToken(nil, imp); err != nil {
			t.Fatal(err)
		}
		defer windows.RevertToSelf()
	}
	snap, err := windows.CreateToolhelp32Snapshot(windows.TH32CS_SNAPTHREAD, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer windows.CloseHandle(snap)
	var te windows.ThreadEntry32
	te.Size = uint32(unsafe.Sizeof(te))
	for err := windows.Thread32First(snap, &te); err == nil; err = windows.Thread32Next(snap, &te) {
		if te.OwnerProcessID != pid {
			continue
		}
		total++
		h, err := windows.OpenThread(mask, false, te.ThreadID)
		if err == nil {
			opened++
			windows.CloseHandle(h)
		}
	}
	return opened, total
}

const mediumIL = "S-1-16-8192"

// asLevel runs fn on a locked thread impersonating this test's own token
// lowered to level.
func asLevel(t *testing.T, level string, fn func()) {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	var self, imp windows.Token
	if err := windows.OpenProcessToken(windows.CurrentProcess(), windows.TOKEN_DUPLICATE|windows.TOKEN_QUERY, &self); err != nil {
		t.Fatal(err)
	}
	defer self.Close()
	if err := windows.DuplicateTokenEx(self, windows.TOKEN_ALL_ACCESS, nil, windows.SecurityImpersonation, windows.TokenImpersonation, &imp); err != nil {
		t.Fatal(err)
	}
	defer imp.Close()
	tml := windows.Tokenmandatorylabel{Label: windows.SIDAndAttributes{Sid: mustSid(t, level), Attributes: windows.SE_GROUP_INTEGRITY}}
	if err := windows.SetTokenInformation(imp, windows.TokenIntegrityLevel, (*byte)(unsafe.Pointer(&tml)), tml.Size()); err != nil {
		t.Fatal(err)
	}
	if err := windows.SetThreadToken(nil, imp); err != nil {
		t.Fatal(err)
	}
	defer windows.RevertToSelf()
	fn()
}

func mustSid(t *testing.T, s string) *windows.SID {
	sid, err := windows.StringToSid(s)
	if err != nil {
		t.Fatal(err)
	}
	return sid
}

// TestGoChildUnderLockdown: a Go program (the session part is one) must run
// normally under the rights Launch gives it. This is the T-20 desk failure
// ("session.ended ... pipe closed" every few seconds) reproduced off the PC.
func TestGoChildUnderLockdown(t *testing.T) {
	code, errs := startLocked(t)
	if code != 0 {
		t.Fatalf("child exit %d under the lock-down; its errors:\n%s", code, errs)
	}
	fmt.Println("PASS a Go child runs normally under the lock-down")
}

// TestLockdownBlocksLowerLevel: under the session part's launch rights, a program
// one integrity level below it (on the PC: Jake's agents and every Run button
// item, all Medium, against the watcher at High) is refused every right the
// PC check (phonerunner-check, T-16) requires refused, on the process and on
// every thread; the same program at the child's own level gets suspend +
// set-context on its threads (the control: the probe itself works).
func TestLockdownBlocksLowerLevel(t *testing.T) {
	var bad []string
	var threads, sameOpened, sameTotal int
	code, errs := startOpt(t, opt{procSD: true, threadSD: true, launchDefault: true, probe: func(pid uint32) {
		asLevel(t, lowIL, func() {
			for _, d := range pccheck.Dangerous {
				if h, err := windows.OpenProcess(d.Mask, false, pid); err == nil {
					windows.CloseHandle(h)
					bad = append(bad, "process: "+d.Name)
				}
			}
			if h, err := windows.OpenProcess(pccheck.QueryLimited, false, pid); err == nil {
				windows.CloseHandle(h)
			} else {
				bad = append(bad, "process: query-limited was refused (Jake must keep it)")
			}
		})
		ids := threadIDs(pid)
		threads, sameTotal = len(ids), len(ids)
		for _, d := range pccheck.DangerousThread {
			var opened int
			asLevel(t, lowIL, func() { opened = openCount(ids, d.Mask) })
			if opened > 0 {
				bad = append(bad, fmt.Sprintf("thread: %s on %d of %d threads", d.Name, opened, len(ids)))
			}
		}
		asLevel(t, testChildLevel, func() {
			sameOpened = openCount(ids, windows.THREAD_SUSPEND_RESUME|windows.THREAD_SET_CONTEXT)
		})
	}})
	if code != 0 {
		t.Fatalf("child exit %d; its errors:\n%s", code, errs)
	}
	t.Logf("child threads %d; same level opened %d/%d for suspend+set-context", threads, sameOpened, sameTotal)
	if threads == 0 || sameTotal == 0 {
		t.Fatal("probe saw no threads; it proves nothing")
	}
	if sameOpened == 0 {
		t.Fatal("control failed: even a same-level program opened no thread, so the probe cannot tell")
	}
	if len(bad) > 0 {
		t.Fatalf("FAIL a lower-level program got:\n  %s", strings.Join(bad, "\n  "))
	}
	fmt.Println("PASS a lower-level program is refused every dangerous right on the child")
}

// threadIDs lists pid's threads (as this test itself: a lowered token may not
// take the snapshot).
func threadIDs(pid uint32) []uint32 {
	snap, err := windows.CreateToolhelp32Snapshot(windows.TH32CS_SNAPTHREAD, 0)
	if err != nil {
		return nil
	}
	defer windows.CloseHandle(snap)
	var ids []uint32
	var te windows.ThreadEntry32
	te.Size = uint32(unsafe.Sizeof(te))
	for err := windows.Thread32First(snap, &te); err == nil; err = windows.Thread32Next(snap, &te) {
		if te.OwnerProcessID == pid {
			ids = append(ids, te.ThreadID)
		}
	}
	return ids
}

// openCount opens each thread with mask as the calling thread is.
func openCount(ids []uint32, mask uint32) (opened int) {
	for _, id := range ids {
		if h, err := windows.OpenThread(mask, false, id); err == nil {
			opened++
			windows.CloseHandle(h)
		}
	}
	return opened
}

// TestItemProgramsUnderItemRights: the programs Run button items use start and
// exit normally under an item's launch rights (Jake's own level).
func TestItemProgramsUnderItemRights(t *testing.T) {
	sys, _ := windows.GetSystemDirectory()
	for _, argv := range [][]string{
		{sys + `\cmd.exe`, "/c", "exit 0"},
		{sys + `\WindowsPowerShell\v1.0\powershell.exe`, "-NoProfile", "-NonInteractive", "-Command", "exit 0"},
	} {
		code, errs := startOpt(t, opt{procSD: true, threadSD: true, item: true, argv: argv})
		t.Logf("ITEM %s: exit %d (0x%X) %s", argv[0], code, code, errs)
		if code != 0 {
			t.Errorf("FAIL %s exit 0x%X under item rights", argv[0], code)
		}
	}
	if code, errs := startOpt(t, opt{procSD: true, threadSD: true, item: true}); code != 0 {
		t.Errorf("FAIL a Go program exit 0x%X under item rights: %s", code, errs)
	}
}

// TestItemLaterThreads records the item trade: a program at the item's own level
// (on the PC: any program Jake runs, agents included) is refused the item's
// process and first thread, but may open threads the item creates later.
func TestItemLaterThreads(t *testing.T) {
	var procBad []string
	var opened, total int
	code, _ := startOpt(t, opt{procSD: true, threadSD: true, item: true, probe: func(pid uint32) {
		for _, d := range pccheck.Dangerous {
			if h, err := windows.OpenProcess(d.Mask, false, pid); err == nil {
				windows.CloseHandle(h)
				procBad = append(procBad, d.Name)
			}
		}
		ids := threadIDs(pid)
		total = len(ids)
		opened = openCount(ids, windows.THREAD_SUSPEND_RESUME|windows.THREAD_SET_CONTEXT)
	}})
	if code != 0 {
		t.Fatalf("item child exit 0x%X", code)
	}
	t.Logf("ITEM same level: process rights granted %v; later threads opened %d/%d for suspend+set-context", procBad, opened, total)
	if len(procBad) > 0 {
		t.Fatalf("FAIL the item's process gave %v to a same-level program", procBad)
	}
}

// TestSetLevelRaisesOnly: setLevel never lowers a token.
func TestSetLevelRaisesOnly(t *testing.T) {
	var self, tok windows.Token
	if err := windows.OpenProcessToken(windows.CurrentProcess(), windows.TOKEN_DUPLICATE|windows.TOKEN_QUERY, &self); err != nil {
		t.Fatal(err)
	}
	defer self.Close()
	if err := windows.DuplicateTokenEx(self, windows.TOKEN_ALL_ACCESS, nil, windows.SecurityImpersonation, windows.TokenPrimary, &tok); err != nil {
		t.Fatal(err)
	}
	defer tok.Close()
	before, err := levelOf(tok)
	if err != nil {
		t.Fatal(err)
	}
	if err := setLevel(tok, lowIL); err != nil {
		t.Fatal(err)
	}
	if after, _ := levelOf(tok); after != before {
		t.Fatalf("level changed %d -> %d; setLevel must only raise", before, after)
	}
}

// TestLockdownParts reports which part of the lock-down a Go child cannot run
// under (logged, not failed: the verdict is TestGoChildUnderLockdown). The plain
// run is the control that shows the harness itself works.
func TestLockdownParts(t *testing.T) {
	for _, c := range []struct {
		name string
		o    opt
	}{
		{"plain", opt{}},
		{"process-rights-only", opt{procSD: true}},
		{"first-thread-rights-only", opt{threadSD: true}},
		{"default-rights-only", opt{launchDefault: true}},
		// Which default rights for Jake are enough for a Go program to start:
		{"default read+wait 0x120000 + read-attrs/query", opt{defMask: 0x00120000 | 0x0800 | 0x0040}},
		{"default generic read+execute", opt{defMask: windows.GENERIC_READ | windows.GENERIC_EXECUTE}},
		{"default generic read+write+execute", opt{defMask: windows.GENERIC_READ | windows.GENERIC_WRITE | windows.GENERIC_EXECUTE}},
		{"default generic all", opt{defMask: windows.GENERIC_ALL}},
	} {
		code, errs := startOpt(t, c.o)
		t.Logf("PART %s: exit %d (0x%X) %s", c.name, code, code, errs)
	}
}

// TestInjectionProbe: with each candidate default rights plus the launch's
// process and first-thread rights, can a program running as the same user open
// the child's threads for suspend + set-context? Once at this test's own level
// and once lowered to Medium (where Jake's ordinary programs and agents run).
// Logged, not failed: it is the evidence for the fix decision.
func TestInjectionProbe(t *testing.T) {
	for _, c := range []struct {
		name string
		mask uint32
	}{
		{"generic read+execute", windows.GENERIC_READ | windows.GENERIC_EXECUTE},
		{"generic all", windows.GENERIC_ALL},
	} {
		var same, med [2]int
		code, _ := startOpt(t, opt{procSD: true, threadSD: true, defMask: c.mask, probe: func(pid uint32) {
			same[0], same[1] = threadAccess(t, pid, "")
			med[0], med[1] = threadAccess(t, pid, mediumIL)
		}})
		t.Logf("PROBE %s: child exit %d; same level opened %d/%d threads; Medium opened %d/%d", c.name, code, same[0], same[1], med[0], med[1])
	}
	var tok windows.Token
	windows.OpenProcessToken(windows.CurrentProcess(), windows.TOKEN_QUERY, &tok)
	defer tok.Close()
	t.Logf("PROBE test runs elevated: %v", tok.IsElevated())
}

// TestExitWhyFixed: the copied-off log gets only fixed phrases, never program text.
func TestExitWhyFixed(t *testing.T) {
	seen := map[string]bool{}
	for _, c := range []uint32{0, 1, 2, 0xC0000005, 0xC0000142, 3, 0xDEADBEEF} {
		seen[ExitWhy(c)] = true
	}
	if len(seen) != 6 || !seen["stopped (other exit code)"] {
		t.Fatalf("unexpected phrases: %v", seen)
	}
}
