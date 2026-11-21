// Package winsvc holds the Windows-only parts of the SYSTEM service: starting the
// session part in Jake's desktop session with locked-down process rights, the
// Windows service wrapper, and the desk commands (install, login, pair, uninstall).
//
// None of this can run in the cloud build box. It is cross-compiled and vetted here
// and exercised on the PC by the step-6 install tests (plan section 12), with every
// PC test a script that prints one PASS/FAIL line.
package winsvc
