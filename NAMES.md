# The Names Registry

**Status:** v0.1 — first issued
**Date:** 2026-05-08
**Authority:** Subordinate to `CONSTITUTION.md`. This document records names Jake has assigned to suite-level concepts, products, services, tools, and capabilities. The `GLOSSARY.md` defines *terms*; this document defines *names*.

---

## 1. Naming convention (binding)

When Jake assigns a name, the following defaults apply unless he explicitly says otherwise:

1. **A name is a brand for an existing component.** It re-labels something that already exists in the codebase. It does NOT imply a code reorganization, package rename, repo split, or directory move.
2. **No spinoff is implied.** The named thing stays exactly where it lives. Internal module names, CLI command names, package names, and file paths remain as they were unless Jake explicitly directs otherwise.
3. **User-facing strings update.** Documentation, CHANGELOG/BUILD_TRACKER entries, README sections, GUI labels, and any other surface a human reads SHOULD adopt the new brand within a reasonable window after naming.
4. **Code identifiers do NOT update reflexively.** Internal symbols (Python class names, module paths, CLI subcommand names) only change when Jake explicitly directs the rename. Stable identifiers across versions are valuable; cosmetic renames have a real refactoring cost.
5. **Claude does not raise spinoff questions unsolicited.** If there's a concrete technical reason a separate-package conversation is warranted (e.g., the named thing genuinely needs to ship without its parent), Claude flags it. Otherwise Claude treats the name as a label, updates user-facing docs, and moves on.

This convention is captured because the v1.1.0a1 session surfaced a Claude failure mode: when Jake named "Tracer," Claude offered three structural options including a spinoff variant. Jake's correction: don't do that. Just adopt the name. This document encodes that correction so future sessions don't repeat it.

---

## 2. Suite name: **Ad Astra**

**Decided:** 2026-05-08.

"Ad Astra" — Latin, "to the stars" — is the user-facing brand for the entire toolsuite. It supersedes any earlier informal references to "the Atrium" as a *suite* name (see open question below).

