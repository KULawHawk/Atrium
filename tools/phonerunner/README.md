# PhoneRunner (watch-only, PR 1)

Lets Jake watch his Windows PC from his Android phone over his private Tailscale network:
which window is in front, whether the PC is locked, the latest screenshot, the last
lines of chosen log files, and whether results are being copied off the PC.
**Watch-only: it cannot start, stop or change anything.** The Run button, the control
panel, the command box and the lock-screen helper come in later PRs behind a per-tap
passkey (plan: `/mnt/project-files/phone-runner-plan/PLAN_phone_run_button_2026-11-20.md`,
Decisions 259–263).

This is its own Go module. It touches no Atrium Python code, contract or registry entry.

## How it is put together

| Part | Runs as | Does |
|---|---|---|
| `phonerunner-service.exe` | Windows service, SYSTEM | Joins Jake's tailnet as its own device `phonerunner` (Tailscale `tsnet`, **no localhost port**). Serves the page over HTTPS. Lets in only Jake's paired phone, identified by Tailscale itself (device ID + login), never by a header. Writes the append-only log, status and heartbeat. Sends fixed-text phone alerts. |
| `phonerunner-session.exe` | Jake, in his desktop session | Started by the service with locked-down process rights (Jake gets only query + stop). Reports the front window, lock state and screenshots over a pipe only it holds. The service labels everything it says "reported by the session process". |

Store: `C:\ProgramData\PhoneRunner\` (SYSTEM + Administrators write, Jake read). Folders Jake (and so any agent) **cannot read**: `tsnet\` (Tailscale identity), `private\` (`config.json`, which holds the alert topic, a bearer secret), `captures\` (pictures). `ack\` is the one folder Jake's agents may write, for the copy-off acknowledgement. The session part reads only `session.json` (capture intervals and window rules; no secret).

## Safety rules built in

- Only the paired phone can load anything; the PC itself and every other device get "Not allowed" (the page shows the visitor its own device ID so Jake can pair it at the desk).
- Every string shown, logged or left for copying passes the key filter (`internal/redact`): known key shapes, `Bearer` tokens, JWTs, `password=`/`token=` pairs, private-key blocks, and long random strings. 40-character hex (git commits) is kept; 64-character hex only when labelled as a hash (`sha256 …`, `hash …`, or a `sha256sum` line).
- While a key page, a Windows security screen, a password manager, or a patient-mode window is in front (`config.DefaultDenyRules`, including titles with a birth date, "DOB" or a record number), pictures pause **and the window's title and program name are replaced with `withheld: <reason>`** on the page, in the status file and in the log. The session part checks; the service checks again and drops any picture that slipped through; the session part re-reads the front window after each picture and discards it if the window changed. Locked PC: no pictures.
- **Pictures are not copied off the PC yet** (Decision 266 = A: copied only after the picture filter, built last). They sit in the admin-only `captures\` folder and show on his phone.
- **Window titles are not copied off the PC either** until a patient filter exists (coordinator ruling, strictest first). `status.json`, the status copy the PC lane takes, says "kept on the PC and phone" in place of the title.
- Alerts carry one of five fixed texts and nothing else; the page link is off by default (`ntfy_click_link`) so ntfy.sh never learns the page's address.
- A device that keeps getting refused is logged at most once a minute, with a count of skipped refusals.
- Nothing is ever deleted. `uninstall` removes the service and keeps the data.
- Desk commands refuse to run without elevation, and `install` refuses unless the programs sit under `C:\Program Files\`.

## Not in this PR (honest list)

- "Screen text" is the front window's **title** only; full text through Windows UI Automation comes later.
- Window rules check the **front window only**. A key page or patient file in a side window or on a second monitor is still in the picture (the Settings info box says so). Pictures stay on the PC and phone until the picture filter handles this.
- The key filter cannot spot a short password with no label (for example a bare `hunter2`).
- Title rules are a starting list; a patient file whose title has no name pattern, date or "patient" still shows on the phone (never in a copied file).
- No Run button, control panel, command box, passkey, or lock-screen helper.
- The copy-off script for the PC lane (it reads the store and writes `ack\copy_ack.json`).
- The Windows parts (`internal/winsvc`, `capture_windows.go`, the service entry point) are cross-compiled and vetted here but **have never run**; they are exercised on the PC by the install tests below.

## Build (cloud, reproducible)

```
./build.sh dist          # CGO off, -trimpath, empty build id; prints SHA256SUMS
```
Two builds give the same hashes. The service program is about 23 MB, over the PC lane's ~16 MB transfer cap, so it is staged in pieces under 10 MB with a sha256 for each piece.

## Install at the desk (Jake, about 15–20 min, after the PC lane stages and checks the files)

1. Copy both `.exe` files into `C:\Program Files\PhoneRunner\` (one Windows box).
2. In an elevated window: `phonerunner-service install` → PASS lines.
3. `phonerunner-service login` → open the Tailscale link it prints, approve → PASS with the page address.
4. Open the page on the phone → "Not allowed" shows the phone's device ID and login.
5. `phonerunner-service pair <device ID> <login>` → type `YES` → PASS.
6. `sc start PhoneRunner`, reload the page on the phone.

## Tests

`go test -cover ./...` — 100% of statements in every platform-independent package (the session program's one-line `main` aside). PC tests (each a script printing one PASS/FAIL line, dry-run first) arrive with the staging PR: T-06 the PC itself is refused, T-07 permissions, T-09 page over cellular, T-11 restart keeps the log, T-16 an agent cannot open the session part for writing.
