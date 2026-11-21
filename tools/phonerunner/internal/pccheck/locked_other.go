//go:build !windows

package pccheck

import "errors"

// WinProc is unavailable off Windows; every call fails.
type WinProc struct{}

var errNotWindows = errors.New("process check runs only on Windows")

// Elevated fails off Windows.
func (WinProc) Elevated() (bool, error) { return false, errNotWindows }

// Identity fails off Windows.
func (WinProc) Identity() (string, string, error) { return "", "", errNotWindows }

// FindAll fails off Windows.
func (WinProc) FindAll(string) ([]uint32, error) { return nil, errNotWindows }

// Threads fails off Windows.
func (WinProc) Threads(uint32) ([]uint32, error) { return nil, errNotWindows }

// OpenThread fails off Windows.
func (WinProc) OpenThread(uint32, uint32) error { return errNotWindows }

// Open fails off Windows.
func (WinProc) Open(uint32, uint32) error { return errNotWindows }
