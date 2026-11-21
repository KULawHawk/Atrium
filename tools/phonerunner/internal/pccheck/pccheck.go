// Package pccheck holds the PC install tests that can be written as plain checks,
// each giving one PASS or FAIL line (plan section 12):
//
//	T-11 LogIntact: after a crash or reboot, every log line is whole, valid JSON,
//	     in order (a restart starts the sequence again at 1), with no torn line.
//	     This is the log half of T-11; the "item shown Interrupted, never PASS"
//	     half arrives with the Run button, which is when items exist.
//	T-06 Refused:   a request from a device that is not the paired phone (for
//	     example the PC itself) gets the 403 "Not allowed" page and nothing else.
package pccheck

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
)

// Result is one test's verdict.
type Result struct {
	Test   string
	Pass   bool
	Detail string
}

// Line renders the one-line verdict.
func (r Result) Line() string {
	v := "FAIL"
	if r.Pass {
		v = "PASS"
	}
	return fmt.Sprintf("%s %s %s", v, r.Test, r.Detail)
}

func fail(test, format string, a ...any) Result {
	return Result{Test: test, Detail: fmt.Sprintf(format, a...)}
}

// LogIntact is T-11.
func LogIntact(path string) Result {
	const test = "T-11"
	data, err := os.ReadFile(path)
	if err != nil {
		return fail(test, "cannot read log: %v", err)
	}
	if len(data) == 0 {
		return fail(test, "log is empty")
	}
	if data[len(data)-1] != '\n' {
		return fail(test, "last line is torn (no line end)")
	}
	sc := bufio.NewScanner(strings.NewReader(string(data)))
	sc.Buffer(make([]byte, 64*1024), 8<<20)
	var prev int64
	lines, restarts := 0, 0
	for sc.Scan() {
		lines++
		var rec struct {
			Seq   int64  `json:"seq"`
			At    string `json:"at"`
			Event string `json:"event"`
		}
		if err := json.Unmarshal(sc.Bytes(), &rec); err != nil || rec.Seq < 1 || rec.At == "" || rec.Event == "" {
			return fail(test, "line %d is not a whole log record", lines)
		}
		switch {
		case rec.Seq == prev+1:
		case rec.Seq == 1:
			restarts++
		default:
			return fail(test, "line %d: sequence jumps from %d to %d (a line is missing)", lines, prev, rec.Seq)
		}
		prev = rec.Seq
	}
	if err := sc.Err(); err != nil {
		return fail(test, "reading log: %v", err)
	}
	return Result{Test: test, Pass: true, Detail: fmt.Sprintf("%d lines whole and in order, %d restarts", lines, restarts)}
}

// Refused is T-06. client must route through Tailscale (on the PC, the system's
// own Tailscale client does).
func Refused(ctx context.Context, client *http.Client, url string) Result {
	const test = "T-06"
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return fail(test, "bad address: %v", err)
	}
	resp, err := client.Do(req)
	if err != nil {
		return fail(test, "page not reachable (cannot prove refusal): %v", err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 64<<10))
	if resp.StatusCode != http.StatusForbidden || !strings.Contains(string(body), "Not allowed") {
		return fail(test, "expected 403 Not allowed, got %d", resp.StatusCode)
	}
	for _, leak := range []string{"/api/", "screenshot", "window"} {
		if strings.Contains(strings.ToLower(string(body)), leak) {
			return fail(test, "refusal page mentions %q", leak)
		}
	}
	return Result{Test: test, Pass: true, Detail: "this device got 403 Not allowed"}
}
