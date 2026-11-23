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
func startLocked(t *testing.T) (uint32, string) { return startWith(t, true, true, true) }

// startWith turns each part of the lock-down on or off (the diagnostic below).
func startWith(t *testing.T, procSD, threadSD, defRights bool) (uint32, string) {
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
	if defRights {
		if err := applyLockdown(tok, user); err != nil {
			t.Fatal(err)
		}
	}
	saP, saT, err := lockdownAttrs(user)
	if err != nil {
		t.Fatal(err)
	}
	if !procSD {
		saP = nil
	}
	if !threadSD {
		saT = nil
	}
	inherit := &windows.SecurityAttributes{Length: uint32(unsafe.Sizeof(windows.SecurityAttributes{})), InheritHandle: 1}
	var er, ew windows.Handle
	if err := windows.CreatePipe(&er, &ew, inherit, 0); err != nil {
		t.Fatal(err)
	}
	windows.SetHandleInformation(er, windows.HANDLE_FLAG_INHERIT, 0)
	exe, _ := os.Executable()
	env := append(os.Environ(), "PHONERUNNER_LOCKDOWN_CHILD=1")
	si := &windows.StartupInfo{Cb: uint32(unsafe.Sizeof(windows.StartupInfo{})), Flags: windows.STARTF_USESTDHANDLES, StdOutput: ew, StdErr: ew}
	exe16, _ := windows.UTF16PtrFromString(exe)
	cmd16, _ := windows.UTF16PtrFromString(windows.ComposeCommandLine([]string{exe}))
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
	if ev, _ := windows.WaitForSingleObject(pi.Process, 60000); ev != windows.WAIT_OBJECT_0 {
		windows.TerminateProcess(pi.Process, 1)
		t.Fatal("child still running after 60 s")
	}
	var code uint32
	windows.GetExitCodeProcess(pi.Process, &code)
	return code, <-done
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

// TestLockdownParts reports which part of the lock-down a Go child cannot run
// under (logged, not failed: the verdict is TestGoChildUnderLockdown). The plain
// run is the control that shows the harness itself works.
func TestLockdownParts(t *testing.T) {
	for _, c := range []struct {
		name     string
		p, th, d bool
	}{
		{"plain", false, false, false},
		{"process-rights-only", true, false, false},
		{"first-thread-rights-only", false, true, false},
		{"default-rights-only", false, false, true},
	} {
		code, errs := startWith(t, c.p, c.th, c.d)
		t.Logf("PART %s: exit %d (0x%X) %s", c.name, code, code, errs)
	}
}
