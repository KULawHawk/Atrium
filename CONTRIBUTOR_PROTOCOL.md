# The Atrium Contributor Protocol

**Status:** v0.1 — first issued
**Date:** 2026-05-08
**Authority:** Subordinate to `CONSTITUTION.md`. This document specifies how anyone (human or Claude session) works on Atrium products.

---

## Who this is for

Anyone modifying code, design docs, or governance documents in any Atrium product. The protocol applies whether the contributor is:

- Jake working solo
- A Claude session driving the work
- A future human collaborator
- A future Claude session resuming work after a break

The protocol exists because Jake's projects are large enough that individual sessions can't hold full context. Without protocol, every session re-derives the same patterns and re-makes the same mistakes. With protocol, sessions inherit institutional knowledge.

---

## Section 1: Operating rules in effect

These are the operating rules established in the Curator project conversation and adopted across the Atrium. Anyone working on any Atrium product follows them.

### Rule 1.1: Numbered options menus

When proposing next steps, present them as a numbered list (1, 2, 3, ...). The user replies with the number(s) they want. This is faster than free-form back-and-forth and avoids the "did you mean A or B?" disambiguation cycle.

When the user types just `c` (or `cont`), this means "proceed with the default option" — typically the first option, unless the menu explicitly identifies a different default.

When the user types `Nm` (where N is an option number and `m` follows), this means "give me a 30-second pitch on option N" before committing.

### Rule 1.2: Tier integration first-class

When designing or implementing, integration tiers are first-class concerns, not afterthoughts. Specifically:

- Cross-product integration (SIP) is designed in, not retrofitted
- Plugin extensibility is built into the architecture, not bolted on
- Cross-platform compatibility (Windows / macOS / Linux) is tested, not assumed
- Cross-version compatibility is declared explicitly via `compatibility.toml`

### Rule 1.3: No corner-cutting

Don't ship a feature without:
- Tests covering the happy path AND the error paths
- Documentation in CHANGELOG.md AND BUILD_TRACKER.md
- A regression run confirming no test count loss
- Honest assessment of what was deferred vs. what was completed

Speed matters. Quality matters more. The accumulated value of well-built features compounds; the accumulated cost of half-built features compounds even faster.

### Rule 1.4: Reasoning lives in thinking blocks

When a Claude session is reasoning through a design or implementation choice, that reasoning belongs in extended-thinking blocks, not in chat output. Chat output is for the user-facing summary, the deliverable, and the actionable menu.

### Rule 1.5: Wishlists always visible in chat

Operating rules, deferred items, open decisions — these are kept visible in chat alongside their persisted on-disk locations. The chat history is not authoritative; the on-disk records are. But the chat visibility prevents the user from having to look up their own preferences.

### Rule 1.6: Build location locked

Once a product's build location is established (e.g., `C:\Users\jmlee\Desktop\AL\Curator\`), it does not move. Path changes break too many things: documentation references, MCP server configurations, cached test fixtures, CI scripts, etc.

