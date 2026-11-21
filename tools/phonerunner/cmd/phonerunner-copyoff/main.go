// Command phonerunner-copyoff is the PC lane's copy-off step (Hard Rule 8). It runs
// as Jake, needs no elevation, and prints one PASS or FAIL line.
//
//	phonerunner-copyoff stage --outbox <dir>
//	    PASS staged batch N: <folder> manifest sha256 <hash> (...)
//	    -> send that folder to the share, then:
//	phonerunner-copyoff ack --outbox <dir> --manifest <hash>
//	    PASS ack written: N log bytes confirmed copied off the PC
//
// --store defaults to C:\ProgramData\PhoneRunner. Pictures are never copied by
// this tool (they are in a folder it cannot read).
package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"time"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/copyoff"
)

// DefaultStore is the service's store on the PC.
const DefaultStore = `C:\ProgramData\PhoneRunner`

func main() {
	os.Exit(run(os.Args[1:], os.Stdout, time.Now))
}

func run(args []string, out io.Writer, now func() time.Time) int {
	if len(args) == 0 || (args[0] != "stage" && args[0] != "ack") {
		fmt.Fprintln(out, "FAIL usage: phonerunner-copyoff stage|ack --outbox <dir> [--store <dir>] [--manifest <sha256>]")
		return 2
	}
	fs := flag.NewFlagSet("phonerunner-copyoff "+args[0], flag.ContinueOnError)
	fs.SetOutput(out)
	storeDir := fs.String("store", DefaultStore, "PhoneRunner store folder")
	outbox := fs.String("outbox", "", "folder the PC lane sends to the share")
	manifest := fs.String("manifest", "", "sha256 of the batch MANIFEST.json that was sent (ack only)")
	if err := fs.Parse(args[1:]); err != nil {
		return 2
	}
	if *outbox == "" {
		fmt.Fprintln(out, "FAIL --outbox is required")
		return 2
	}
	c := &copyoff.Copier{Store: *storeDir, Outbox: *outbox, Now: now}
	if args[0] == "stage" {
		r, err := c.Stage()
		if err != nil {
			fmt.Fprintln(out, "FAIL", err)
			return 1
		}
		note := "new batch"
		if r.Reused {
			note = "already staged, not yet acknowledged: send it, then ack"
		}
		fmt.Fprintf(out, "PASS staged batch %d: %s manifest sha256 %s (%s; log bytes %d-%d; %d files; %d key-like spans masked; missing: %v)\n",
			r.Manifest.Batch, r.Dir, r.ManifestSHA, note, r.Manifest.LogFrom, r.Manifest.LogTo, len(r.Manifest.Files), r.Manifest.Redacted, r.Manifest.Missing)
		for _, f := range r.Manifest.Files {
			if f.NeedsSplit {
				fmt.Fprintf(out, "NOTE %s is %d bytes: split it before sending\n", f.Name, f.Bytes)
			}
		}
		return 0
	}
	r, err := c.Ack(*manifest)
	if err != nil {
		fmt.Fprintln(out, "FAIL", err)
		return 1
	}
	if r.Refreshed {
		fmt.Fprintln(out, "PASS ack refreshed: nothing new since the last batch")
		return 0
	}
	fmt.Fprintf(out, "PASS ack written: batch %d, %d log bytes confirmed copied off the PC\n", r.Manifest.Batch, r.Manifest.LogTo)
	return 0
}
