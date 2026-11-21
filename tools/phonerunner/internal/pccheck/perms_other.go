//go:build !windows

package pccheck

// ReadPerms is unavailable off Windows.
func ReadPerms(string) (Perms, error) { return Perms{}, ErrUnsupportedPerms }
