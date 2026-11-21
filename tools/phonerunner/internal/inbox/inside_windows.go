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
