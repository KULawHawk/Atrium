//go:build windows

package pccheck

import (
	"errors"
	"strings"
	"unsafe"

	"golang.org/x/sys/windows"
)

// WinProc is the real Proc.
type WinProc struct{}

// Elevated reports whether this process holds an elevated token.
func (WinProc) Elevated() (bool, error) {
	return windows.GetCurrentProcessToken().IsElevated(), nil
}

// Identity returns this process's user SID and integrity level name.
func (WinProc) Identity() (string, string, error) {
	tok := windows.GetCurrentProcessToken()
	tu, err := tok.GetTokenUser()
	if err != nil {
		return "", "", err
	}
	var n uint32
	_ = windows.GetTokenInformation(tok, windows.TokenIntegrityLevel, nil, 0, &n)
	if n == 0 {
		return "", "", errors.New("integrity level unreadable")
	}
	buf := make([]byte, n)
	if err := windows.GetTokenInformation(tok, windows.TokenIntegrityLevel, &buf[0], n, &n); err != nil {
		return "", "", err
	}
	label := (*windows.Tokenmandatorylabel)(unsafe.Pointer(&buf[0]))
	return tu.User.Sid.String(), integrityName(label.Label.Sid.String()), nil
}

func integrityName(sid string) string {
	switch sid {
	case "S-1-16-4096":
		return "Low"
	case "S-1-16-8192":
		return "Medium"
	case "S-1-16-8448":
		return "Medium-Plus"
	case "S-1-16-12288":
		return "High"
	case "S-1-16-16384":
		return "System"
	}
	return sid
}

// FindAll returns every process whose image name is exe.
func (WinProc) FindAll(exe string) ([]uint32, error) {
	snap, err := windows.CreateToolhelp32Snapshot(windows.TH32CS_SNAPPROCESS, 0)
	if err != nil {
		return nil, err
	}
	defer windows.CloseHandle(snap)
	var e windows.ProcessEntry32
	e.Size = uint32(unsafe.Sizeof(e))
	var out []uint32
	for err = windows.Process32First(snap, &e); err == nil; err = windows.Process32Next(snap, &e) {
		if strings.EqualFold(windows.UTF16ToString(e.ExeFile[:]), exe) {
			out = append(out, e.ProcessID)
		}
	}
	return out, nil
}

// Threads returns the thread IDs of pid.
func (WinProc) Threads(pid uint32) ([]uint32, error) {
	snap, err := windows.CreateToolhelp32Snapshot(windows.TH32CS_SNAPTHREAD, 0)
	if err != nil {
		return nil, err
	}
	defer windows.CloseHandle(snap)
	var e windows.ThreadEntry32
	e.Size = uint32(unsafe.Sizeof(e))
	var out []uint32
	for err = windows.Thread32First(snap, &e); err == nil; err = windows.Thread32Next(snap, &e) {
		if e.OwnerProcessID == pid {
			out = append(out, e.ThreadID)
		}
	}
	return out, nil
}

// OpenThread tries to open tid with access and closes it again.
func (WinProc) OpenThread(tid, access uint32) error {
	h, err := windows.OpenThread(access, false, tid)
	if err != nil {
		return err
	}
	return windows.CloseHandle(h)
}

// Open tries to open pid with access and closes it again.
func (WinProc) Open(pid, access uint32) error {
	h, err := windows.OpenProcess(access, false, pid)
	if err != nil {
		return err
	}
	return windows.CloseHandle(h)
}
