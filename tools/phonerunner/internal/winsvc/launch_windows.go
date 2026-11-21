//go:build windows

package winsvc

import (
	"errors"
	"fmt"
	"os"
	"unsafe"

	"golang.org/x/sys/windows"
)

// Child is a running session part or item.
type Child struct {
	Process windows.Handle
	PID     uint32
	Out     *os.File       // read end of the pipe; only the child holds the write end
	Job     windows.Handle // 0 unless launched with Job: the whole process tree
}

// Close releases the parent's handles. Closing the job ends the item's tree
// (kill-on-close), so an item never outlives the service.
func (c *Child) Close() {
	c.Out.Close()
	windows.CloseHandle(c.Process)
	if c.Job != 0 {
		windows.CloseHandle(c.Job)
	}
}

// Stop ends the child, and its whole tree when it has a job.
func (c *Child) Stop() error {
	if c.Job != 0 {
		return windows.TerminateJobObject(c.Job, 1)
	}
	return windows.TerminateProcess(c.Process, 1)
}

// Opts adjusts a launch. The zero value is the session part's launch.
type Opts struct {
	Dir         string   // working folder ("" = inherit)
	Env         []string // the whole environment ("" = the user's own block)
	StderrToOut bool     // send stderr down the same pipe as stdout
	Job         bool     // put the child in a kill-on-close job object
}

// envBlock builds a Windows environment block.
func envBlock(env []string) *uint16 {
	var b []uint16
	for _, e := range env {
		u, _ := windows.UTF16FromString(e) // includes the trailing 0
		b = append(b, u...)
	}
	b = append(b, 0)
	return &b[0]
}

// newKillJob makes a job that ends every process in it when its handle closes.
func newKillJob() (windows.Handle, error) {
	j, err := windows.CreateJobObject(nil, nil)
	if err != nil {
		return 0, err
	}
	info := windows.JOBOBJECT_EXTENDED_LIMIT_INFORMATION{}
	info.BasicLimitInformation.LimitFlags = windows.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
	if _, err := windows.SetInformationJobObject(j, windows.JobObjectExtendedLimitInformation, uintptr(unsafe.Pointer(&info)), uint32(unsafe.Sizeof(info))); err != nil {
		windows.CloseHandle(j)
		return 0, err
	}
	return j, nil
}

// ErrNobodySignedIn means there is no interactive user to watch.
var ErrNobodySignedIn = errors.New("nobody is signed in at the PC")

// processSDDL gives SYSTEM full control and Jake (and the OWNER RIGHTS principal,
// which stops the owner rewriting the descriptor) only query-limited + terminate,
// so an agent running as Jake cannot open the session part to inject code or read
// its memory (review finding 3).
func processSDDL(userSID string) string {
	return fmt.Sprintf("D:P(A;;GA;;;SY)(A;;0x1001;;;%s)(A;;0x1001;;;OW)", userSID)
}

func threadSDDL(userSID string) string {
	return fmt.Sprintf("D:P(A;;GA;;;SY)(A;;0x0801;;;%s)(A;;0x0801;;;OW)", userSID)
}

// defaultDACL is set as the session token's default DACL, so every object the
// session part creates later (Go runtime threads above all) gets SYSTEM full
// control and Jake only read-permissions + wait: no suspend, context, or
// impersonation rights on any later thread (reviewer point on #53). OWNER RIGHTS
// is listed so the owner's implicit permission-change right is removed too.
func defaultDACL(userSID string) string {
	return fmt.Sprintf("D:P(A;;GA;;;SY)(A;;0x120000;;;%s)(A;;0x120000;;;OW)", userSID)
}

// tokenDefaultDACL is TOKEN_DEFAULT_DACL.
type tokenDefaultDACL struct{ DefaultDacl *windows.ACL }

// LaunchSession starts exe in the active console session as the signed-in user.
func LaunchSession(exe string, args []string) (*Child, error) { return Launch(exe, args, Opts{}) }

