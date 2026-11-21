# Nestegg: the APEX suite installer for other Windows PCs

Jake, 11/20/2026 9:20 PM CT: "an entire installation suite so this can be automatically installed on other computers", then "I mean everything. Everything."
Decision 273 = A (9:29 PM CT): a **script bundle with one double-click file**. It runs in phases, each phase prints PASS/FAIL, and there is a check-only dry run.
Coordinator defaults (under "assume approved when obvious", Jake told so he can object): I3 A (a "Check for updates" button in Settings), I4 A (core + CPU readers; the rest are OFF switches), I5 A (install to `C:\Users\<name>\AdAstra\`).
Plan: project share `installer/PLAN_installer_2026-11-20.md`.

## What is here now (PR 1)

| File | What it does |
|---|---|
| `Check AdAstra.cmd` | Double-click. Runs `Check-AdAstra.ps1` and waits for a key press. |
| `Check-AdAstra.ps1` | **Phase 0, read-only.** Checks Windows version, disk, install folder, winget, Python 3.13, Git, Tesseract, Poppler, VC++ runtime, GPU (report only), TPM (report only), network reach, GitHub sign-in. It is also the installer's `-DryRun`. Prints `PASS` / `GAP` / `INFO` per line and ends `NESTEGG-CHECK: PASS` or `NESTEGG-CHECK: GAPS n`. |

It installs nothing, changes no Windows setting, deletes nothing, and reads no key or secret. It writes only its own report file, to `<InstallRoot>\.adastra\` if that folder exists, else `%TEMP%`. `tests/test_nestegg_static.py` checks those promises by reading the script text.

## What comes next (one phase per PR)

1. Phase 1, prerequisites: Python per-user, plus Git, Tesseract and the VC++ runtime through winget. Each of those three shows one Windows security box that the person clicks. Poppler is unpacked after a sha check.
2. Phase 2, code: the five repos at one tested release (method set by I2).
3. Phase 3, core + CPU readers: calls Conclave `scripts/setup_workbench.ps1`, then the Locutus / Obsidian / Sequoia / Atrium venvs.
4. Phase 4, optional parts as Settings switches.
5. Phase 5, shortcuts and `<install_root>\.adastra\install_inventory.json` (reserved in `NAMES.md`).
6. Phase 6, doctor: one `INSTALL: PASS` or the exact failing line.

## Never automated (the person's own steps)

Windows security boxes, sign-ins, signups and agreements (including any HIPAA agreement), API keys (Windows Credential Manager only), Windows Hello, the phone-tool passkey, and any Windows setting change. No patient data is shipped or tested.
