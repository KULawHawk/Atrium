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
- A device that keeps getting refused is logged at most once a minute, with a count of skipped refusals; its login is shortened (`s***@example.com`) because the log is copied off the PC.
- Nothing is ever deleted. `uninstall` removes the service and keeps the data.
- Desk commands refuse to run without elevation, and `install` refuses unless the programs sit under `C:\Program Files\`.

## Not in this PR (honest list)

- "Screen text" is the front window's **title** only; full text through Windows UI Automation comes later.
- Window rules check the **front window only**. A key page or patient file in a side window or on a second monitor is still in the picture (the Settings info box says so). Pictures stay on the PC and phone until the picture filter handles this.
- The key filter cannot spot a short password with no label (for example a bare `hunter2`).
- Title rules are a starting list; a patient file whose title has no name pattern, date or "patient" still shows on the phone (never in a copied file).
- No Run button, control panel, command box, passkey, or lock-screen helper.
- The Windows parts (`internal/winsvc`, `capture_windows.go`, the service entry point) are cross-compiled and vetted here but **have never run**; they are exercised on the PC by the install tests below.

## Copy-off and PC checks (PR 2)

Two more programs, both run as Jake, no elevation, change nothing on the PC except their own outbox and the store's `ack\` file, and print one PASS/FAIL line:

- `phonerunner-copyoff stage --outbox <dir>` copies new **whole** log lines (second pass of the key filter, masked spans counted), `status.json` (no window titles, and no watched-log lines unless that log is marked `may_copy`, off by default) and `heartbeat.json` into a new `batch_NNNNNN\` folder with `MANIFEST.json` (size + sha256 per file, files over 10 MB flagged for splitting, log capped at 8 MB per batch). The PC lane sends that folder to the share, then runs `phonerunner-copyoff ack --outbox <dir> --manifest <sha256>`: **only after checking every file's sha256 on the share against `MANIFEST.json`**. `ack` re-checks the PC-side files (it cannot see the share) and writes `ack\copy_ack.json` with the batch number and manifest sha256, labelled as the lane's report. The page flags an ack that claims more bytes than the log holds. One batch at a time; staging again before the ack returns the same batch. A shrunken log, a changed manifest or a changed batch file stops with "tell Jake". Nothing is deleted; a folder left by a failed attempt is kept and the next attempt uses a `_retryN` name. **Pictures are never copied by this tool.**
- `phonerunner-check log` (T-11: every log line whole, valid and in order; a restart restarts the sequence at 1) and `phonerunner-check refused --url <page>` (T-06: this PC gets 403 "Not allowed", and the refusal page names nothing on the PC).

## Screen text (PR 4, off by default)

The page can show the words in the front window, read through Windows UI Automation (the accessibility interface screen readers use), so the coordinator can follow a run without a picture.

- **Off until T-10 passes on the PC.** `screen_text_seconds` in `private\config.json` is 0 by default. When on, it is 2–3600.
- **Same withholding as pictures.** A window matching a deny rule (patient words, DOB/MRN, dates, key and password windows) sends no text, only `paused: <reason>`. The service re-checks that and the lock state itself.
- **Limits.** At most 200 lines of 300 characters each. Every line goes through the same key redaction as logs.
- **Discarded on window change.** If the front window changed while it was being read, the text is thrown away.
- **Never in the copied file.** `status.json` shows the hold note instead of screen text, like window titles. This stays until a patient filter exists.
- [U] The UI Automation reader is Windows code that compiles but has never run. T-10 is the PC test: a Notepad window with known synthetic text shows on the page, and a denied window shows only the pause note.

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

`go test -cover ./...` — 100% of statements in every platform-independent package (the session program's one-line `main` aside). `phonerunner-check` covers T-06, T-11, **T-07** (`perms`, run from an **elevated** window by Jake's own click on the Windows prompt, because the private folders hold only SYSTEM and Administrators and a normal window cannot even read their permissions: owner and every permission entry on the program folder, both programs, the store, its log folder and `events.jsonl`, `status.json`, `heartbeat.json`, `session.json`, the private folders, and every file and subfolder at any depth inside `private\`, `tsnet\` and `captures\`; only SYSTEM, Administrators and TrustedInstaller may change them, and nobody else may read the private ones. Inherit-only entries, which decide what each new file allows, are judged by the same rule; the only ones skipped are CREATOR OWNER and CREATOR GROUP on inherit-only entries, which are safe because nobody untrusted can create files there. A folder it cannot list fails. The parent `C:\Program Files` is not checked; it is admin-only on a default Windows install) plus **T-07b** (`denied`, run from a **normal** window at Medium integrity as an agent would be, printing the account and level it ran as: opening `private\config.json` and listing `private\`, `tsnet\` and `captures\` must each be refused with access denied; a missing path fails because it proves nothing) and **T-16** (`locked`, run from a normal window at Medium integrity: exactly one session part must be running, since a second copy may be fake; the process opens for query but refuses create-thread, memory read/write/operation, handle duplication, create-child, set-quota, set-information, suspend, and permission or owner changes; and **every thread** refuses suspend, get/set context, set-information, impersonation, and permission or owner changes. The service launches the session part with a locked default permission on its token, so threads created after launch are protected too, not only the first one. That default also applies to anything else the session part creates, so the PC test runs a real watch cycle (a picture and a text frame reach the page) after T-16, not just a check that the process is alive. The result line names the account and integrity level it ran as. It refuses to judge when run elevated). The perms and locked readers are Windows code that has never run; their verdict logic is tested here. Still owed: T-09 page over cellular (Jake's phone).
