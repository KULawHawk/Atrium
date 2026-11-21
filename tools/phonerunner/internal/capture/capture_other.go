//go:build !windows

package capture

// Unsupported is the non-Windows Capturer: every call fails loudly.
type Unsupported struct{}

// New returns the platform Capturer.
func New() Capturer { return Unsupported{} }

// Foreground always fails off Windows.
func (Unsupported) Foreground() (Window, error) { return Window{}, ErrUnsupported }

// Locked always fails off Windows.
func (Unsupported) Locked() (bool, error) { return false, ErrUnsupported }

// Screenshot always fails off Windows.
func (Unsupported) Screenshot() ([]byte, error) { return nil, ErrUnsupported }

// InitDPI does nothing off Windows.
func InitDPI() error { return nil }
