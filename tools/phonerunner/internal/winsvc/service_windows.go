//go:build windows

package winsvc

import (
	"context"
	"path/filepath"

	"golang.org/x/sys/windows/svc"
)

type handler struct{ sessionExe string }

// Execute is called by the Windows service manager.
func (h handler) Execute(_ []string, req <-chan svc.ChangeRequest, status chan<- svc.Status) (bool, uint32) {
	status <- svc.Status{State: svc.StartPending}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- Run(ctx, DefaultRoot(), h.sessionExe) }()
	status <- svc.Status{State: svc.Running, Accepts: svc.AcceptStop | svc.AcceptShutdown}
	for {
		select {
		case err := <-done:
			cancel()
			if err != nil {
				return true, 1
			}
			return false, 0
		case c := <-req:
			switch c.Cmd {
			case svc.Interrogate:
				status <- c.CurrentStatus
			case svc.Stop, svc.Shutdown:
				status <- svc.Status{State: svc.StopPending}
				cancel()
				<-done
				return false, 0
			}
		}
	}
}

// RunService hands control to the Windows service manager.
func RunService(exeDir string) error {
	return svc.Run(ServiceName, handler{sessionExe: filepath.Join(exeDir, "phonerunner-session.exe")})
}

// IsService reports whether the process was started by the service manager.
func IsService() (bool, error) { return svc.IsWindowsService() }
