# PhoneRunner

Lets Jake watch his Windows PC from his Android phone over his private Tailscale network:
which window is in front, whether the PC is locked, the latest screenshot, the last
lines of chosen log files, and whether results are being copied off the PC.

It also has a **Run button** (Decision 235): staged items run only on his own tap plus his
phone unlock (a passkey), only while the PC is already unlocked, and only after he turns the
button on at the desk, which first re-checks "Always notify" (T-01C). Agents can only stage
items. The control panel, the command box and the picture filter come in later PRs
(plan: `/mnt/project-files/phone-runner-plan/PLAN_phone_run_button_2026-11-20.md`).

This is its own Go module. It touches no Atrium Python code, contract or registry entry.

## How it is put together

| Part | Runs as | Does |
|---|---|---|
| `phonerunner-service.exe` | Windows service, SYSTEM | Joins Jake's tailnet as its own device `phonerunner` (Tailscale `tsnet`, **no localhost port**). Serves the page over HTTPS. Lets in only Jake's paired phone, identified by Tailscale itself (device ID + login), never by a header. Writes the append-only log, status and heartbeat. Sends fixed-text phone alerts. |
| `phonerunner-session.exe` | Jake, in his desktop session | Started by the service with locked-down process rights (Jake gets only query + stop). Reports the front window, lock state and screenshots over a pipe only it holds. The service labels everything it says "reported by the session process". |

