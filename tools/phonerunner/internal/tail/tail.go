// Package tail reads the last lines of a text file, redacted.
package tail

import (
	"bytes"
	"io"
	"os"
	"strings"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/redact"
)

// MaxRead caps how much of the file end is read.
const MaxRead = 256 * 1024

// Lines returns up to n last lines of path with key-like text removed.
func Lines(path string, n int) ([]string, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	return fromSeeker(f, n)
}

func fromSeeker(r io.ReadSeeker, n int) ([]string, error) {
	size, err := r.Seek(0, io.SeekEnd)
	if err != nil {
		return nil, err
	}
	start := int64(0)
	if size > MaxRead {
		start = size - MaxRead
	}
	if _, err := r.Seek(start, io.SeekStart); err != nil {
		return nil, err
	}
	data, err := io.ReadAll(r)
	if err != nil {
		return nil, err
	}
	data = bytes.ReplaceAll(data, []byte("\r\n"), []byte("\n"))
	text := strings.TrimRight(string(data), "\n")
	if text == "" {
		return []string{}, nil
	}
	all := strings.Split(text, "\n")
	if start > 0 && len(all) > 1 {
		all = all[1:] // first line is probably cut
	}
	if len(all) > n {
		all = all[len(all)-n:]
	}
	out, _ := redact.Lines(all)
	return out, nil
}
