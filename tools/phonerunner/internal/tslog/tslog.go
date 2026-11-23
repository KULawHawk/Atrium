// Package tslog quiets Tailscale's user messages. While a tsnet device waits for
// sign-in, Tailscale repeats the same "go to: https://login.tailscale.com/..."
// line many times a second, which floods the desk window (and would flood the
// event log). Once passes each distinct message through one time, then says
// once that it is waiting, and drops the repeats.
package tslog

import (
	"fmt"
	"strings"
	"sync"
)

// Waiting is printed once, the first time a message repeats.
const Waiting = "Waiting for you to finish signing in (the link above stays valid; this window continues by itself)..."

// Once wraps out (one finished line per call) so each distinct message is passed
// once. It is safe for concurrent use, as tsnet may log from several goroutines.
func Once(out func(line string)) func(format string, args ...any) {
	var mu sync.Mutex
	seen := map[string]bool{}
	waited := false
	return func(format string, args ...any) {
		line := strings.TrimSpace(fmt.Sprintf(format, args...))
		mu.Lock()
		defer mu.Unlock()
		if !seen[line] {
			seen[line] = true
			out(line)
			return
		}
		if !waited {
			waited = true
			out(Waiting)
		}
	}
}
