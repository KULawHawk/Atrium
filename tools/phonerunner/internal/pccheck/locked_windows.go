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

// Find returns the first process whose image name is exe.
func (WinProc) Find(exe string) (uint32, error) {
	snap, err := windows.CreateToolhelp32Snapshot(windows.TH32CS_SNAPPROCESS, 0)
	if err != nil {
		return 0, err
	}
	defer windows.CloseHandle(snap)
	var e windows.ProcessEntry32
	e.Size = uint32(unsafe.Sizeof(e))
	for err = windows.Process32First(snap, &e); err == nil; err = windows.Process32Next(snap, &e) {
		if strings.EqualFold(windows.UTF16ToString(e.ExeFile[:]), exe) {
			return e.ProcessID, nil
		}
	}
	return 0, errors.New("no such process")
}

// Open tries to open pid with access and closes it again.
func (WinProc) Open(pid, access uint32) error {
	h, err := windows.OpenProcess(access, false, pid)
	if err != nil {
		return err
	}
	return windows.CloseHandle(h)
}
