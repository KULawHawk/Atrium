# The Names Registry

**Status:** v0.2 (APEX suite names registered; the §2.1 framing question is closed)
**Date:** 2026-05-08 (v0.1); 2026-11-03 (v0.2)
**Authority:** Subordinate to `CONSTITUTION.md`. This document records names Jake has assigned to suite-level concepts, products, services, tools, and capabilities. The `GLOSSARY.md` defines *terms*; this document defines *names*.

**Sources for v0.2.** Every v0.2 ruling below cites Jake's ruling by date and time (US Central) and the document that records it. Those documents live in the 2026-10-23 full-audit folder (`full-audit-2026-10-23/`):
- `STRATEGY.md` §3 (decisions table A1, A2, A3, D6), §2 (Chaise and Obsidian names), §3a (Chaise), §3f (Locutus), §3g (Obsidian).
- `APEX_SUITE_DESCRIPTION.md` and its clean copy `APEX_SUITE_DESCRIPTION_CLEAN.md` (the written-up suite parts and the engine-count ruling).
- `LOCUTUS_DESIGN.md` and `DEIDENTIFY_MODULE_SPEC.md` (the Locutus and Obsidian designs and their decision tables).

---

## 1. Naming convention (binding)

When Jake assigns a name, the following defaults apply unless he explicitly says otherwise:

1. **A name is a brand for an existing component.** It re-labels something that already exists in the codebase. It does NOT imply a code reorganization, package rename, repo split, or directory move.
2. **No spinoff is implied.** The named thing stays exactly where it lives. Internal module names, CLI command names, package names, and file paths remain as they were unless Jake explicitly directs otherwise.
3. **User-facing strings update.** Documentation, CHANGELOG/BUILD_TRACKER entries, README sections, GUI labels, and any other surface a human reads SHOULD adopt the new brand within a reasonable window after naming.
4. **Code identifiers do NOT update reflexively.** Internal symbols (Python class names, module paths, CLI subcommand names) only change when Jake explicitly directs the rename. Stable identifiers across versions are valuable; cosmetic renames have a real refactoring cost.
5. **Claude does not raise spinoff questions unsolicited.** If there's a concrete technical reason a separate-package conversation is warranted (e.g., the named thing genuinely needs to ship without its parent), Claude flags it. Otherwise Claude treats the name as a label, updates user-facing docs, and moves on.

This convention is captured because the v1.1.0a1 session surfaced a Claude failure mode: when Jake named "Tracer," Claude offered three structural options including a spinoff variant. Jake's correction: don't do that. Just adopt the name. This document encodes that correction so future sessions don't repeat it.

**Explicit exception on record.** For **Chaise** and **Obsidian**, Jake directed that the new names be used in PR titles, code identifiers, config keys and docs (2026-10-23 3:32 and 3:35 PM CT, `STRATEGY.md` §2). For those two names, rule 4 is overridden by his direction. Older text that says "clinical mode" or "de-identification module" means the same thing.

---

## 2. The three top-level names: APEX, Atrium, Ad Astra

**RULED by Jake, 2026-10-23 12:21 PM CT (decision A1, `STRATEGY.md` §3).** The ruling replaces v0.1's "Suite name: Ad Astra" section.

| Name | What it names | Use it for |
|---|---|---|
| **APEX** | **The suite.** Conclave, Sequoia, Verity, Affine, Locutus, Obsidian and the APEX hub all sit under it. | "The APEX suite", "an APEX member", "APEX-compatible". |
| **Atrium** | **The integration layer** that lets APEX, and any future suite, integrate with one another. Atrium owns the contracts that cross tool boundaries and the charter rules every tool keeps. It runs nothing. | Governance docs, the Charter, the contracts registry, cross-suite contracts. |
| **Ad Astra** | **Jake's developer and portfolio name** for all of his projects, including ones unrelated to APEX (for example a traffic app). It is **not** the suite name. | Author or portfolio credit ("an Ad Astra project"). |

