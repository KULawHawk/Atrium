//go:build !windows

package capture

import (
	"errors"
	"testing"
)

// Off Windows the platform part is a stub.
func TestUnsupported(t *testing.T) {
	c := New()
	if _, err := c.Foreground(); !errors.Is(err, ErrUnsupported) {
		t.Fatal(err)
	}
	if _, err := c.Locked(); !errors.Is(err, ErrUnsupported) {
		t.Fatal(err)
	}
	if _, err := c.Screenshot(); !errors.Is(err, ErrUnsupported) {
		t.Fatal(err)
	}
}

func TestInitDPIOther(t *testing.T) {
	if err := InitDPI(); err != nil {
		t.Fatal(err)
	}
}
