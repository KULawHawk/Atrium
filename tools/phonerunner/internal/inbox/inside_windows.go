//go:build windows

package inbox

import (
	"os"

	"golang.org/x/sys/windows"
)

// finalPathOS asks Windows where the open handle really is, after every link,
// junction and mount point has been followed.
func finalPathOS(f *os.File) (string, error) {
	buf := make([]uint16, windows.MAX_LONG_PATH)
	n, err := windows.GetFinalPathNameByHandle(windows.Handle(f.Fd()), &buf[0], uint32(len(buf)), 0)
	if err != nil {
		return "", err
	}
	return windows.UTF16ToString(buf[:n]), nil
}

// linksOS is the file's hard-link count, read from the open handle.
func linksOS(f *os.File, _ os.FileInfo) (uint64, error) {
	var info windows.ByHandleFileInformation
	if err := windows.GetFileInformationByHandle(windows.Handle(f.Fd()), &info); err != nil {
		return 0, err
	}
	return uint64(info.NumberOfLinks), nil
}
