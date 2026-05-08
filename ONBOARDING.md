# Atrium Onboarding

**Status:** v0.1 — first issued
**Date:** 2026-05-08
**Audience:** A new Claude session OR a new human contributor coming to the Atrium project for the first time.
**Time investment:** ~30 minutes to read; ~2 hours to feel ready to contribute.

---

## Read these in this order

1. **`CONSTITUTION.md`** (~3000 words, ~10 min) — the binding governance. What the Atrium is, what it must always be, what it must never do. Do NOT skip this even if you're "just here to help with one thing."
2. **`CHARTER.md`** (~2000 words, ~7 min) — the operational elaboration. Why constellation-of-products vs. monolith. How products relate.
3. **This file** (`ONBOARDING.md`, ~2000 words, ~7 min) — orient yourself in the current state.
4. **`CONTRIBUTOR_PROTOCOL.md`** (~2500 words, ~10 min) — how to actually do work without breaking things.
5. **`GLOSSARY.md`** (~1500 words, ~5 min skim, lookup as needed) — terminology.

After these five: pick the product you're working on and read its `DESIGN.md` + `BUILD_TRACKER.md` last entries.

---

## Current state of the constellation (snapshot 2026-05-08)

### Curator
- **Version:** 0.41.0
- **Phase:** β at ~98% complete (gates 4 + 5 closed)
- **Tests:** 897 passing default + 9 opt-in
- **Recent shipped:** Lineage Graph view (v0.41), source `write` hook (v0.40)
- **Build location:** `C:\Users\jmlee\Desktop\AL\Curator\`
- **Active gaps:** bundle creation/editing UI, `curator gdrive auth` CLI helper (both Phase γ polish)
- **Documentation:** `Curator/DESIGN.md` (v1.0 spec), `Curator/DESIGN_PHASE_DELTA.md` (forward-looking), `Curator/ECOSYSTEM_DESIGN.md` (cross-product), `Curator/BUILD_TRACKER.md` (revision history), `Curator/CHANGELOG.md` (user-facing), `Curator/docs/` (technical deep-dives)

### Conclave (proposed, not built)
- **Status:** Proposal only — `Curator/docs/CONCLAVE_PROPOSAL.md` + `Curator/docs/CONCLAVE_LENSES_v2.md`
- **Estimated effort to v1.0:** ~120 hours, phased
- **Build location:** `C:\Users\jmlee\Desktop\AL\Conclave\` (planned; not yet created)
- **Open questions:** OQ-1 through OQ-8 in CONCLAVE_PROPOSAL.md §9

### Umbrella (proposed, not built)
- **Status:** Concept only — captured in `Curator/ECOSYSTEM_DESIGN.md` §4
- **Build location:** `C:\Users\jmlee\Desktop\AL\Umbrella\` (planned)

### Nestegg (proposed, not built)
- **Status:** Concept only
- **Build location:** `C:\Users\jmlee\Desktop\AL\Nestegg\` (planned)

### APEX (peer system, not Atrium member)
- **Constitution:** v0.5 BINDING (since 2026-04-28)
- **Build location:** `C:\Users\jmlee\Desktop\AL\Apex\APEX\`
- **Integration status:** First-class. Atrium honors APEX Constitutional rules. Atrium-side captured in `Curator/ECOSYSTEM_DESIGN.md` and `Atrium/CONSTITUTION.md` Article IV.
- **Key constraints flowing into Atrium:** MORTAL SIN rule, hash-verify-before-move, citation chain, self-sufficiency, no-new-memory-systems

### Open ecosystem decisions

The most important open decisions live in `Curator/ECOSYSTEM_DESIGN.md` §7 (decisions DE-1 through DE-13) and `Curator/docs/CONCLAVE_PROPOSAL.md` §9 (decisions OQ-1 through OQ-8). The biggest ones:

- **DE-1:** Synergy/Curator resolution (recommended: phased B → A; documented in `ECOSYSTEM_DESIGN.md` §1)
- **DE-9:** First-integration milestone (recommended: APEX safety plugin, ~3-4 hours)
- **OQ-1:** Conclave codename and ecosystem position (recommended: standalone constellation product named Conclave)
- **OQ-4:** Conclave Lens count for v1 (recommended: balanced preset of 5 Lenses for first ship, expanding to 12)

A new session should NOT re-litigate these — they're documented as recommendations awaiting Jake's affirmative. Either Jake has decided (check the Phased Delta doc + ECOSYSTEM_DESIGN.md for ratification markers) or these are still open.

---

## The operating rules in 60 seconds

(Full version in `CONTRIBUTOR_PROTOCOL.md` §1.)

1. **Numbered options menus** when proposing next steps. User picks by number.
2. **`c` = continue per default** (the first menu option unless explicitly otherwise).
3. **`Nm` = pitch on N** before committing.
4. **No corner-cutting** — every shipped feature has tests + docs + regression.
5. **Build location locked** — paths don't move once established.
6. **Folder numbers persist** — never reuse a number, even after retirement.
7. **`Filesystem:edit_file` is per-call atomic** — multi-edit batches all-succeed-or-all-rollback. Use `write_file` for big rewrites.
8. **End every Claude turn with a `▶ Continue` cue** + menu of next options.
9. **Wishlists always visible in chat** alongside the on-disk record.
10. **Reasoning lives in thinking blocks**, not in chat output.

---

## Common tasks

### "I want to ship a new feature in Curator"

1. Confirm the feature is in scope per `Curator/DESIGN.md` (v1.0 spec) or `Curator/DESIGN_PHASE_DELTA.md` (Phase Δ+).
2. Read the relevant section to see if there are existing decisions (D-N items in research notes).
3. Implement under `src/curator/`.
4. Write tests under `tests/`. Test count must increase, not decrease.
5. Run the full regression: `pytest tests/`. Confirm no failures.
6. Bump `pyproject.toml` and `src/curator/__init__.py` versions per [semver](https://semver.org/).
7. Add a CHANGELOG entry under that version.
8. Append a BUILD_TRACKER revision-log entry detailing what shipped, why, and what's deferred.
9. If GUI work: add a screenshot to `docs/`.
10. End with the standard `▶ Continue` menu.

### "I want to fix a bug"

1. Reproduce with a failing test FIRST (TDD).
2. Fix the bug.
3. Confirm the test now passes AND no other tests regress.
4. Bump patch version (0.X.Y → 0.X.Y+1).
5. Document in CHANGELOG + BUILD_TRACKER.

### "I want to update a design document"

1. If the doc is canonical (`DESIGN.md`, `CONSTITUTION.md`, `CHARTER.md`): consult the doc's amendment process. Most require Jake's explicit affirmation.
2. If the doc is exploratory (`DESIGN_PHASE_*.md`, `docs/*_PROPOSAL.md`): edit freely but mark the change with a date + rationale.
3. Never delete superseded design docs. Mark them `[SUPERSEDED by X]` at the top.

### "I want to add a Conclave Lens"

(Future-state; Conclave isn't built yet.) When it is:
1. Verify the new Lens has a *distinct failure mode* from existing Lenses (per `CONCLAVE_LENSES_v2.md`'s Lens-distinctness criterion).
2. Implement the `LensInterface` for the new Lens.
3. Add to the configurable subset presets if appropriate.
4. Run the ensemble validation suite against ground-truth assessments.
5. Bump Conclave's version.
6. Document in CONCLAVE_PROPOSAL.md §3 (Lens roster).

### "I want to add a new Atrium product"

This is rare. The path:
1. Articulate the domain the new product serves (per Charter §"How products are added").
2. Verify no existing product covers it adequately.
3. Draft a proposal at `Atrium/proposals/<NAME>_PROPOSAL.md` mirroring `CONCLAVE_PROPOSAL.md`'s structure.
4. Get Jake's affirmative.
5. Update Constitution Article III to add the new product.
6. Bump Constitution version.
7. Initialize the product's repository at `C:\Users\jmlee\Desktop\AL\<NAME>\`.
8. Initial commit follows `CONTRIBUTOR_PROTOCOL.md` §3 documentation discipline.

### "I'm a Claude session and I'm starting fresh"

Use the standard restart prompt from `CONTRIBUTOR_PROTOCOL.md` §6. After ingesting the governance docs, ask Jake what to tackle. Don't assume continuity from prior sessions you didn't participate in — check `BUILD_TRACKER.md` of the relevant product for the most recent state.

---

## Things to NEVER do (the short list)

- **Never violate a Non-Negotiable Principle** (Constitution Article II) without first declaring a Constitutional crisis.
- **Never delete files matching APEX's MORTAL SIN patterns.**
- **Never auto-init a git repo** without explicit user decision on `.gitignore`, squash, and remote.
- **Never assume a tool succeeded** without verifying state.
- **Never ship code without tests.**
- **Never edit BUILD_TRACKER retroactively.** Append-only.
- **Never silently degrade** when a partner product is unavailable. Surface the degradation.
- **Never claim atomicity** for an operation that isn't atomic.

---

## What to do when something goes wrong

### Test regression detected

1. Identify which tests broke and what change caused it.
2. Decide: fix forward (preserve the change, add corrective code) or revert (undo the change).
3. Run regression after fix to confirm green.
4. Document in BUILD_TRACKER what happened.

### A tool call fails or hangs

1. Don't retry immediately.
2. Check whether the tool's effect actually happened (file existence, process state, etc.).
3. If state is consistent with success, proceed.
4. If state is unclear, ask the user.
5. Document patterns of failure in `CONTRIBUTOR_PROTOCOL.md` §4 for future sessions.

### A Constitutional crisis is suspected

1. Pause all work that depends on the violated principle.
2. Document the suspected violation in detail.
3. Surface to Jake immediately.
4. Wait for Jake's direction before proceeding.
5. After resolution, file an entry in `Atrium/CRISIS_LOG.md` (create the file on first crisis).

### A merge conflict between two contributors' changes

(Future-state, when there are multiple contributors.) Standard git workflow applies. The Atrium does not currently have repo-level conventions for this.

---

## What success looks like

After 2 hours of onboarding:
- You can name all five Atrium charter members and what each does
- You know which product is built, which is proposed, which is integrated peer
- You understand why "constellation-of-products" was chosen over monolith
- You can state the MORTAL SIN rule and explain how it operationalizes
- You know the operating rules and the standard menu format
- You can find the right doc for any question (governance vs. product vs. ecosystem vs. terminology)
- You can navigate a `BUILD_TRACKER.md` and `CHANGELOG.md` to understand recent work

After 1 day:
- You've shipped a small contribution (a test, a docstring, a CHANGELOG fix)
- You've followed the full process: code → test → regression → CHANGELOG → BUILD_TRACKER → menu
- You've made at least one mistake and recovered using `CONTRIBUTOR_PROTOCOL.md` §4

If those criteria aren't met after a day, something is wrong with the documentation. Tell Jake.

---

*End of `ONBOARDING.md` v0.1. Update when patterns shift.*