**The full canonical phrase, when one is needed:** "Ad Astra" alone is sufficient. "The Ad Astra suite" is acceptable in formal contexts. "AdAstra" (no space) is the canonical filesystem-safe spelling, used in `install_root` (`C:\Users\jmlee\AdAstra\`) and any path component or identifier that doesn't tolerate spaces.

### 2.1 OPEN QUESTION — relationship to "Atrium"

Prior to today's decision, `GLOSSARY.md` defined **Atrium** as "the constellation of products this Glossary belongs to" — i.e., Atrium WAS the working suite name. With "Ad Astra" now established as the suite name, Jake needs to choose how the two relate. Two clean framings:

- **Framing A — Ad Astra fully replaces Atrium as suite name.** The current `Atrium\` directory containing governance docs (Constitution, Charter, this file, etc.) gets re-purposed or eventually renamed (e.g., to `Governance\` under the new `AdAstra\` root). Every "Atrium" reference in existing docs becomes "Ad Astra" over time.
- **Framing B — Ad Astra is the user-facing suite brand; Atrium is the governance layer inside it.** Ad Astra is what the world sees (icon, launcher, marketing copy if there ever is any, casual reference). Atrium is the constitutional / governance / cross-product-policy layer — analogous to how a country has both a public name AND a constitutional convention inside it. Existing documents stay valid; "Atrium" continues to mean specifically the governance layer.

**Claude's recommendation: Framing B.** Reasons: (1) it doesn't invalidate `CONSTITUTION.md`, `CHARTER.md`, `GLOSSARY.md`, or `CONTRIBUTOR_PROTOCOL.md` references to "Atrium" — they remain accurate under the narrower definition; (2) it preserves the distinct connotations the two words carry (Ad Astra = aspirational / public-facing; Atrium = formal / constitutional / inward-facing); (3) it costs zero refactoring today and remains intelligible if Jake decides to converge later; (4) it mirrors a real-world pattern that humans intuit easily.

This open question is non-blocking. NAMES.md and `INSTALL_PATH_DESIGN.md` are written to be consistent with EITHER framing — they just refer to "the suite" or use "Ad Astra" where appropriate. When Jake chooses, this section closes and the chosen framing becomes binding.

---

## 3. Tools and services registry

| Component | Brand | Type | Status | Lives at | Notes |
|---|---|---|---|---|---|
| Curator | Curator | Product | Shipped (v1.1.0a1) | `<repo>\Curator\` | Content-aware artifact intelligence layer. Index + lineage + bundles + organize + cleanup + watch + GUI + CLI. |
| Curator's Migration capability | **Tracer** | Capability brand | Shipped Phase 1 (v1.1.0a1) | `<repo>\Curator\src\curator\services\migration.py` + `curator migrate` CLI | Same-source local-to-local migration with hash-verify-before-move discipline. Phase 2 (cross-source via gdrive write hook, resume tables, workers, GUI tab) outstanding. Code paths and CLI command name remain `migration` / `curator migrate`; "Tracer" is the user-facing name only. |
| Synergy | Synergy | Peer product | In progress | `<repo>\Synergy\` | File-inventory subsystem; canonical state-of-disk authority per APEX Master Scroll v0.4. Phase 1 unblocked by future Curator MCP server. |
| APEX | APEX | Peer product | Active | `C:\Users\jmlee\Desktop\AL\Apex\APEX\` | Predates Ad Astra; constitutional psychological assessment indexing platform. First-class integration peer; not strictly an Ad Astra member but governed by its own Constitution v0.5 BINDING. |
| Conclave | Conclave | Future product | Designed (proposal stage) | TBD | Multi-Lens ensemble indexer. 12 Lenses defined in `Curator\docs\CONCLAVE_LENSES_v2.md`. Phase 1 unblocked by future Curator MCP server. |
| Umbrella | Umbrella | Future product | Designed (spun out from Curator §A) | TBD | Asset monitor + auto-Claude troubleshoot. Standalone per `DESIGN_PHASE_DELTA.md` realignment notice. |
| Nestegg | Nestegg | Future product | Designed (spun out from Curator §I) | TBD | Standalone single-file installer. Will write `<install_root>\.adastra\install_inventory.json` on install per `INSTALL_PATH_DESIGN.md`. |

`<repo>\` in this table refers to the current location `C:\Users\jmlee\Desktop\AL\` and the future location `C:\Users\jmlee\AdAstra\` interchangeably; see `INSTALL_PATH_DESIGN.md` for the migration plan.

---

## 4. Naming new things — process

When Jake names something:

1. **Jake states the name and what it applies to.** Examples: "the Migration tool is Tracer," "let's call the new GUI tab Compass."
2. **Claude adds a row to §3 of this document** within the same session, recording component / brand / type / status / location / notes.
3. **Claude updates the most relevant user-facing surface** (CHANGELOG, BUILD_TRACKER, README section, etc.) within the same session — typically a one-line addition.
4. **Claude does NOT rename code identifiers** unless Jake explicitly requests it. The brand is a label; the code is the code.
5. **If there's any ambiguity** about scope (does this name apply to a class, a CLI subcommand, a whole product, a capability across products?), Claude asks one focused clarifying question and proceeds once answered.

---

## 5. Cross-references

- `CONSTITUTION.md` — supreme authority; this document is subordinate.
- `GLOSSARY.md` — defines *terms* (audit log, lineage, bundle, etc.); this document defines *names* (Curator, Tracer, Ad Astra, etc.). Some entities will appear in both (e.g., Curator).
- `INSTALL_PATH_DESIGN.md` — uses the names defined here for filesystem-layout purposes.
- Per-product `CHANGELOG.md` and `BUILD_TRACKER.md` — adopt brands defined here in user-facing entries.

---

## 6. Revision log

- **2026-05-08 v0.1** — first issued. Captures: (1) suite name "Ad Astra," (2) Tracer as Curator's Migration capability brand, (3) the binding naming convention (a name is a brand, not a refactor request), (4) the open Atrium-vs-Ad-Astra-relationship question with Framing B recommended.