**Slogan.** The APEX suite's slogan is **over.built** (Jake's text of 2026-10-23 3:27 PM CT, recorded in `APEX_SUITE_DESCRIPTION.md`). Write it in lower case with the period.

### 2.1 The Atrium-vs-Ad-Astra question (CLOSED by A1)

v0.1 left open how "Atrium" and "Ad Astra" relate, and offered two framings: (A) Ad Astra replaces Atrium as the suite name, or (B) Ad Astra is the user-facing suite brand and Atrium is the governance layer inside it. Claude recommended B.

Jake's A1 ruling settles the question differently from both framings. It keeps the useful half of B (Atrium is a distinct layer, so existing Atrium documents stay valid) but changes two things:
- **The suite is APEX, not Ad Astra.** Ad Astra (formerly the suite name in v0.1 of this file) is now the portfolio name above all of Jake's projects.
- **Atrium is an integration layer, not only a governance layer.** It sits above the suites rather than inside one, and it owns the cross-tool contracts as well as the governance rules.

This section is closed. The ruling is binding.

### 2.2 The `AdAstra` filesystem spelling

v0.1 set "AdAstra" (no space) as the filesystem-safe spelling, used in `install_root` (`C:\Users\jmlee\AdAstra\`). That spelling still stands. Because Ad Astra is the portfolio name over all projects, a portfolio-level install root is consistent with A1. `INSTALL_PATH_DESIGN.md` still calls that root "the Ad Astra suite"; that wording is stale under A1 and is left for that document's own revision (it is deferred to end-of-build).

### 2.3 How the old APEX relates to the new one

Before A1, "APEX" in these documents meant Jake's Constitution-governed psychological-assessment indexing platform (APEX Constitution v0.5 BINDING since 2026-04-28, with subsystems such as Inkblot, Synergy and Vampire). Under A1, "APEX" names the whole suite that grew out of that work. Where an older document says "APEX" and means the original platform, its rules (the MORTAL SIN rule, the citation chain, Compounding Learning) still apply and are carried into the suite rules in `CHARTER.md`.

---

## 3. Tools and services registry

### 3.1 APEX suite members

Engine count: **19.** Conclave has **18 built Lenses**, plus **LENS-19 ABBYY FineReader**, designed and not yet built. Public text says 19 (Jake, 2026-10-23 4:17 PM CT, `APEX_SUITE_DESCRIPTION.md` closing note). Internal build documents may say "18 until LENS-19".

| Component | Brand | Type | Status | Lives at | Ruling and source | Notes |
|---|---|---|---|---|---|---|
| The suite | **APEX** | Suite | Active | Members' own repos | A1, 2026-10-23 12:21 PM CT, `STRATEGY.md` §3 | Data-integrity and fidelity suite whose tools work alone and also check one another. Formerly the name of the assessment-indexing platform only (see §2.3). |
| Integration layer | **Atrium** | Integration layer | Active (documents only) | `KULawHawk/atrium` | A1, 2026-10-23 12:21 PM CT, `STRATEGY.md` §3 | Owns cross-tool contracts (see `CONTRACTS_REGISTRY.md`) and the charter rules. Not an APEX member; it sits above the suites. |
| Multi-Lens indexer | **Conclave** | Suite member | Built (18 Lenses); LENS-19 designed | `KULawHawk/Conclave` | Name predates A1; engine count ruled 2026-10-23 4:17 PM CT, `APEX_SUITE_DESCRIPTION.md` | Converts assessment manuals into reviewed knowledge bases. 19 engines in public text. Path 1 starts here. |
| Decision-tree scoring | **Sequoia** | Suite member | In build | `KULawHawk/sequoia` | Registered per A2 follow-up, 2026-10-23 12:23 PM CT, `STRATEGY.md` §3; D6 merge 12:35 PM CT | Compiles a verified knowledge base into decision forests. The Atrium Forensic scoring-engine brief merged into Sequoia as its output and form-fill layer (D6); one scorer per instrument. |
| Audio verification | **Verity** | Suite member | Designed | TBD | Registered per A2 follow-up, 2026-10-23 12:23 PM CT, `STRATEGY.md` §3; scope per D1, 12:31 PM CT | Verifies transcripts against audio. Staging: verbal subtest responses, then interviews, then full sessions. |
| Skew and warp rescue | **Affine** | Suite member | Designed (Wave 6 item C3) | TBD (one CLI and repo planned) | A2, 2026-10-23 12:23 PM CT, `STRATEGY.md` §3 | **Formerly Deskew and MissSkew**, now one tool. MissSkew's deep-learning dewarp becomes an optional GPU-gated stage. |
| Shared learning component | **Locutus** | Suite member | P0 built (contracts and firewall) | `KULawHawk/locutus` | J1, 2026-10-23 1:44 PM CT; J2/J8, `LOCUTUS_DESIGN.md` §12, `STRATEGY.md` §3f | Turns every human ruling from every tool into reusable patterns, shipped back as signed, hash-pinned Pattern Packs. Never in a run's decision path at run time. Its contracts are owned by Atrium. |
| De-identification module | **Obsidian** | Suite member (shared module) | Contracts in build (Wave 6 items 6.19 to 6.26) | `KULawHawk/obsidian`; engine and UI as a shared package used by the APEX hub | Name: 2026-10-23 3:32 PM CT, `STRATEGY.md` §2; placement: SEC-0, 2:15 PM CT, `DEIDENTIFY_MODULE_SPEC.md` §8 | Removes identifiers from any file before it leaves the PC or enters a shared store. Hard gate before any patient data enters the suite. Locutus tool enum value is `obsidian`. Contract owned by Atrium. |
| Clinical mode | **Chaise** | Strictness profile (capability brand) | Adopted; build order K3, K1, K2 (blueprint 6.8) | Conclave configuration | Name: 2026-10-23 3:35 PM CT, `STRATEGY.md` §2; adopted 1:09 PM CT, `STRATEGY.md` §3a | Named profile that only tightens defaults. Knobs: K1 auto-accept bar, K2 human kickback band, K3 dual independent review. Required for any clinically certifiable knowledge base. |
| Suite front door | **APEX hub** | Suite member (display) | Planned (Wave 6) | TBD | Named in A1 follow-up ("Wave 6 hub work uses APEX suite"), `STRATEGY.md` §3; description `APEX_SUITE_DESCRIPTION.md` §3 | Shows each tool's outputs, the suite's numbers, the Obsidian checklist and share screen, and the Chaise status of every knowledge base. Hosts no computation and holds no authority. |

### 3.2 Other registered products and capabilities (suite placement not yet ruled)

These rows are carried over from v0.1. A1 does not say whether Curator, Umbrella and Nestegg sit under APEX, under another suite, or stand alone under Ad Astra. Until Jake rules, read them as Ad Astra projects that integrate through Atrium.

| Component | Brand | Type | Status | Lives at | Notes |
|---|---|---|---|---|---|
| Curator | Curator | Product | Shipped (v1.1.0a1) | `<repo>\Curator\` | Content-aware artifact intelligence layer. Index + lineage + bundles + organize + cleanup + watch + GUI + CLI. |
| Curator's Migration capability | **Tracer** | Capability brand | Shipped Phase 1 (v1.1.0a1) | `<repo>\Curator\src\curator\services\migration.py` + `curator migrate` CLI | Same-source local-to-local migration with hash-verify-before-move discipline. Phase 2 (cross-source via gdrive write hook, resume tables, workers, GUI tab) outstanding. Code paths and CLI command name remain `migration` / `curator migrate`; "Tracer" is the user-facing name only. |
| Synergy | Synergy | Original-APEX subsystem | In progress | `<repo>\Synergy\` | File-inventory subsystem; canonical state-of-disk authority per APEX Master Scroll v0.4. Phase 1 unblocked by future Curator MCP server. |
| Umbrella | Umbrella | Future product | Designed (spun out from Curator §A) | TBD | Asset monitor + auto-Claude troubleshoot. Standalone per `DESIGN_PHASE_DELTA.md` realignment notice. |
| Nestegg | Nestegg | Future product | Designed (spun out from Curator §I) | TBD | Standalone single-file installer. Will write `<install_root>\.adastra\install_inventory.json` on install per `INSTALL_PATH_DESIGN.md`. |

`<repo>\` in this table refers to the current location `C:\Users\jmlee\Desktop\AL\` and the future location `C:\Users\jmlee\AdAstra\` interchangeably; see `INSTALL_PATH_DESIGN.md` for the migration plan.

### 3.3 Retired names (bridges)

Each retired name keeps one bridge so readers who know the old name can find the new one.

| Old name | Now | Ruling |
|---|---|---|
| Deskew, MissSkew | **Affine** (one tool) | A2, 2026-10-23 12:23 PM CT |
| "Ad Astra" as the suite name | **APEX** is the suite; Ad Astra is the portfolio name | A1, 2026-10-23 12:21 PM CT |
| "clinical mode" | **Chaise** | 2026-10-23 3:35 PM CT |
| "de-identification module" | **Obsidian** | 2026-10-23 3:32 PM CT |
| "Atrium Forensic scoring-engine brief" | Sequoia's output and form-fill layer | D6, 2026-10-23 12:35 PM CT |

---

## 4. Naming new things — process

When Jake names something:

1. **Jake states the name and what it applies to.** Examples: "the Migration tool is Tracer," "let's call the new GUI tab Compass."
2. **Claude adds a row to §3 of this document** within the same session, recording component / brand / type / status / location / notes, plus the ruling's date, time and source.
3. **Claude updates the most relevant user-facing surface** (CHANGELOG, BUILD_TRACKER, README section, etc.) within the same session — typically a one-line addition.
4. **Claude does NOT rename code identifiers** unless Jake explicitly requests it. The brand is a label; the code is the code.
5. **If there's any ambiguity** about scope (does this name apply to a class, a CLI subcommand, a whole product, a capability across products?), Claude asks one focused clarifying question and proceeds once answered.

---

## 5. Cross-references

- `CONSTITUTION.md` — supreme authority; this document is subordinate. The Constitution (RATIFIED v0.3) still uses the pre-A1 names; aligning it needs an Article V amendment.
- `CHARTER.md` — the suite charter rules that apply to every APEX member, and the two data paths (A3).
- `GLOSSARY.md` — defines *terms* (audit log, lineage, bundle, RulingRecord, etc.); this document defines *names* (APEX, Atrium, Ad Astra, Curator, Tracer, etc.). Some entities appear in both.
- `CONTRACTS_REGISTRY.md` — the cross-tool contracts Atrium owns, one line per module.
- `INSTALL_PATH_DESIGN.md` — uses the names defined here for filesystem-layout purposes.
- Per-product `CHANGELOG.md` and `BUILD_TRACKER.md` — adopt brands defined here in user-facing entries.

---

## 6. Revision log

- **2026-05-08 v0.1** — first issued. Captures: (1) suite name "Ad Astra," (2) Tracer as Curator's Migration capability brand, (3) the binding naming convention (a name is a brand, not a refactor request), (4) the open Atrium-vs-Ad-Astra-relationship question with Framing B recommended.
- **2026-11-03 v0.2** — brings the registry in line with Jake's rulings of 2026-10-23. (1) §2 rewritten: APEX is the suite, Atrium is the integration layer, Ad Astra is the portfolio name (A1); slogan "over.built" recorded. (2) §2.1 closed. (3) §3 split into APEX suite members (APEX, Atrium, Conclave, Sequoia, Verity, Affine, Locutus, Obsidian, Chaise, APEX hub) and carried-over rows, with each ruling's date, time and source. (4) Engine count recorded as 19. (5) Retired-name bridges added (§3.3). (6) The Chaise and Obsidian code-identifier exception to rule 1.4 recorded.
