# Nestegg: the APEX suite installer for other Windows PCs

Jake, 11/20/2026 9:20 PM CT: "an entire installation suite so this can be automatically installed on other computers", then "I mean everything. Everything."
Decision 273 = A (9:29 PM CT): a **script bundle with one double-click file**. It runs in phases, each phase prints PASS/FAIL, and there is a check-only dry run.
Coordinator defaults (under "assume approved when obvious", Jake told so he can object): I3 A (a "Check for updates" button in Settings), I4 A (core + CPU readers; the rest are OFF switches), I5 A (install to `C:\Users\<name>\AdAstra\`).
Plan: project share `installer/PLAN_installer_2026-11-20.md`.

## What is here now

| File | Phase | What it does |
|---|---|---|
| **`Install AdAstra.cmd` / `Install-AdAstra.ps1`** | **1 + 2, the one command** | Jake 11/22: "Anytime you can run one command that will take care of all the parts at once, that's the way it should be done." Runs phase 1, then phase 2 only if phase 1 ends `PASS`. Sources from `<InstallRoot>\src` (all five repos, or FAIL before anything installs). Creates the per-aim learning folders under `<InstallRoot>\learning` (create-only, never touches existing contents). `-DryRun` installs nothing. Ends `NESTEGG-INSTALL: PASS`, `HOLD` or `FAIL`. |
| `Check AdAstra.cmd` / `Check-AdAstra.ps1` | 0, read-only | Checks Windows, disk, install folder, winget, Python 3.13 and 3.12, Git, Tesseract, Poppler, MuPDF mutool, VC++ runtime, GPU and TPM (report only), network, GitHub sign-in. Ends `NESTEGG-CHECK: PASS` or `GAPS n`. Installs nothing. |
| `Install-Prereqs.ps1` | 1, programs | See below. Ends `NESTEGG-PREREQS: PASS` or `FAIL n`. |
| `install_parts.py` + `parts.json` + `locks/` | 2, parts | Builds every one of the 38 parts in its own environment from exact versions with hashes, then proves it is complete. Ends `NESTEGG-PARTS: PASS`, `HOLD n` or `FAIL n`. |
| `htrlens_models.py` + `htrlens_models.json` | 2, HtrLens model files | Fetches the Kraken and TrOCR weights, checks every pinned sha256, loads them offline. Ends `NESTEGG-HTRLENS: PASS` or `FAIL n`. |
| `saved_copies.py` + `saved_copies.json` | 2, saved copies | Decision 30 A (Jake 11/23). Every package and model file is looked for in this order: the home copy `<InstallRoot>\saved`, then the private saved-copy release, then the original site. Each file is hash-checked whichever copy it came from. Files are stored under their sha256, in parts under 2 GiB. A home-network disk can be added as one more folder entry. `check <folder>` re-hashes a copy. |
| `Pull Saved Copies.cmd` | home copy | Double-click: fills `%USERPROFILE%\AdAstra\saved` from the private release, checking free disk first and hash-checking every piece. Uses your own `gh` sign-in. Ends `SAVED-COPIES: PASS` or `FAIL n`. |
| `build_saved_release.py` + `release/build-saved-copy.yml` | release build | Runs only in the private saved-copies repository (Atrium is public). It downloads each pinned file, refuses a wrong hash, uploads it in parts, and keeps only one file on disk at a time. It can resume after a stop. |
| `release/source_pin.py` | release build | Pins the saved-copies repository's tools to one Atrium commit on main. `make` writes SOURCE.txt (the commit plus a sha256 for every tool file at that commit). The build job runs `verify` (fetched from that commit) and stops before uploading anything if a file differs or an unpinned file is present. |

Still to come: release download of the five repos (I2 = C), core start-up, Settings switches, shortcuts and inventory, the doctor.

## Phase 2: parts (`install_parts.py`)

`python -I install_parts.py --src <folder with Conclave, locutus, sequoia, obsidian, atrium> --envs <folder> [--only A,B] [--dry-run]`

For each part in `parts.json`:

1. **Locked install.** The part's known-good list `locks/lists/<part>_py<ver>.txt` (measured by the package accounting thread; copied here byte for byte, `locks/SOURCE_SHA256.txt` records the source hashes, so there is one set of lists) is installed with `pip install --require-hashes --no-deps` against `locks/SHA256SUMS_*.txt`. Then the part's own source with `--no-deps`, then `pip check`. On Windows, Linux-only packages (`nvidia-*`, `triton`) are left out and `colorama` is added where click, tqdm or colorlog need it.
2. **Not locked = FAIL, never installed from the open index:** no known-good list yet; a package with no measured hash for this platform; a `parts.json` torch pin, added package or gate-3 constraint that the list disagrees with; CUDA torch on Windows (only the CPU build is measured); the Marker and MinerU engines (no known-good lists yet); the Paddle side env until its spoke declares a hash-locked `[side_env]` list (Conclave #2941), which the installer then builds at the spoke's own folder.
3. **Model files.** Pinned steps (HtrLens, the spaCy model, spoke scripts that pin revision and hash) must verify; unpinned ones (Docling, MinerU, VisionLocal's revision "main", and the `unpinned` entries) are FAIL "not pinned", even when the download worked.
4. **Probe.** Imports every module of the part plus every outside package its code names; each failure is a FAIL row by name. Programs the part needs (tesseract, pdftoppm, mutool) must be on PATH.
5. **Measured or not.** A reader (`conclave_lens_*`, and the Marker/MinerU engines) PASSes only when its list is MATCHED to a measured pod run; on a list resolved today it installs exactly and shows HOLD "locked, not measured". A part that is not a reader PASSes on a list resolved today only when its own tests pass under that exact set (test tools from `locks/lists/_test_tools_py<ver>.txt`, hash-checked); until that list exists it is HOLD. The status of each list is in `locks/LIST_STATUS.txt`.
6. **Re-runs keep the last working copy (SET-11).** An existing environment `<envs>\<Part>` is renamed `<Part>.kept-<time>`, and the new one is built at the real path. It stays only if its own verdict and import probe have no FAIL row. Only then is `adastra_verified.json` written into it. An existing environment without that file is set aside as `<Part>.unfinished-<time>` and is never called the working copy. That covers a build a crash interrupted, or one made before this check existed. If the new build fails, the newest verified `.kept-` copy is put back. If there is none, the run says plainly that the part is not installed. The failed build is kept as `<Part>.failed-<time>`. The Paddle side env is built beside as `<folder>.new-<time>` and switched in after its warmup. Nothing is deleted: **each passing re-run of a part adds one kept copy** beside it (about the size of that environment, often 1 to 5 GB). Every run lists all `.kept-`, `.unfinished-`, `.new-` and `.failed-` folders as INFO rows. Removing them is your call; nothing removes them automatically. A folder held open by a running program is a FAIL row ("close any program using it"), and nothing changes.
7. **Held** items (for example betacal, PA-3) print HOLD and never count as PASS. The last line counts FAIL, HOLD and PASS separately (`NESTEGG-PARTS: FAIL n, HOLD n, PASS n`), so a HOLD never reads as a clean install.

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