Store: `C:\ProgramData\PhoneRunner\` (SYSTEM + Administrators write, Jake read; the Run button's `inbox\` and `work\` are Jake-writable, see below). Folders Jake (and so any agent) **cannot read**: `tsnet\` (Tailscale identity), `private\` (`config.json`, which holds the alert topic, a bearer secret), `captures\` (pictures). `ack\` is the one folder Jake's agents may write, for the copy-off acknowledgement. The session part reads only `session.json` (capture intervals and window rules; no secret).

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
- No control panel, command box, or lock-screen helper yet. No per-item time limit yet (the plan's "time limit from header"); Stop is the limit for now.
- The Windows parts (`internal/winsvc`, `capture_windows.go`, the service entry point) are cross-compiled and vetted here but **have never run**; they are exercised on the PC by the install tests below.

## Copy-off and PC checks (PR 2)

Two more programs, both run as Jake, no elevation, change nothing on the PC except their own outbox and the store's `ack\` file, and print one PASS/FAIL line:

- `phonerunner-copyoff stage --outbox <dir>` copies new **whole** log lines (second pass of the key filter, masked spans counted), `status.json` (no window titles, and no watched-log lines unless that log is marked `may_copy`, off by default) and `heartbeat.json` into a new `batch_NNNNNN\` folder with `MANIFEST.json` (size + sha256 per file, files over 10 MB flagged for splitting, log capped at 8 MB per batch). The PC lane sends that folder to the share, then runs `phonerunner-copyoff ack --outbox <dir> --manifest <sha256>`: **only after checking every file's sha256 on the share against `MANIFEST.json`**. `ack` re-checks the PC-side files (it cannot see the share) and writes `ack\copy_ack.json` with the batch number and manifest sha256, labelled as the lane's report. The page flags an ack that claims more bytes than the log holds. One batch at a time; staging again before the ack returns the same batch. A shrunken log, a changed manifest or a changed batch file stops with "tell Jake". Nothing is deleted; a folder left by a failed attempt is kept and the next attempt uses a `_retryN` name. **Pictures are never copied by this tool.**
- `phonerunner-check log` (T-11: every log line whole, valid and in order; a restart restarts the sequence at 1) and `phonerunner-check refused --url <page>` (T-06: this PC gets 403 "Not allowed", and the refusal page names nothing on the PC).

## Screen text (PR 4, off by default)

The page can show the words in the front window, read through Windows UI Automation (the accessibility interface screen readers use), so the coordinator can follow a run without a picture.

- **Off until T-10 passes on the PC.** `screen_text_seconds` in `private\config.json` is 0 by default. When on, it is 2–3600.
- **Same withholding as pictures.** A window matching a deny rule (patient words, DOB/MRN, dates, key and password windows) sends no text, only `paused: <reason>`. The service re-checks that and the lock state itself.
- **Only what is on screen.** It reads the visible part of text areas (not the whole document), skips password boxes entirely, walks at most 400 window parts level by level, and gives up on a window that does not answer within 5 seconds.
- **Limits.** At most 200 lines of 300 characters each. Every line goes through the same key redaction as logs.
- **Discarded on window change.** If the front window changed while it was being read, the text is thrown away.
- **Never in the copied file.** `status.json` shows the hold note instead of screen text, like window titles. This stays until a patient filter exists.
- [U] The UI Automation reader is Windows code that compiles but has never run. T-10 is the PC test: a Notepad window with known synthetic text shows on the page; a long document scrolled to its middle shows only the visible lines; a window with a password box never shows that box's name or contents; and a denied window shows only the pause note.

## Run button approval check (PR 5, part 1: the check only, not yet wired to a page)

`internal/approve` is the check every Run tap must pass. It uses the go-webauthn library (BSD-3-Clause) for the passkey cryptography.

- **One tap, one signature.** Each tap gets a fresh random challenge, stored against the exact request: the item, the sha256 of its manifest, the action, and the Tailscale device that tapped. The phone signs it only after Jake unlocks the phone, because user verification is required.
- **Refused:**
  - a second use of the same answer (T-03);
  - an answer after 2 minutes (T-04);
  - an answer from a device other than the one that tapped;
  - a signature without the phone unlock, or one made for another web address;
  - a passkey whose counter went backwards (a copied passkey);
  - any change to the item's files between the tap and the answer.
- **Random challenge on purpose.** The library warns that a challenge derived from the request weakens it. The stored, single-use mapping binds the signature to the request just as tightly.
- **Registration.** A passkey can be added only while a 5-minute window is open (opened at the desk), and only from the phone's Tailscale device; one from the PC is refused (T-17). Only one is allowed per window: a second arrival refuses both and closes the window. The new passkey is stored only after Jake types its 8-character code at the desk, the same code his phone shows.
- **Storage.** Passkeys live in `private\passkeys.json` (SYSTEM and Administrators only). A damaged file stops the service rather than starting with none.
- **Under "Always notify" (Decision 274):** no PIN is stored. The page will carry this risk note: *Your PC uses "Always notify". It closes the known quiet routes to admin rights. Microsoft still does not treat the Windows prompt as a security wall, so a program running as you might one day find a way to admin without a prompt. If that happened, it could read the phone tool's private files and fake a tap. The tool shows every run on your phone and logs it, and it never stores your PIN.*

## Staged items and their manifest (PR 6, part 2a: no page or run yet)

`internal/inbox` reads what lanes stage for the Run button. Each item is a folder: `item.json` (title, claimed_by, entry `.ps1`, estimate_time, estimate_cost, needs_desktop), the entry script, and any other files.

- **Manifest.** Every file with its sha256, in path order, in the same form `sha256sum` prints. The manifest sha256 is what a tap approves. `item.json` is in the manifest, so the entry script and its settings are pinned too.
- **Run is refused, with the reason shown, when:**
  - the header is missing a title or claimed_by, or has a field the tool does not know;
  - the entry is not a `.ps1` file in the item folder itself;
  - the item contains a link or special file, a file over 10 MB, or more than 200 files.
- **Estimates.** A missing time or cost estimate shows "not stated" in red.
- **Badges (plan 6.4), written by the tool, not the proposer.** Installs software · reads a key or secret · starts a billed service · deletes files · changes Windows settings · needs a Windows security box · **REMOTE CODE** (`iex`, downloads, `eval(`, base64 blobs). The badges come from a pattern match: they help, but they prove nothing, and the coordinator's read-through stays.
- **Changes since the last approved version.** Shown per file (added, changed, removed), with a line diff of text files (up to 2,000 lines each).
- **Unread files.** Files the scan cannot read (anything that is not a text type, such as `.dll`, `.exe`, `.js` or `.vbs`) are named in their own badge.
- **Copying what was approved.** `CopyApproved` copies the item into a new store folder. Before reading anything, it checks the list against the approved manifest sha256 and refuses any path that is absolute, has a drive or `..`, or contains a backslash, colon or empty segment. The list it copies is the service's own snapshot from when the tap began, never one sent back by the page. It hashes the bytes it writes, refuses on any difference, and re-checks that no file appeared or vanished in the inbox. The run (next PR) uses only that copy.
- **Approval actions.** Taps approve only `run`, `stop` or `resume`; anything else is refused.
- **Threat note.** Passkey registration accepts the "none" attestation format, so the tool cannot prove which phone model made the passkey. What stops a passkey made elsewhere is the registration window: it opens only at the desk, accepts only the phone's Tailscale device and only one passkey, and Jake must confirm the code. The device check also stays on every tap, because Android passkeys sync between devices.

## Running an approved item (PR 7, part 2b: the runner, not yet on the page)

`internal/runner` runs one approved item at a time; `winsvc.StartItem` starts it on the PC.

- **Fixed command.** The tool decides what runs, not the item: `%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File <approved copy>\<entry>`.
- **Separate folders.**
  - The working folder is the approved copy, which Jake's account can read but not change.
  - TEMP is the run's own work folder, kept apart from the approved files.
- **Clean environment.** Only `SystemRoot`, `windir`, a system-only `PATH`, `PATHEXT`, a system-only `PSModulePath`, `TEMP`/`TMP` and `PHONERUNNER=1`. Nothing comes from Jake's profile: no user `PATH`, no `USERPROFILE`. `PSModulePath` is set on purpose to `%SystemRoot%\System32\WindowsPowerShell\v1.0\Modules`: left unset, Windows PowerShell adds the user-writable `Documents\WindowsPowerShell\Modules`, from which a planted module could load.
- **Where it runs.** In Jake's desktop session, with the same locked process and thread rights as the session part (T-16 applies to items too). The item sits in a kill-on-close job, so **Stop ends the whole tree**, and nothing an item started that way survives the service. Stop is approved by a tap, like Run.
- **Output stays on the PC by default.**
  - stdout and stderr come down one pipe, kept line by line: the last 200 lines are shown, and each line is cut at 4,096 characters.
  - Every line is key-redacted, then kept on the PC only (the page and a PC-only output file). It is **not** written to the event log, which is copied off the PC.
  - An item can set `"output_may_copy": true` in item.json to let its output lines into the event log as `run.line` events. It is off unless the item says so, and the run's end record notes which way it went.
  - The page shows the exit code, whether it was stopped, the line count, and how many key-like spans were blanked.
- **One at a time.** A second Run while one is going is refused.
- **Exit is seen at once.** The runner waits on the main process while it reads output, so a run ends when the main process ends, even if a leftover child still holds the pipe. On the PC, the main process ending closes only the job, which ends that child and so releases the pipe; the runner then reads the pipe to its end and only after that closes it, so lines printed just before exit are not lost.
- **Honest limits:**
  - Programs started through WMI or CIM (`Win32_Process`), the Task Scheduler (`schtasks`, `Register-ScheduledTask`), `explorer`, or a new service are started by Windows itself, outside the job, so **Stop cannot end them**. The inbox puts a "may start programs that Stop cannot end" badge on items that mention these. The scan is a pattern match and can be evaded.
  - Items that need no desktop still run as Jake. The plan's separate low-rights account for those is parked with plan B.
  - [U] The Windows launcher (job, suspended start, clean environment block) compiles but has never run. Its PC test is T-05: a dummy item that prints its environment and working folder, prints `$env:PSModulePath`, tries one call that needs `USERPROFILE` (`[Environment]::GetFolderPath('MyDocuments')`), starts a child process, and is then stopped. A second dummy item prints 500 numbered lines and exits at once. The test passes if the environment is exactly the list above, `PSModulePath` is the one system folder only, the `USERPROFILE` call shows what an item sees without it (recorded, not a failure), the working folder is the approved copy, writing into that copy fails, Stop ends the child too, and all 500 numbered lines from the second item arrive.

## The Run button on the page (PR 8, part 2c)

`internal/control` joins the approval check, the staged items and the runner; `internal/web` adds the routes and the page; `winsvc` wires them into the service.

- **What the phone shows.** "Staged items": each item's title, who staged it, time and cost (red when not stated), badges, problems, whether it is new or what changed since he last approved it, and each file's text with a line diff against the last approved copy (key-redacted, cut at 256 KB). "Running now": the run's state, exit code or "stopped by you", line count, the last 200 output lines, and **the item's badges again next to Stop**. The risk note is shown beside the Run buttons.
- **Run.**
  - The tap asks the PC for a challenge. Refused at once, with the reason, if the Run button is off, the PC is locked, the desktop watcher is not reporting, the item has a problem, or another item is running.
  - A badged item asks a second "Run it anyway?" line first (plan 6.4).
  - The PC keeps its own snapshot of the item as loaded.
  - The phone signs after Jake unlocks it. The PC checks the signature, time limit, device and manifest, re-checks the PC is ready, copies **exactly the snapshot's files** into a new folder under `approved\`, and starts the fixed command on that copy with its own `work\` folder as TEMP.
  - The file list never comes from the page.
- **Stop** is approved the same way, bound to the running item's manifest. A Stop that lands after the item already ended on its own is recorded as "already ended", not "stopped".
- **Output** goes to `private\output\<item>.log` (SYSTEM and Administrators only, never staged by copy-off; a test proves it) and to the page. It reaches the copied event log only if the item sets `"output_may_copy": true`.
- **The log** records every tap approved or refused, every copy refused, run start and end, and every passkey step. It never records output unless allowed.
- **No reading through links.** The inbox is Jake-writable and the service reads it as SYSTEM, so every inbox read (the scan, the copy, the file view) goes through `inbox.ReadInside`. It checks where the open handle really is (on Windows, `GetFinalPathNameByHandle`) and refuses any file, or item folder, that resolves outside the item, and any file with more than one hard link (a hard link's path looks inside the item, so it is refused by its link count). A link, junction or hard link swapped in after the scan cannot make the service read, show or copy a file Jake's account cannot read. Each run's TEMP folder is made new with `Mkdir`; a folder or junction planted under that name refuses the run.
- **Same-page requests only.** Every POST must be JSON with `Sec-Fetch-Site: same-origin`, and the device is always the one the tailnet names, never a value from the page.
- **Adding the phone's passkey (at the desk, about 3 minutes).** `phonerunner-service passkey` (elevated) opens a 5-minute window. On the phone, Jake taps "Add this phone's passkey" and unlocks. The phone shows an 8-character code, and he types it at the desk to store the passkey. If the phone's step fails, the page says the window is used up and the desk step must be run again. The desk command and the service talk through `private\desk\` (SYSTEM and Administrators only), so each desk step starts with his own click on the Windows prompt.
- **Turning the Run button on.** `phonerunner-service run-button on` (elevated) runs the read-only T-01C check first and refuses unless it prints PASS. Then restart the service. `run-button off` needs no check. The service also re-runs T-01C before every Run tap, so if Always notify is turned off later, Run is refused with the FAIL line. The page shows the Run button as the running service uses it ("on" or "off" with the reason); a desk change shows after the restart.
- **Staged items contain synthetic data only.** Their text and differences are shown on the phone.
- **Folders.**
  - `inbox\`: lanes stage here; Jake's account can write.
  - `approved\`: read-only to Jake.
  - `work\`: Jake can write.
  - `private\output\`, `private\desk\`, `private\passkeys.json`, `privatepproved.json` (the last approved version of each item): SYSTEM and Administrators only.
  - Install sets all of these.
- **Threat note.** Registration accepts the "none" attestation format (now also in the plan's §6.5 threat list).
- [U] The service wiring, the desk commands and the page's passkey calls are code that has never run. Their PC test is T-20 (new; it also covers the plan's T-02 no passkey, T-05 file changed after viewing, and T-09 over cellular):
  - add the passkey;
  - turn the Run button on;
  - run the T-05 dummy items from the phone;
  - Stop one;
  - check that a tap from the PC's own browser is refused;
  - check that a second Run while one is going is refused;
  - check that editing a file after the tap refuses the run;
  - from a normal window, hard-link `C:\ProgramData\PhoneRunner\private\config.json` into a staged item (`mklink /H`); expected: Windows denies the link, or the item shows a problem and Run is refused, and nothing appears under `approved\`;
  - check that a Run with no passkey registered is refused;
  - repeat one Run over cellular.
- Not yet: the plan's T-19 (refuse a long item while copy-off is behind) and a per-item time limit.

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
7. Run button (optional, when he wants it): `phonerunner-service passkey` → tap "Add this phone's passkey" on the phone → type the code → PASS. Then `phonerunner-service run-button on` → T-01C PASS → restart the service.

## Tests

`go test -cover ./...` — 100% of statements in every platform-independent package (the session program's one-line `main` aside). `phonerunner-check` covers T-06, T-11, **T-07** (`perms`, run from an **elevated** window by Jake's own click on the Windows prompt, because the private folders hold only SYSTEM and Administrators and a normal window cannot even read their permissions: owner and every permission entry on the program folder, both programs, the store, its log folder and `events.jsonl`, `status.json`, `heartbeat.json`, `session.json`, the private folders, and every file and subfolder at any depth inside `private\`, `tsnet\` and `captures\`; only SYSTEM, Administrators and TrustedInstaller may change them, and nobody else may read the private ones. Inherit-only entries, which decide what each new file allows, are judged by the same rule; the only ones skipped are CREATOR OWNER and CREATOR GROUP on inherit-only entries, which are safe because nobody untrusted can create files there. A folder it cannot list fails. The parent `C:\Program Files` is not checked; it is admin-only on a default Windows install) plus **T-07b** (`denied`, run from a **normal** window at Medium integrity as an agent would be, printing the account and level it ran as: opening `private\config.json` and listing `private\`, `tsnet\` and `captures\` must each be refused with access denied; a missing path fails because it proves nothing) and **T-16** (`locked`, run from a normal window at Medium integrity: exactly one session part must be running, since a second copy may be fake; the process opens for query but refuses create-thread, memory read/write/operation, handle duplication, create-child, set-quota, set-information, suspend, and permission or owner changes; and **every thread** refuses suspend, get/set context, set-information, impersonation, and permission or owner changes. The service launches the session part with a locked default permission on its token, so threads created after launch are protected too, not only the first one. That default also applies to anything else the session part creates, so the PC test runs a real watch cycle (a picture and a text frame reach the page) after T-16, not just a check that the process is alive. The result line names the account and integrity level it ran as. It refuses to judge when run elevated). The perms and locked readers are Windows code that has never run; their verdict logic is tested here. Still owed: T-09 page over cellular (Jake's phone).
