# Ad Astra lifecycle governance — design (UNIMPLEMENTED)

**Status:** Design captured 2026-05-09. **No code yet.**
This doc preserves Jake's intent + my recommendations from the install/MCP debug
session so the work can be planned and built deliberately when its turn comes.

## Context — why this exists

During the 2026-05-09 session Jake asked: "didn't we build auto-update with
burn-in and rollback?" Honest answer: no. The closest thing was the
`atrium-reversibility` package, which the constellation summary correctly
flagged as **deferred** — meaning planned but not implemented.

Jake's instinct that this *should* exist is correct. It's a sane pattern for
any tool that touches user data. The full design has three intertwined parts:

1. **Asset classification taxonomy** — every Ad Astra asset has a lifecycle
   status, so future cleanup and update operations know what's safe to touch.
2. **Update lifecycle with rollback** — when any Ad Astra tool gets a new
   version installed, it goes through staged → burn-in → finalized, with
   automatic rollback + version-blocking on health-check failure.
3. **Asset cleanup workflow** — Curator drives the actual file cleanup, but
   it can only safely act when classification metadata is in place.

These are listed in dependency order: classification first, then update
lifecycle (which uses classification), then cleanup (which uses both).

---

## Part 1: Asset classification taxonomy

### The three-level status model

Every file/dir/asset under Ad Astra (and ideally everything Curator tracks)
gets one of these statuses, stored as metadata:

| Status | Meaning | Cleanup behavior |
|---|---|---|
| **`vital`** | Never delete. Even if appears unused. (e.g., the Atrium constitution, license files, primary repo HEADs, original course materials.) | Cleanup operations skip these always. Trash command refuses without `--force-vital`. |
| **`active`** | Currently used. Default for everything not otherwise tagged. | Normal cleanup applies (duplicates dedup-able, junk files purgeable). |
| **`provisional`** | Replaced or superseded by something else, kept around for safety/burn-in. | Auto-deletable after a configured age IF the replacement is still working. |
| **`junk`** | Known disposable (`.tmp`, `.DS_Store`, `~$*`, build artifacts, log overflow). | Always safe to trash. |

### Where the metadata lives

Two-tier:

1. **Per-asset extended attributes** (when filesystem supports it, e.g. NTFS
   alternate data streams or xattrs) — fast, travels with the file.
2. **Curator's `flex_attrs` table** — authoritative; survives filesystem moves
   if Curator tracked the move. Schema:
   ```sql
   ALTER TABLE files ADD COLUMN status TEXT
     CHECK (status IN ('vital','active','provisional','junk'))
     DEFAULT 'active';
   ALTER TABLE files ADD COLUMN supersedes_id TEXT;  -- FK files.id
   ALTER TABLE files ADD COLUMN status_reason TEXT;
   ALTER TABLE files ADD COLUMN status_set_at TIMESTAMP;
   ALTER TABLE files ADD COLUMN status_expires_at TIMESTAMP;  -- for provisional
   ```

### CLI surface (proposed)

```
curator status set <path> --vital --reason "Atrium charter"
curator status set <path> --provisional --supersedes <other-id> --expires-in 30d
curator status set <path> --junk
curator status get <path>
curator status report  # all statuses, grouped by tag
```

### MCP surface (proposed)

```
get_status(file_id) -> {status, reason, expires_at, supersedes}
set_status(file_id, status, reason)
report_status_summary() -> aggregate counts per status
```

---

## Part 2: Update lifecycle with rollback (the universal pattern)

### Why "universal utility" not "per-tool"

Jake's directive: "ensure it is built out in full either as universal utility
or as part of each utility and tool."

**Recommendation: universal utility.** Specifically a new package
`atrium-reversibility` (the previously-deferred one). Reasons:

- DRY: same state machine + rollback logic in every tool = guaranteed drift
- Centralized blocked-version registry — future Ad Astra tools can refuse to
  reinstall a version they themselves marked broken
- Cross-tool burn-in: if Curator v1.7 is being burned-in and atrium-citation
  v0.3 also gets installed during that window, both should share the
  rollback decision

**Distribution model:** `atrium-reversibility` ships as a Python library
that any tool's installer (PowerShell or otherwise) imports. Curator's
`Install-Curator.ps1` becomes one client of it.

### State machine

```
       ┌────────────┐
       │  PROPOSED  │  pip install --pre / installer detects new version
       └─────┬──────┘
             │ user confirms or auto-policy
       ┌─────▼──────┐
       │  STAGED    │  new version installed; old version snapshot kept
       └─────┬──────┘  health checks scheduled at burn-in interval
             │ health checks pass for entire burn-in window
       ┌─────▼──────┐
       │ FINALIZED  │  old snapshot deleted; new version is canonical
       └────────────┘
             │ if any health check fails:
       ┌─────▼──────┐
       │ ROLLED_BACK │ snapshot restored; version added to blocked list
       └─────────────┘  blocked list checked on every future install
```

### Health-check protocol

