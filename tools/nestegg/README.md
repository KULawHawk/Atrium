# Nestegg: the APEX suite installer for other Windows PCs

Jake, 11/20/2026 9:20 PM CT: "an entire installation suite so this can be automatically installed on other computers", then "I mean everything. Everything."
Decision 273 = A (9:29 PM CT): a **script bundle with one double-click file**. It runs in phases, each phase prints PASS/FAIL, and there is a check-only dry run.
Coordinator defaults (under "assume approved when obvious", Jake told so he can object): I3 A (a "Check for updates" button in Settings), I4 A (core + CPU readers; the rest are OFF switches), I5 A (install to `C:\Users\<name>\AdAstra\`).
Plan: project share `installer/PLAN_installer_2026-11-20.md`.

## What is here now

| File | Phase | What it does |
|---|---|---|
| `Check AdAstra.cmd` / `Check-AdAstra.ps1` | 0, read-only | Checks Windows, disk, install folder, winget, Python 3.13 and 3.12, Git, Tesseract, Poppler, MuPDF mutool, VC++ runtime, GPU and TPM (report only), network, GitHub sign-in. Ends `NESTEGG-CHECK: PASS` or `GAPS n`. Installs nothing. |
| `Install-Prereqs.ps1` | 1, programs | See below. Ends `NESTEGG-PREREQS: PASS` or `FAIL n`. |
| `install_parts.py` + `parts.json` + `locks/` | 2, parts | Builds every one of the 38 parts in its own environment from exact versions with hashes, then proves it is complete. Ends `NESTEGG-PARTS: PASS`, `HOLD n` or `FAIL n`. |
| `htrlens_models.py` + `htrlens_models.json` | 2, HtrLens model files | Fetches the Kraken and TrOCR weights, checks every pinned sha256, loads them offline. Ends `NESTEGG-HTRLENS: PASS` or `FAIL n`. |

Still to come: release download of the five repos (I2 = C), core start-up, Settings switches, shortcuts and inventory, the doctor.

## Phase 2: parts (`install_parts.py`)

`python -I install_parts.py --src <folder with Conclave, locutus, sequoia, obsidian, atrium> --envs <folder> [--only A,B] [--dry-run]`

For each part in `parts.json`:

1. **Locked install.** The part's known-good list `locks/lists/<part>_py<ver>.txt` (measured by the package accounting thread; copied here byte for byte, `locks/SOURCE_SHA256.txt` records the source hashes, so there is one set of lists) is installed with `pip install --require-hashes --no-deps` against `locks/SHA256SUMS_*.txt`. Then the part's own source with `--no-deps`, then `pip check`. On Windows, Linux-only packages (`nvidia-*`, `triton`) are left out and `colorama` is added where click, tqdm or colorlog need it.
2. **Not locked = FAIL, never installed from the open index:** no known-good list yet; a package with no measured hash for this platform; a `parts.json` torch pin, added package or gate-3 constraint that the list disagrees with; CUDA torch on Windows (only the CPU build is measured); the Marker and MinerU engines and the Paddle side env (no known-good lists yet).
3. **Model files.** Pinned steps (HtrLens, the spaCy model, spoke scripts that pin revision and hash) must verify; unpinned ones (Docling, MinerU, VisionLocal's revision "main", and the `unpinned` entries) are FAIL "not pinned", even when the download worked.
4. **Probe.** Imports every module of the part plus every outside package its code names; each failure is a FAIL row by name. Programs the part needs (tesseract, pdftoppm, mutool) must be on PATH.
5. **Held** items (for example betacal, PA-3) print HOLD and never count as PASS.

Known open item: pip fetches the build backend for each part's own source (for example setuptools) at install time; it is not locked yet (printed as an INFO row on every part).

## Never automated (the person's own steps)

Windows security boxes, sign-ins, signups and agreements (including any HIPAA agreement), API keys (Windows Credential Manager only), Windows Hello, the phone-tool passkey, and any Windows setting change. No patient data is shipped or tested.

## Phase 1: prerequisites (`Install-Prereqs.ps1`)

Installs what is missing, leaves what is present alone: Python 3.13 and 3.12 (per user), Git,
GitHub CLI, Tesseract OCR, Poppler (per user), MuPDF mutool, VC++ runtime. Everything comes through
winget at one pinned version (`--version`), and winget checks each download against its signed
manifest's sha256. A program with no measured version yet (today: Tesseract) is FAIL "not locked"
if it would have to be installed, and is never installed unpinned. CI checks winget still offers
every pinned version. A program that is already present is left alone at whatever version it is (only fresh installs are pinned); phase 0 reports the version it finds. `-DryRun` only says what it would do.
Windows security boxes and winget's agreement question are the person's own answers; `-AssumeYes`
exists only for the clean-Windows test machine. Nothing is deleted and no Windows setting or
permanent PATH is changed by this script. Log: `<InstallRoot>\.adastra\install_log\`; found paths:
`<InstallRoot>\.adastra\prereqs.json`. Last line `NESTEGG-PREREQS: PASS` or `FAIL n`.
