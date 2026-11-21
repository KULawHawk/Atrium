// Command phonerunner-check runs PC install tests that need no elevation and
// change nothing. Each prints one PASS or FAIL line.
//
//	phonerunner-check log [--store <dir>]   T-11: the event log is whole and in order
//	phonerunner-check refused --url <page>  T-06: this PC is refused by the page
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
	os.Exit(run(os.Args[1:], os.Stdout, &http.Client{Timeout: 20 * time.Second}))
}

func run(args []string, out io.Writer, client *http.Client) int {
	if len(args) == 0 || (args[0] != "log" && args[0] != "refused") {
		fmt.Fprintln(out, "FAIL usage: phonerunner-check log [--store <dir>] | refused --url <page address>")
		return 2
	}
	fs := flag.NewFlagSet("phonerunner-check "+args[0], flag.ContinueOnError)
	fs.SetOutput(out)
	storeDir := fs.String("store", `C:\ProgramData\PhoneRunner`, "PhoneRunner store folder")
	url := fs.String("url", "", "the phone page address, https://phonerunner.<tailnet>.ts.net/")
	if err := fs.Parse(args[1:]); err != nil {
		return 2
	}
	var r pccheck.Result
	if args[0] == "log" {
		r = pccheck.LogIntact(filepath.Join(*storeDir, "log", "events.jsonl"))
	} else {
		if *url == "" {
			fmt.Fprintln(out, "FAIL --url is required")
			return 2
		}
		r = pccheck.Refused(context.Background(), client, *url)
	}
	fmt.Fprintln(out, r.Line())
	if !r.Pass {
		return 1
	}
	return 0
}