For Curator the relevant check is the existing `Install-Curator.ps1` Step 9
MCP probe. For other tools (Scrapbook, APEX, FAP Engine, etc.), each ships a
`<tool>-healthcheck` entrypoint that returns 0 on success, non-zero on
failure with a structured error.

Burn-in default: **7 days**, with 1 health check on day 0 (right after
install) and one daily until finalization. Configurable per-tool.

### Snapshot mechanism

**Recommendation: filesystem-level snapshot via robocopy/rsync, NOT zip.**

- venv at `Curator\.venv` → snapshot to `~/.atrium/snapshots/curator/<sha>/.venv`
- canonical config at `Curator\.curator\curator.toml` → also snapshot
- claude_desktop_config.json snapshot (already done by current installer)

Rollback = atomic-rename old snapshot back over current. Cheap, fast, no
weird zip-restore failure modes.

### Blocked-version registry

```
~/.atrium/blocked_versions.json
{
  "curator": [
    {"version": "1.7.0", "blocked_at": "2026-05-15T09:21:00Z",
     "reason": "Step 9 MCP probe failed: tools/list returned 0 tools"}
  ],
  "curatorplug-atrium-citation": [],
  "curatorplug-atrium-safety": []
}
```

Every installer run consults this before attempting an install. A blocked
version requires `--force-install-blocked` to bypass.

### CLI surface (proposed)

```
atrium-update status                # show staged/finalized/blocked across all tools
atrium-update finalize curator      # manual finalize before burn-in expires
atrium-update rollback curator      # manual rollback
atrium-update unblock curator 1.7.0 # remove from blocked list
```

---

## Part 3: Asset cleanup workflow (Curator-driven)

### Today's reality (read this first)

Curator already has the **primitives**:

- `curator scan` — index files
- `curator group` — find duplicates
- `curator cleanup` — find empty dirs, broken symlinks, junk patterns
- `curator trash` / `curator restore` — soft-delete with recycle bin
- `curator organize` / `organize-revert` — reversible structural changes
- `curator audit` — full operation history

What Curator does NOT have yet:

- `curator status set` (Part 1 metadata above)
- Awareness of the `vital` flag in cleanup operations
- "Provisional → auto-deletable after age" automation

**Until Part 1 ships, the cautious workflow is:**

```
Phase 1 — read-only inventory:
  curator sources add local <path>
  curator scan local --root <path>
  curator group --json > duplicates.json
  curator cleanup --dry-run > junk.json

Phase 2 — manual review:
  Human reviews duplicates.json and junk.json. Tags vital files
  (currently impossible via Curator; for now, exclude them by path).

Phase 3 — apply with safety:
  curator group --apply --keep oldest --exclude-dirs <vital-dirs>
  curator cleanup --apply --exclude-dirs <vital-dirs>
  All actions go to Recycle Bin (NOT permanent delete).
  All actions audited.

Phase 4 — burn-in (manual today, automated post-Part-1):
  Files sit in Recycle Bin for N days.
  Restore any false-positives via curator restore <file-id>.
  Empty Recycle Bin only when confident.
```

### Integration with Part 1 + Part 2

Once Part 1 ships, Phase 2 manual review becomes automatic exclusion: cleanup
just refuses to touch `vital` and stages `provisional` separately. Once
Part 2 ships, the burn-in period for cleanup operations integrates with the
same atrium-reversibility infrastructure used for software updates.

---

## Implementation order (when this work happens)

1. **`atrium-reversibility` v0.1**: state machine + snapshot + blocked-list
   skeleton. No tool integration yet — just the library.
2. **Curator schema migration**: add `status`, `supersedes_id`, etc. fields
   to files table. Default everyone to `active`.
3. **`curator status` CLI subcommand** + matching MCP tool.
4. **`Install-Curator.ps1` consumes atrium-reversibility**: snapshots venv
   before install, registers staged update, health-check loop, finalize/
   rollback paths.
5. **Migrate other Ad Astra tools** (Scrapbook, APEX, UAP, FAP Engine, etc.)
   to consume atrium-reversibility — one at a time.
6. **Curator's `cleanup` and `group` commands honor `vital` status**.
7. **Auto-finalize / auto-purge daemon**: a small scheduled task that walks
   `provisional` and `staged` items, finalizes or rolls back per policy.

Roughly a 3–6 session block of work. None of it is urgent right now.

---

## Open design questions for next iteration

- Should `vital` be inheritable from a parent dir? (e.g., tag a folder vital
  and everything under it inherits) — probably yes, with explicit override.
- How does this interact with `bundles` (Curator's existing concept)?
- Cross-source: does `vital` on a local file persist when the file is
  migrated to Drive via Tracer?
- Granularity of blocked_versions: per-package, or per-package-+-Python-
  version, or per-package-+-OS?
- Do we want `atrium-reversibility` to also handle non-package assets
  (e.g., a backed-up curator.db pre-corruption)? Probably yes — same
  snapshot mechanism, different consumers.
