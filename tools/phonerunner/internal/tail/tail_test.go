package tail

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func write(t *testing.T, s string) string {
	t.Helper()
	p := filepath.Join(t.TempDir(), "f.log")
	if err := os.WriteFile(p, []byte(s), 0o600); err != nil {
		t.Fatal(err)
	}
	return p
}

func TestLines(t *testing.T) {
	p := write(t, "a\r\nb\nc token=abc\nd\n")
	got, err := Lines(p, 3)
	if err != nil || len(got) != 3 || got[0] != "b" || strings.Contains(got[1], "abc") || got[2] != "d" {
		t.Fatalf("%v %v", got, err)
	}
	got, _ = Lines(write(t, ""), 5)
	if len(got) != 0 {
		t.Fatalf("empty file gave %v", got)
	}
	if _, err := Lines(filepath.Join(t.TempDir(), "none"), 1); err == nil {
		t.Fatal("missing file accepted")
	}
}

func TestLargeFileDropsCutLine(t *testing.T) {
	big := strings.Repeat("x", MaxRead) + "\nlast1\nlast2\n"
	got, err := Lines(write(t, big), 10)
	if err != nil || len(got) != 2 || got[1] != "last2" {
		t.Fatalf("%d lines %v", len(got), err)
	}
}

type badSeeker struct{ failAt int; calls int }

func (b *badSeeker) Seek(off int64, whence int) (int64, error) {
	b.calls++
	if b.calls == b.failAt {
		return 0, errors.New("seek failed")
	}
	return 10, nil
}
func (b *badSeeker) Read([]byte) (int, error) { return 0, errors.New("read failed") }

func TestSeekerErrors(t *testing.T) {
	for _, at := range []int{1, 2, 3} {
		if _, err := fromSeeker(&badSeeker{failAt: at}, 1); err == nil {
			t.Errorf("failAt %d: no error", at)
		}
	}
	var _ io.ReadSeeker = &badSeeker{}
}
