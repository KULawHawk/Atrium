//go:build !windows

package pccheck

import "errors"

// WinProc is unavailable off Windows; every call fails.
type WinProc struct{}

var errNotWindows = errors.New("process check runs only on Windows")

// Elevated fails off Windows.
func (WinProc) Elevated() (bool, error) { return false, errNotWindows }

// Find fails off Windows.
func (WinProc) Find(string) (uint32, error) { return 0, errNotWindows }

// Open fails off Windows.
func (WinProc) Open(uint32, uint32) error { return errNotWindows }
