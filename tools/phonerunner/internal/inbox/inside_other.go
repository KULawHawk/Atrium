//go:build !windows

package inbox

import (
	"fmt"
	"os"
	"syscall"
)

// finalPathOS reads the open file's real path from /proc (Linux, where the
// tests run).
func finalPathOS(f *os.File) (string, error) {
	return os.Readlink(fmt.Sprintf("/proc/self/fd/%d", f.Fd()))
}

// linksOS is the file's hard-link count.
func linksOS(_ *os.File, st os.FileInfo) (uint64, error) {
	return uint64(st.Sys().(*syscall.Stat_t).Nlink), nil
}
