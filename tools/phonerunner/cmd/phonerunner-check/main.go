// Command phonerunner-check runs PC install tests that need no elevation and
// change nothing. Each prints one PASS or FAIL line.
//
//	phonerunner-check log [--store <dir>]   T-11: the event log is whole and in order
//	phonerunner-check refused --url <page>  T-06: this PC is refused by the page
//	phonerunner-check perms                 T-07: agents cannot change the programs or
//	                                        store, nor read its private folders
//	phonerunner-check locked                T-16: agents cannot open the running session
//	                                        part for injection (run NOT elevated)
package main

import (
	"context"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/pccheck"
)

func main() {
	os.Exit(run(os.Args[1:], os.Stdout, deps{client: &http.Client{Timeout: 20 * time.Second}, read: pccheck.ReadPerms, proc: pccheck.WinProc{}}))
}

type deps struct {
	client *http.Client
	read   pccheck.Reader
	proc   pccheck.Proc
}

func run(args []string, out io.Writer, d deps) int {
	known := map[string]bool{"log": true, "refused": true, "perms": true, "locked": true}
	if len(args) == 0 || !known[args[0]] {
		fmt.Fprintln(out, "FAIL usage: phonerunner-check log [--store <dir>] | refused --url <page address> | perms [--program-dir <dir>] [--store <dir>] | locked")
		return 2
	}
	fs := flag.NewFlagSet("phonerunner-check "+args[0], flag.ContinueOnError)
	fs.SetOutput(out)
	storeDir := fs.String("store", `C:\ProgramData\PhoneRunner`, "PhoneRunner store folder")
	url := fs.String("url", "", "the phone page address, https://phonerunner.<tailnet>.ts.net/")
	programDir := fs.String("program-dir", `C:\Program Files\PhoneRunner`, "folder holding the two programs")
	if err := fs.Parse(args[1:]); err != nil {
		return 2
	}
	var r pccheck.Result
	switch args[0] {
	case "log":
		r = pccheck.LogIntact(filepath.Join(*storeDir, "log", "events.jsonl"))
	case "perms":
		r = pccheck.CheckPerms(d.read, pccheck.Targets(*programDir, *storeDir))
	case "locked":
		r = pccheck.CheckLocked(d.proc, "phonerunner-session.exe")
	default:
		if *url == "" {
			fmt.Fprintln(out, "FAIL --url is required")
			return 2
		}
		r = pccheck.Refused(context.Background(), d.client, *url)
	}
	fmt.Fprintln(out, r.Line())
	if !r.Pass {
		return 1
	}
	return 0
}
