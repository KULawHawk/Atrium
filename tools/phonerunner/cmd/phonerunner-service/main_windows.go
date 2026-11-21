//go:build windows

// Command phonerunner-service is the SYSTEM service plus its desk commands.
//
//	phonerunner-service install [--user NAME]   elevated, once: store + permissions + service
//	phonerunner-service login                   elevated: join the tailnet (prints Tailscale's sign-in link)
//	phonerunner-service pair NODEID LOGIN       elevated: allow Jake's phone (type YES to confirm)
//	phonerunner-service passkey                 elevated: add the phone's passkey (5-minute window, code check)
//	phonerunner-service run-button on|off       elevated: on re-checks Always notify (T-01C) first
//	phonerunner-service uninstall               elevated: remove the service, keep all data
//	phonerunner-service version
//
// Each desk command prints PASS or FAIL lines.
package main

import (
	"bufio"
	"flag"
	"fmt"
	"os"
	"path/filepath"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/service"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/winsvc"
)

func main() {
	if ok, err := winsvc.IsService(); err == nil && ok {
		exe, _ := os.Executable()
		if err := winsvc.RunService(filepath.Dir(exe)); err != nil {
			os.Exit(1)
		}
		return
	}
	if len(os.Args) < 2 {
		usage()
	}
	var err error
	switch os.Args[1] {
	case "install":
		fs := flag.NewFlagSet("install", flag.ExitOnError)
		user := fs.String("user", os.Getenv("USERNAME"), "Windows user whose agents may read the store")
		fs.Parse(os.Args[2:])
		err = winsvc.Install(*user)
	case "login":
		err = winsvc.Login()
	case "pair":
		if len(os.Args) != 4 {
			usage()
		}
		err = winsvc.Pair(os.Args[2], os.Args[3], bufio.NewReader(os.Stdin))
	case "passkey":
		err = winsvc.AddPasskey(os.Stdin)
	case "run-button":
		if len(os.Args) != 3 || (os.Args[2] != "on" && os.Args[2] != "off") {
			usage()
		}
		err = winsvc.SetRunButton(os.Args[2] == "on")
	case "uninstall":
		err = winsvc.Uninstall()
	case "version":
		fmt.Println("phonerunner-service", service.Version)
	default:
		usage()
	}
	if err != nil {
		fmt.Println("FAIL", err)
		os.Exit(1)
	}
}

func usage() {
	fmt.Println("usage: phonerunner-service install [--user NAME] | login | pair NODEID LOGIN | passkey | run-button on|off | uninstall | version")
	os.Exit(2)
}
