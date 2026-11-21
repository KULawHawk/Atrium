// Command phonerunner-session watches Jake's desktop and reports to the service
// over the pipe the service gave it as standard output. The service starts it in
// Jake's session; it is not meant to be started by hand.
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"time"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/capture"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/config"
)

func main() {
	os.Exit(run(os.Args[1:], os.Stdout, os.Stderr, capture.New()))
}

// reader returns c's screen-text reader when it has one.
func reader(c capture.Capturer) capture.TextReader {
	r, _ := c.(capture.TextReader)
	return r
}

func run(args []string, out, errw interface{ Write([]byte) (int, error) }, c capture.Capturer) int {
	fs := flag.NewFlagSet("phonerunner-session", flag.ContinueOnError)
	fs.SetOutput(errw)
	cfgPath := fs.String("settings", "", "session settings file (intervals and deny rules only)")
	maxRun := fs.Duration("for", 0, "stop after this long (tests)")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	cfg, err := config.LoadSession(*cfgPath)
	if err != nil {
		fmt.Fprintln(errw, "FAIL", err)
		return 1
	}
	_ = capture.InitDPI()
	ctx := context.Background()
	if *maxRun > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, *maxRun)
		defer cancel()
	}
	err = capture.Loop(ctx, c, capture.LoopConfig{
		Rules:           cfg.DenyRules,
		TextEvery:       time.Duration(cfg.CaptureTextSeconds) * time.Second,
		ShotEvery:       time.Duration(cfg.CaptureShotSeconds) * time.Second,
		ScreenTextEvery: time.Duration(cfg.ScreenTextSeconds) * time.Second,
		Reader:          reader(c),
	}, out, time.Now)
	if err != nil {
		fmt.Fprintln(errw, "FAIL", err)
		return 1
	}
	return 0
}
