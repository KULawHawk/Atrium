# Ad Astra Install Path Design

**Status:** v0.1 — first issued
**Date:** 2026-05-08
**Authority:** Subordinate to `CONSTITUTION.md`. Coordinated with `NAMES.md`. Will inform the eventual `Nestegg` installer implementation.

---

## 1. Decision

**The Ad Astra suite installs and lives at:**

```
C:\Users\jmlee\AdAstra\
```

**Current development location:** `C:\Users\jmlee\Desktop\AL\` (will migrate when the build matures).
**Migration timing:** end-of-build, NOT now. See §6.

This decision is binding for design purposes — every future doc, code path that references `install_root`, and Nestegg's installer logic should treat `C:\Users\jmlee\AdAstra\` as the canonical target. Nothing on disk moves until the migration day.

---

## 2. Why this path

### 2.1 The selected path

`C:\Users\jmlee\AdAstra\` was chosen because:

- **No admin / UAC required.** User-owned subtree. `git`, `pytest`, venv creation, file moves — none triggers an elevation prompt.
- **Conventional Windows location.** Per-user installations under the user profile root are standard Windows practice and survive Windows updates / re-imaging better than ad-hoc locations.
- **Not under `%LOCALAPPDATA%`.** Critical: Curator's own `SafetyService` correctly flags everything under `%LOCALAPPDATA%\Temp\` as CAUTION (app-data verdict). We hit this exact issue during v1.1.0a1 migration testing — pytest's `tmp_path` lives there, and the safety service correctly refused to migrate files. Putting `install_root` under the home root rather than AppData avoids a class of false-CAUTION verdicts that would otherwise need defensive code to handle.
- **Not under `%PROGRAMFILES%`.** No admin requirement; no fights with Windows file virtualization or UAC.
- **Self-documenting.** "AdAstra" in the path tells anyone browsing what's there.

### 2.2 Alternatives considered and rejected

- **`C:\AdAstra\`** — drive root. Cleanest path strings. Slight unconventionality (most users don't have folders at drive root). Acceptable but not optimal.
- **`C:\Tools\AdAstra\`** — middle ground. Adds an extra path component for no real benefit when the suite is the only thing in `Tools\`.
- **`%LOCALAPPDATA%\AdAstra\`** — Windows convention but hidden by default and triggers the SafetyService CAUTION-on-app-data verdict. Rejected.
- **`%PROGRAMFILES%\AdAstra\`** — admin required, fights development workflows, no payoff. Rejected.
- **`%USERPROFILE%\Desktop\AdAstra\`** — current working location pattern. Desktop should hold active items / shortcuts, not permanent installs. Acceptable for development; rejected as long-term home.

---

## 3. Recommended layout

```
C:\Users\jmlee\AdAstra\
├─ Curator\                         <- moved from <Desktop>\AL\Curator\
│  ├─ src\curator\                  source tree (unchanged)
│  ├─ tests\                        test tree (unchanged)
│  ├─ docs\                         per-product docs
│  ├─ .venv\                        virtual env (recreated post-migration)
│  ├─ runtime\                      ALL Curator-generated runtime data; see §4.1
│  │  ├─ curator.db                 SQLite index (was %APPDATA%\Curator\)
│  │  ├─ logs\                      Loguru file sink (was %APPDATA%\Curator\)
│  │  ├─ audit\                     SHA256-chained JSONL audit log
│  │  ├─ gdrive\<alias>\            credentials.json + token.pickle per alias
│  │  └─ hash_cache\                xxhash3_128 / md5 / fuzzy_hash cache
│  ├─ pyproject.toml
│  ├─ README.md
│  ├─ CHANGELOG.md
│  ├─ BUILD_TRACKER.md
│  ├─ DESIGN.md
│  ├─ DESIGN_PHASE_DELTA.md
│  └─ ...
├─ APEX\                            <- moved from <Desktop>\AL\Apex\APEX\
├─ Synergy\                         <- moved from <Desktop>\AL\Synergy\
├─ Atrium\                          <- moved from <Desktop>\AL\Atrium\
│  ├─ CONSTITUTION.md
│  ├─ CHARTER.md
│  ├─ GLOSSARY.md
│  ├─ NAMES.md
│  ├─ INSTALL_PATH_DESIGN.md         (this file)
│  ├─ ONBOARDING.md
│  ├─ CONTRIBUTOR_PROTOCOL.md
│  └─ META\
├─ Conclave\                        FUTURE
├─ Umbrella\                        FUTURE
├─ Nestegg\                         FUTURE — produces Ad Astra installer
├─ branding\                        suite-shared visual identity
│  ├─ icons\                        .ico (multi-res), .png (high-res sources)
│  │  ├─ adastra.ico                suite icon
│  │  ├─ curator.ico
│  │  ├─ tracer.ico                 (Tracer is a Curator capability; its own icon if desired for launchers)
│  │  └─ ...
│  ├─ wordmarks\                    SVG wordmarks
│  ├─ palette.md                    color tokens
│  └─ typography.md                 font choices (if any)
├─ bin\                             launcher shims
│  ├─ curator.cmd                   wraps <root>\Curator\.venv\Scripts\curator.exe
│  ├─ curator.ps1                   PowerShell variant
│  └─ ...                           one shim per top-level CLI
├─ .adastra\                        suite-internal metadata (see §5)
│  └─ install_inventory.json        canonical record of every external touchpoint
├─ README.md                        suite-level overview
└─ .gitignore                       suite-level (or each product has its own)
```

The leading `<root>\` notation in subsequent sections refers to `C:\Users\jmlee\AdAstra\` after migration.

---

## 4. File taxonomy: what's inside `install_root` vs. what's outside

### 4.1 Inside (the win — almost everything)

The vast majority of every product's footprint is captured by `install_root`:

- **Source code** — every product's `src\`, `tests\`, `docs\`.
- **Virtual environments** — each product's `.venv\`. Recreated when the install moves; absolute paths in `pyvenv.cfg` make venvs non-portable.
- **Runtime data** — Curator currently writes to `%APPDATA%\Curator\` by default. The `Config` object already supports overriding `db_path` and `log_path`. **A one-time default change** points runtime data at `<root>\Curator\runtime\` instead. ~10 LOC change in `src/curator/config.py`. Other products inherit the same convention. Critical consequence: a backup of `<root>\` captures literally everything, with no scattered AppData paths to chase.
- **Credentials** — `gdrive\<alias>\credentials.json + token.pickle` belong under `<root>\Curator\runtime\gdrive\` not `%APPDATA%`. Same reasoning.
- **Audit logs** — by Constitution requirement, every product writes an audit log; all live under `<root>\<Product>\runtime\audit\`.
- **Caches** — hash caches, embedding caches, MusicBrainz response caches, Lens caches (Conclave) — all under `<root>\<Product>\runtime\`.
- **Branding assets** — `<root>\branding\`. Single source of truth shared by all products.
- **Launcher shims** — `<root>\bin\`. Thin `.cmd` / `.ps1` wrappers around per-product venv entrypoints.

### 4.2 Outside (the unavoidable externals — short list)

Five categories, four of which are pure opt-in:

1. **Python interpreter** at `C:\Program Files\Python313\` (or wherever Python lives).
   - Not "ours" — shared system resource.
   - Each `.venv\` references it but doesn't duplicate it.
   - Nestegg's installer should record the interpreter path + version in the install inventory and verify on every run that it's still present.

2. **Start Menu / Desktop shortcuts**.
   - Locations: `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Ad Astra\` and `%USERPROFILE%\Desktop\`.
   - Optional. User chooses at install time.
   - Recorded in install inventory. Removed on uninstall.

3. **PATH environment variable update** in registry (`HKCU\Environment\PATH`).
   - Optional. Adds `<root>\bin\` to the user PATH so `curator`, `tracer`, etc. work from any terminal.
   - Alternative if user opts out: invoke through `<root>\bin\curator.cmd` directly.
   - Recorded in install inventory. The exact prepended/appended segment is logged so uninstall can remove only what was added.

4. **Add/Remove Programs entry** at `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\AdAstra\`.
   - Purely cosmetic / Windows citizenship. Lets the suite show in Settings → Apps & Features.
   - Optional. Recommended if the suite ever gets shared with other users.
   - Recorded in install inventory.

5. **OS Recycle Bin** when Curator/Tracer trash files.
   - Not really our file — user data passing through Windows mechanism.
   - Out of scope for "install footprint."

That is the complete external surface. Five categories, four opt-in.

---

## 5. The install inventory pattern

`<root>\.adastra\install_inventory.json` is a JSON file written by Nestegg (or by hand during the development-era migration) recording every external touchpoint. It is the **only authoritative record** of what's outside `install_root`.

### 5.1 Schema sketch

```json
{
  "schema_version": 1,
  "installed_at": "2026-05-08T14:32:00Z",
  "ad_astra_version": "0.1",
  "install_root": "C:\\Users\\jmlee\\AdAstra",
  "external_touchpoints": [
    {
      "kind": "python_interpreter",
      "path": "C:\\Program Files\\Python313\\python.exe",
      "version": "3.13.1",
      "managed": false
    },
    {
      "kind": "start_menu_shortcut",
      "path": "C:\\Users\\jmlee\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Ad Astra\\Curator.lnk",
      "target": "C:\\Users\\jmlee\\AdAstra\\bin\\curator.cmd",
      "icon": "C:\\Users\\jmlee\\AdAstra\\branding\\icons\\curator.ico",
      "created_by": "nestegg",
      "managed": true
    },
    {
      "kind": "desktop_shortcut",
      "path": "C:\\Users\\jmlee\\Desktop\\Curator.lnk",
      "target": "C:\\Users\\jmlee\\AdAstra\\bin\\curator.cmd",
      "icon": "C:\\Users\\jmlee\\AdAstra\\branding\\icons\\curator.ico",
      "managed": true
    },
    {
      "kind": "registry_path_entry",
      "registry_path": "HKCU\\Environment",
      "value_name": "Path",
      "appended_segment": "C:\\Users\\jmlee\\AdAstra\\bin",
      "managed": true
    },
    {
      "kind": "registry_uninstall_entry",
      "registry_path": "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\AdAstra",
      "managed": true
    }
  ]
}
```

The exact schema will be ratified when Nestegg is built. This is illustrative.

### 5.2 What it enables

This single inventory file gives Nestegg (and any human auditor) the full external picture:

- **Uninstall** — read inventory, remove every `managed: true` touchpoint, then `Remove-Item -Recurse <root>\`. Symmetric with install. Zero orphans by construction.
- **Verify** — re-read inventory, check each entry still exists / matches expected state. Useful for self-diagnostics ("`adastra doctor`").
- **Repair** — for any inventory entry that's been clobbered, re-create it from the inventory. (E.g., user deleted a shortcut by hand → repair restores it.)
- **Move** — if `install_root` ever migrates (say `C:\` to `D:\`), Nestegg reads the inventory, rewrites every path-containing touchpoint to the new location, updates the inventory in place. Zero manual cleanup.

### 5.3 Relationship to Atrium Constitution

This pattern is the Constitution's discipline (audit log, hash-verify, no-silent-failures, atomic operations) applied to the installer domain. Same shape, different surface. The inventory IS an audit log of installer actions; uninstall is the symmetric inverse; verify is the integrity check; the format is JSON-text so it's human-readable like every other Atrium-governed audit trail. Nestegg's eventual Constitution adherence statement will reference this section.

---

## 6. Migration plan: `Desktop\AL\` -> `AdAstra\`

This is end-of-build work. It is documented now so future-Jake and future-Claude know exactly what to do when the time comes; it is NOT to be executed today, this week, or this month. Trigger condition: the build is mature enough that one can reasonably claim "the suite is ready to live in its permanent home" — likely concurrent with Nestegg's first working installer build or just after Tracer Phase 2 ships.

### 6.1 Prerequisites

- Working tree clean for every product (`git status` reports nothing pending).
- Latest version pushed to GitHub remote (NOT optional — see §6.4).
- All test suites passing on every product.
- No Curator/Tracer/Synergy services running (no `curator watch`, no GUI, no daemon).
- A current backup outside the user's machine (cloud / external drive). Belt and suspenders.

### 6.2 Steps (target ~30 minutes)

1. **Verify clean state.** `cd C:\Users\jmlee\Desktop\AL\Curator; git status` — clean. Repeat per product.
2. **Push to GitHub.** Closes single-disk SPOF (Atrium GATE-PM-013). No work loss possible if the move corrupts something.
3. **Create the target.** `New-Item -ItemType Directory C:\Users\jmlee\AdAstra`.
4. **Move each product tree.** Per product:
   ```powershell
   Move-Item C:\Users\jmlee\Desktop\AL\Curator C:\Users\jmlee\AdAstra\Curator
   ```
   `Move-Item` on the same volume preserves git metadata, file timestamps, and ACLs. Cross-volume would copy + delete, which is slower but still correct.
5. **Verify git survived per product.** `cd C:\Users\jmlee\AdAstra\Curator; git status` — should be clean. `git log --oneline -3` — should show recent commits including v1.0.0rc1 tag and v1.1.0a1 commit. `git describe` — should still report `v1.0.0rc1-N-g<hash>`.
6. **Recreate venvs per product.** `pyvenv.cfg` contains absolute paths that are now stale.
   ```powershell
   cd C:\Users\jmlee\AdAstra\Curator
   Remove-Item -Recurse .venv
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -e ".[dev]"
   ```
7. **Run regression per product.** `pytest -q`. Curator should report 1002+ passing. Other products their own counts.
8. **Update Curator runtime defaults.** Edit `src\curator\config.py` so `db_path` defaults to `<root>\Curator\runtime\curator.db` instead of `%APPDATA%\Curator\curator.db`. Migrate the existing DB file from `%APPDATA%\Curator\` to the new location (or leave the old in place until the user re-scans). Same for `log_path`.
9. **Recreate any Desktop shortcuts** to point at new launcher targets.
10. **Update PATH** if `<root>\bin\` was previously on PATH from `Desktop\AL\bin\`.
11. **Remove the old tree.** `Remove-Item -Recurse C:\Users\jmlee\Desktop\AL` ONLY after all of the above are verified.

### 6.3 Document updates required

After migration, the following one-line edits are required:

- `Atrium\GLOSSARY.md` — definitions referencing `C:\Users\jmlee\Desktop\AL\` paths update to `C:\Users\jmlee\AdAstra\`.
- `Atrium\NAMES.md` §3 — table column "Lives at" updates.
- Each product's `README.md` and `BUILD_TRACKER.md` — any path references update.
- Each product's `CHANGELOG.md` — a single entry recording the migration, no version bump (cosmetic).

These are search-and-replace operations against well-known strings. Should take 5-10 minutes total.

### 6.4 Risk register

- **Single-disk SPOF.** The move is `Move-Item` on the same volume. Atomic at the directory level on NTFS, but if power fails mid-move, recovery requires the GitHub push that step 6.1 mandates. No remote = no migration.
- **Stale absolute paths.** Venvs, `.idea\` IDE configs, `.vscode\settings.json`, any cached `pyc` files. Recreating venvs and clearing caches handles all known cases. Anything missed surfaces as an `ImportError` on first test run, which is loud and recoverable.
- **Curator running.** If a `curator watch` process is running during the move, file handles will likely block the move on Windows. Step 6.1 prerequisite "no services running" prevents this.
- **DB-on-the-moving-disk problem.** If `curator.db` is open by any process during the move it will fail to move. Same mitigation as above.

### 6.5 Rollback

If anything goes wrong before step 11, simply move the tree back: `Move-Item C:\Users\jmlee\AdAstra\Curator C:\Users\jmlee\Desktop\AL\Curator`. Git history is intact. Recreate venvs in old location. Total recovery time: ~5 minutes.

After step 11 (old tree removed), rollback requires `git clone` from the GitHub remote into the old location. This is why §6.1 mandates the push.

---

## 7. Open questions

- **Atrium-vs-Ad-Astra suite-name relationship.** See `NAMES.md` §2.1. Non-blocking; Framing B (Atrium = governance layer inside Ad Astra) is the recommendation pending Jake's decision. This document is consistent with either framing.
- **Nestegg's installer scope.** Whether Nestegg treats the suite as a single installable unit OR as a meta-installer that orchestrates per-product installs. Either is consistent with the inventory pattern. Defer until Nestegg actually starts.
- **Per-product `runtime\` vs. shared `<root>\runtime\`.** Current recommendation: per-product, because each product's runtime data has different schema/lifecycle/audit requirements. Revisit when a second product (Synergy?) actually starts writing runtime data.

---

## 8. Cross-references

- `CONSTITUTION.md` — supreme authority.
- `NAMES.md` — defines the names this document references (Ad Astra, Curator, Tracer, Nestegg, etc.).
- `Curator\DESIGN.md` — Curator's spec, including current `Config` semantics that this document proposes to extend.
- `Curator\DESIGN_PHASE_DELTA.md` §I — Nestegg's spec, which this document feeds into via §5.
- `Curator\BUILD_TRACKER.md` — records the eventual migration when it happens.

---

## 9. Revision log

- **2026-05-08 v0.1** — first issued. Captures: (1) install root decision (`C:\Users\jmlee\AdAstra\`), (2) full file taxonomy with explicit external-touchpoint enumeration, (3) install inventory pattern (`.adastra\install_inventory.json`), (4) explicit migration steps with prerequisites and rollback, (5) three open questions for later resolution.
