//go:build !windows

package inbox

import (
	"fmt"
	"os"
)

// finalPathOS reads the open file's real path from /proc (Linux, where the
// tests run).
func finalPathOS(f *os.File) (string, error) {
	return os.Readlink(fmt.Sprintf("/proc/self/fd/%d", f.Fd()))
}