The Atrium products live under `C:\Users\jmlee\Desktop\AL\`:
- `C:\Users\jmlee\Desktop\AL\Curator\` (existing)
- `C:\Users\jmlee\Desktop\AL\Apex\APEX\` (existing; not Atrium, but coexists)
- `C:\Users\jmlee\Desktop\AL\Conclave\` (planned)
- `C:\Users\jmlee\Desktop\AL\Umbrella\` (planned)
- `C:\Users\jmlee\Desktop\AL\Nestegg\` (planned)
- `C:\Users\jmlee\Desktop\AL\Atrium\` (created 2026-05-08; this directory)

### Rule 1.7: Folder numbers persist forever

If a numbering scheme is established (subAPEX-N in APEX; phase numbers in Curator's roadmap; DE-N decisions in ECOSYSTEM_DESIGN.md), numbers are not reused. A retired item leaves its number in place; a new item gets the next available number.

This rule prevents off-by-one confusion when historical references resurface ("DM-3 was decided last March" — DM-3 should still be DM-3 today).

### Rule 1.8: "Round N ready" = consume signal

When the user signals readiness for the next round of work (typically by typing `c`), Claude proceeds with the default action without re-confirming. The user's signal is the consume; re-asking wastes the round.

### Rule 1.9: Use `Filesystem:write_file` for big edits; `edit_file` for small ASCII edits

The `Filesystem:edit_file` tool is **per-call atomic** — when ANY edit in a multi-edit batch fails, ALL edits in that batch roll back. This is a feature, not a bug, but it means:

- Multi-edit batches are higher-risk than single-edit operations
- An anchor mismatch in edit #3 of a batch undoes successful edits #1 and #2
- Smart anchors are short, surely-unique, ASCII-only when possible

Specific failure modes documented in this conversation:
- **Em-dash mismatch** (— vs -- vs ---): the file may use one variant; the edit may use another
- **Casing mismatch** ("Implements" vs "implements"): case-sensitive
- **Phantom-anchor** (specifying an old text that doesn't exist): always fails the whole batch
- **Whitespace mismatch**: trailing spaces, tabs vs spaces, newline conventions

For multi-edit batches: do a quick `read_file` of the target region BEFORE batching to verify anchors. For long content (>30 lines): use `Filesystem:write_file` to overwrite, not `edit_file` to patch.

### Rule 1.10: End every turn with visible Continue cue

Every Claude session response ends with a `▶ Continue` cue plus the menu of next options. This serves two purposes:
1. It tells the user the session is awaiting input (vs. still working)
2. It establishes the menu of valid responses (numbered options + `c` for default + `Nm` for pitches)

### Rule 1.11: `c` = `cont` (default item)

The single character `c` always means "execute the default option from the most recent menu." If the menu doesn't identify a default explicitly, it's the first item. Accept `cont` as a synonym.

---

## Section 2: Per-product conventions

### File operations

- Always use absolute paths. Relative paths break across CWD changes.
- Verify file existence before assuming you can edit.
- After ANY successful `str_replace` or `edit_file`, re-`view` before further edits to the same file (the prior view output is stale).
- Use `Filesystem:write_file` for files >100 lines or where the content is mostly new.

### Test discipline

- After every code change, run the affected test subset (~5-10 second target)
- Before committing any milestone, run the full regression (`pytest tests/`)
- Test count must not decrease without explicit deletion + reason in CHANGELOG
- Skipped tests must have a documented reason
- Performance tests live in `tests/perf/` and are opt-in via `pytest -m slow`

### Version bumping

Semantic versioning per product:
- **Patch** (0.X.Y → 0.X.Y+1): bugfix, no API change
- **Minor** (0.X.Y → 0.X+1.0): new feature, backward compatible
- **Major** (0.X.Y → 1.0.0+): breaking change

Constellation-level decisions don't trigger product version bumps. Each product versions its own work.

When bumping a version:
1. Update `pyproject.toml` (or equivalent)
2. Update `src/<product>/__init__.py` `__version__`
3. Add CHANGELOG entry under that version heading
4. Append BUILD_TRACKER revision-log entry
5. Run regression to confirm clean state at the new version

### Naming

Per Constitution-aligned conventions:
- **Codenames are primary identifiers.** Use `Curator` not `the file knowledge graph tool`. Use `Conclave` not `the multi-Lens indexer`.
- **Dotted notation for subcomponents:** `Curator.gui.lineage_view`, `Conclave.lenses.PdfText`.
- **Plugin packages:** `<product>plug-<vendor>-<purpose>`. Example: `curatorplug-atrium-safety`.
- **Tool scripts:** `<Codename>_<Verb>.py` for CLI utilities (matches APEX's `APEX_<Verb>.py` pattern).

---

## Section 3: Documentation discipline

### Where things go

- **`<product>/DESIGN.md`** — the v1.0 product spec. Stable; rarely edited after initial write.
- **`<product>/DESIGN_PHASE_<N>.md`** — phase-specific roadmap. Created when a phase is planned; archived (not deleted) when the phase ships.
- **`<product>/BUILD_TRACKER.md`** — append-only revision log. Every milestone entry is appended; nothing is edited in place.
- **`<product>/CHANGELOG.md`** — user-facing changelog per [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.
- **`<product>/docs/`** — deeper technical docs (research notes, integration designs, screenshots).
- **`Atrium/`** — constellation-level governance (this Constitution, this Protocol, the Charter, etc.).

### What goes in BUILD_TRACKER vs CHANGELOG

- **BUILD_TRACKER:** every meaningful work session, even if no version was bumped. Detailed, internal-facing, includes the why and how.
- **CHANGELOG:** every released version, plus `[Unreleased]` for in-flight work that meaningfully affects users. User-facing, terse.

The BUILD_TRACKER tells the implementer what changed and why; the CHANGELOG tells the user what changed and what to expect.

### How design docs evolve

- A new design idea starts as a section in the relevant `DESIGN_PHASE_<N>.md` (if it's phase-specific) or `<product>/docs/<topic>_PROPOSAL.md` (if it's standalone).
- When the design is ratified (Jake approves), it migrates into the appropriate primary doc (`DESIGN.md` for v1.0 features, ECOSYSTEM_DESIGN.md for cross-product, etc.).
- The original proposal stays in `docs/` as historical record. Don't delete superseded design docs; mark them with a `[SUPERSEDED by X]` banner at the top.

---

## Section 4: Mid-session repair patterns

These are failure modes encountered in the Curator project conversation, with the fixes that worked. New contributors save time by knowing them in advance.

### Pattern: edit_file batch atomicity rollback

**Symptom:** A multi-edit batch fails on edit #N, and ALL prior successful edits roll back.

**Fix:**
1. Identify which edit failed (the error message points to the bad anchor)
2. Re-do edit #1 through #(N-1) as separate single-edit calls
3. Fix edit #N's anchor and apply
4. For very large edit batches: prefer `Filesystem:write_file` overwrite

### Pattern: Phantom-anchor failure

**Symptom:** Edit fails with "could not find exact match" but the user is sure the text exists.

**Fix:**
1. `read_file` the region around where the text should be
2. Compare byte-for-byte to your `oldText`
3. Common culprits: em-dash variants (—/--/—), casing, trailing whitespace, line endings (CRLF vs LF)
4. Use a shorter, simpler ASCII-only anchor

### Pattern: Tool unresponsive

**Symptom:** A PowerShell or other tool call returns no result after a long timeout.

**Fix:**
1. Don't retry immediately
2. Verify the underlying state through alternative means (file existence check, etc.)
3. If state is consistent with success, proceed
4. If state is unclear, ask the user before retrying

### Pattern: Test wiring requires update after structural change

**Symptom:** A new GUI tab is added; existing tab-position tests fail with off-by-one.

**Fix:**
1. Search test files for the changed structural assumption
2. Update each affected assertion
3. Re-run the affected test subset to confirm
4. Document in BUILD_TRACKER that test wiring was updated

### Pattern: Helper script not persisted

**Symptom:** A Python helper script written via `Filesystem:write_file` doesn't exist when called.

**Fix:**
1. Don't rely on prior tool result confirmation; verify file presence
2. For one-off helpers, inline via PowerShell here-strings instead of writing a script
3. For reusable helpers, write to a known location and verify before invoking

---

## Section 5: Things to NEVER do

- **Never violate a Non-Negotiable Principle** (Constitution Article II) without first declaring a Constitutional crisis.
- **Never delete files matching APEX's MORTAL SIN patterns** (`Output/`, `kb/`, `Scrolls/`, `manifest.json`, `profile.json`, `verification_report*`, `*_extractions.jsonl`).
- **Never auto-init a git repo** without explicit user decision on `.gitignore`, squash strategy, and remote.
- **Never assume a tool succeeded** without verifying the resulting state.
- **Never ship code without tests.**
- **Never edit `BUILD_TRACKER.md` retroactively.** Append-only.
- **Never reuse a folder number** (per Rule 1.7).
- **Never silently fall back to a degraded mode** (per Constitution Principle 4).
- **Never claim atomicity for an operation that isn't atomic** (per Constitution Principle 5).

---

## Section 6: Standard restart prompt for new sessions

When a Claude session ends and a new one begins on the same project, the user pastes this prompt to bring the new session up to speed:

> Resuming work on the Atrium constellation (`C:\Users\jmlee\Desktop\AL\`).
>
> **Governance:** `Atrium/CONSTITUTION.md` (binding), `Atrium/CHARTER.md`, `Atrium/CONTRIBUTOR_PROTOCOL.md`, `Atrium/GLOSSARY.md`, `Atrium/ONBOARDING.md`. Read these first.
>
> **Active products:** Curator (v0.41.0, Phase β at ~98%), APEX peer system (Constitution-governed). Planned: Conclave (proposal at `Curator/docs/CONCLAVE_PROPOSAL.md`), Umbrella, Nestegg.
>
> **Current state:** [user fills in: which product, which phase, which feature]
>
> **Operating rules:** numbered options menu, `c` = continue per default, no corner-cutting, end every turn with `▶ Continue` cue. Per-product BUILD_TRACKER files capture the build history.
>
> **Today's task:** [user fills in]

The prompt is intentionally short — the new session should ingest the governance docs first to gain real context, not consume a 3000-word prompt before it can do anything.

---

## Section 7: When this protocol is updated

This Protocol is a living document. Patterns identified in real work get added. Patterns that turn out not to matter get removed.

Updates require:
- A clear reason (what failure or friction motivated it)
- Jake's explicit approval (in chat or in a commit)
- Version bump on this Protocol

Major changes to the operating rules (e.g., changing the meaning of `c`) require Constitution-level deliberation since they affect every session's expectations.

---

*End of `CONTRIBUTOR_PROTOCOL.md` v0.1. Implements Constitution Article VI's "what this Constitution is NOT" by being the contributor-facing how-to.*