// Launch is LaunchSession with options (used for approved items).
func Launch(exe string, args []string, o Opts) (*Child, error) {
	sess := windows.WTSGetActiveConsoleSessionId()
	if sess == 0xFFFFFFFF {
		return nil, ErrNobodySignedIn
	}
	var userTok windows.Token
	if err := windows.WTSQueryUserToken(sess, &userTok); err != nil {
		return nil, fmt.Errorf("%w (%v)", ErrNobodySignedIn, err)
	}
	defer userTok.Close()
	// Work on a private copy so the change below never touches Jake's own token.
	var tok windows.Token
	if err := windows.DuplicateTokenEx(userTok, windows.MAXIMUM_ALLOWED, nil, windows.SecurityImpersonation, windows.TokenPrimary, &tok); err != nil {
		return nil, fmt.Errorf("launch: token copy: %w", err)
	}
	defer tok.Close()
	tu, err := tok.GetTokenUser()
	if err != nil {
		return nil, fmt.Errorf("launch: user lookup: %w", err)
	}
	userSID := tu.User.Sid.String()
	sdD, err := windows.SecurityDescriptorFromString(defaultDACL(userSID))
	if err != nil {
		return nil, fmt.Errorf("launch: default rights: %w", err)
	}
	dacl, _, err := sdD.DACL()
	if err != nil {
		return nil, fmt.Errorf("launch: default rights: %w", err)
	}
	tdd := tokenDefaultDACL{DefaultDacl: dacl}
	if err := windows.SetTokenInformation(tok, windows.TokenDefaultDacl, (*byte)(unsafe.Pointer(&tdd)), uint32(unsafe.Sizeof(tdd))); err != nil {
		return nil, fmt.Errorf("launch: default rights: %w", err)
	}

	inherit := &windows.SecurityAttributes{Length: uint32(unsafe.Sizeof(windows.SecurityAttributes{})), InheritHandle: 1}
	var r, w windows.Handle
	if err := windows.CreatePipe(&r, &w, inherit, 0); err != nil {
		return nil, fmt.Errorf("launch: pipe: %w", err)
	}
	ok := false
	defer func() {
		windows.CloseHandle(w)
		if !ok {
			windows.CloseHandle(r)
		}
	}()
	if err := windows.SetHandleInformation(r, windows.HANDLE_FLAG_INHERIT, 0); err != nil {
		return nil, fmt.Errorf("launch: pipe: %w", err)
	}
	nulName, _ := windows.UTF16PtrFromString("NUL")
	nul, err := windows.CreateFile(nulName, windows.GENERIC_READ|windows.GENERIC_WRITE, 0, inherit, windows.OPEN_EXISTING, 0, 0)
	if err != nil {
		return nil, fmt.Errorf("launch: NUL: %w", err)
	}
	defer windows.CloseHandle(nul)

	sdP, err := windows.SecurityDescriptorFromString(processSDDL(userSID))
	if err != nil {
		return nil, fmt.Errorf("launch: process rights: %w", err)
	}
	sdT, err := windows.SecurityDescriptorFromString(threadSDDL(userSID))
	if err != nil {
		return nil, fmt.Errorf("launch: thread rights: %w", err)
	}
	saP := &windows.SecurityAttributes{Length: uint32(unsafe.Sizeof(windows.SecurityAttributes{})), SecurityDescriptor: sdP}
	saT := &windows.SecurityAttributes{Length: uint32(unsafe.Sizeof(windows.SecurityAttributes{})), SecurityDescriptor: sdT}

	// Inherit exactly the pipe write end and NUL, nothing else the service holds.
	attrs, err := windows.NewProcThreadAttributeList(1)
	if err != nil {
		return nil, fmt.Errorf("launch: attributes: %w", err)
	}
	defer attrs.Delete()
	handles := []windows.Handle{w, nul}
	if err := attrs.Update(windows.PROC_THREAD_ATTRIBUTE_HANDLE_LIST, unsafe.Pointer(&handles[0]), uintptr(len(handles))*unsafe.Sizeof(handles[0])); err != nil {
		return nil, fmt.Errorf("launch: attributes: %w", err)
	}

	errOut := nul
	if o.StderrToOut {
		errOut = w
	}
	desktop, _ := windows.UTF16PtrFromString(`winsta0\default`)
	si := &windows.StartupInfoEx{
		StartupInfo: windows.StartupInfo{
			Cb:        uint32(unsafe.Sizeof(windows.StartupInfoEx{})),
			Flags:     windows.STARTF_USESTDHANDLES,
			StdInput:  nul,
			StdOutput: w,
			StdErr:    errOut,
			Desktop:   desktop,
		},
		ProcThreadAttributeList: attrs.List(),
	}
	var env *uint16
	if o.Env != nil {
		env = envBlock(o.Env)
	} else {
		if err := windows.CreateEnvironmentBlock(&env, tok, false); err != nil {
			return nil, fmt.Errorf("launch: environment: %w", err)
		}
		defer windows.DestroyEnvironmentBlock(env)
	}
	var dir *uint16
	if o.Dir != "" {
		if dir, err = windows.UTF16PtrFromString(o.Dir); err != nil {
			return nil, err
		}
	}
	exe16, err := windows.UTF16PtrFromString(exe)
	if err != nil {
		return nil, err
	}
	cmd16, err := windows.UTF16PtrFromString(windows.ComposeCommandLine(append([]string{exe}, args...)))
	if err != nil {
		return nil, err
	}
	// Made last, after every step that can return early, so its handle cannot leak.
	var job windows.Handle
	if o.Job {
		if job, err = newKillJob(); err != nil {
			return nil, fmt.Errorf("launch: job: %w", err)
		}
	}
	var pi windows.ProcessInformation
	flags := uint32(windows.CREATE_UNICODE_ENVIRONMENT | windows.EXTENDED_STARTUPINFO_PRESENT | windows.CREATE_NO_WINDOW)
	if job != 0 {
		flags |= windows.CREATE_SUSPENDED // into the job before it runs a single instruction
	}
	if err := windows.CreateProcessAsUser(tok, exe16, cmd16, saP, saT, true, flags, env, dir, &si.StartupInfo, &pi); err != nil {
		if job != 0 {
			windows.CloseHandle(job)
		}
		return nil, fmt.Errorf("launch: CreateProcessAsUser: %w", err)
	}
	if job != 0 {
		if err := windows.AssignProcessToJobObject(job, pi.Process); err != nil {
			windows.TerminateProcess(pi.Process, 1)
			windows.CloseHandle(pi.Thread)
			windows.CloseHandle(pi.Process)
			windows.CloseHandle(job)
			return nil, fmt.Errorf("launch: job: %w", err)
		}
		if _, err := windows.ResumeThread(pi.Thread); err != nil {
			windows.TerminateJobObject(job, 1)
			windows.CloseHandle(pi.Thread)
			windows.CloseHandle(pi.Process)
			windows.CloseHandle(job)
			return nil, fmt.Errorf("launch: resume: %w", err)
		}
	}
	windows.CloseHandle(pi.Thread)
	ok = true
	return &Child{Process: pi.Process, PID: pi.ProcessId, Out: os.NewFile(uintptr(r), "session-pipe"), Job: job}, nil
}
