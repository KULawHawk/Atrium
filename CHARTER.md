# The Atrium Charter

**Status:** v0.2 (adds the APEX suite charter rules and the two data paths)
**Date:** 2026-05-08 (v0.1); 2026-11-03 (v0.2)
**Authority:** Subordinate to `CONSTITUTION.md`. This Charter elaborates Article III (the constellation roster) and Article IV (cross-product governance) into operational practice.

**What changed in v0.2.** Jake ruled on 2026-10-23 (decision A1, 12:21 PM CT, recorded in `full-audit-2026-10-23/STRATEGY.md` §3) that **APEX is the suite**, **Atrium is the integration layer** that lets APEX and future suites integrate with one another, and **Ad Astra is Jake's developer and portfolio name**, not the suite. v0.2 adds the rules every APEX tool keeps (the section "The APEX suite charter rules") and the two data paths (decision A3). The v0.1 text below is kept where it is still true; where the A1 ruling changes a statement, the section says so. Names are registered in `NAMES.md` v0.2.

---

## What the Atrium is

The Atrium is **a constellation of independent software products that share a common protocol layer**. The metaphor is architectural: a Roman atrium was the central hall connecting separate rooms in a house — open to the sky, the place where independent spaces met. Each Atrium product is a separate room. The protocol layer (SIP) is the atrium itself.

The constellation pattern says: rather than build one tool that does everything (and does most of it badly), build many tools that each do one thing well, then make them play together cleanly. The pattern works because:

1. **Specialization beats generalization.** A monolithic tool's design forces compromises in every domain. Specialized tools optimize for their domain.
2. **Failure isolates.** A bug in Conclave doesn't crash Curator. A regression in Umbrella doesn't break Nestegg. Each product can ship at its own velocity.
3. **Onboarding scales.** A contributor learns one product's codebase to be productive. Adding more contributors doesn't require everyone to know everything.
4. **Replacement is local.** If a product is replaced (Synergy → Curator over phases) or retired (NotebookLM bridge in APEX), the rest continues unaffected.
5. **Composition is opt-in.** Users install only what they need. Power users install everything and get the integrated benefits.

This pattern is the inverse of what's tempting in early development: just put everything in one repo, share data structures, get fast wins through tight coupling. That works for v0.1 but becomes the source of every painful refactor by v3.

**Atrium after A1.** The constellation pattern above still describes how Atrium works. A1 sharpens Atrium's role: it is the integration layer *above* the suites. It owns the contracts that cross tool boundaries (the ruling record, pattern pack, partition manifest, query request, forge request and the Obsidian contracts, listed in `CONTRACTS_REGISTRY.md`) and the charter rules below. It runs nothing. Its job is to let a future suite reuse Conclave, Locutus or Obsidian without rewiring them.

## Why standalone-first matters

Per Constitution Aim 7 (Self-sufficiency; numbered Aim 3 before the v0.3 reordering):

A user installing only Curator must get full Curator value. Not "Curator works but you really need Conclave for the indexer." Not "you can use Curator standalone but the GUI assumes APEX is installed." **Full value, standalone.**

This is enforced by the test suite in each product (the GUI tests pass without APEX installed; Curator's tests pass without networkx until you opt in to `[gui]` extras; etc.) and by the integration design pattern: when product A wants to use product B's data, it does so through a SIP-defined protocol that gracefully degrades when B is absent.

Concretely:
- Curator queries Conclave's KB output through file conventions (reads APEX-format manifests). If Conclave isn't installed, Curator still indexes the assessment PDFs as ordinary files.
- Conclave queries Curator for source files through MCP. If Curator's MCP server isn't running, Conclave falls back to its own minimal file walk.
- Umbrella monitors any SIP-compliant tool. If only Curator is installed, Umbrella monitors only Curator. If everything is installed, Umbrella monitors everything.
- Nestegg installs only what the user asks for. There's no "install Atrium and get all five" without the user explicitly choosing each.

## How products in the constellation are added

A new product joins the constellation when it satisfies all four membership criteria from Constitution Article III:

1. Fully functional standalone
2. Implements SIP-required protocols
3. Governed by the Atrium Constitution (membership = Constitutional acceptance)
4. Fills a domain not adequately covered by existing members

The first criterion is structural: the product can be installed and used by someone who has none of the other Atrium products.

The second is interface-driven: the product must implement health check, audit log format, SHA256 hash compatibility, configuration conventions, and any other SIP requirements that apply to its domain.

The third is Constitutional: by joining, the product accepts the Ten Aims (Six Aims before the v0.2 amendment) and Five Non-Negotiable Principles. Products that can't accept these (e.g., a tool that needs to ignore the MORTAL SIN rule for performance reasons) don't join the Atrium — they remain standalone tools that may interoperate at arm's length.

The fourth prevents internal competition: the Atrium is a constellation, not a marketplace. If two products would do substantially the same thing, one is chosen and the other is either retired (with a phase-out plan) or absorbed.

## How products are retired

Same Article III rules: another member fully covers the domain, no active users depend on the retiring member, Jake approves, the Constitution is updated.

The current case study is **Synergy** (an APEX subsystem, not an Atrium member, but the principle is the same). The phased retirement plan in `Curator/ECOSYSTEM_DESIGN.md` §1 is the canonical example: gradual scope narrowing as Curator absorbs Synergy's responsibilities, with retirement triggered event-by-event rather than calendar-by-calendar.

## How products respect each other's domains

Each product has authority within its domain. Within that domain:
- Its data model is the source of truth
- Its decisions are not overridden by other products
- Other products consume its outputs but do not edit them

Outside its domain:
- It does not encode opinions about other products' data
- It does not duplicate other products' functionality
- If it needs functionality another product provides, it integrates rather than reimplements

When a disagreement arises (e.g., Conclave thinks a section heading is "3.2 Scoring"; Curator's classification thinks the file is named differently — wait, those are different domains, they don't conflict), the resolution is: each product's view of its own domain prevails. Curator's file-name claim is authoritative for the file name; Conclave's section-heading claim is authoritative for the section heading; neither overrides the other.

Where genuine conflict exists (e.g., two products both need to be the canonical "list of all assessment files" authority), the Charter is updated to assign authority to one of them — the constellation does not have ambiguous authority.

## How conflicts surface

Cross-product conflicts surface through three mechanisms:

1. **Audit log divergence.** SIP-compliant audit logs from multiple products can be cross-referenced. When one says "deleted file X" and another says "file X was created by me yesterday," the divergence is detected.
2. **Health check failure modes.** Each product reports its `<tool> health` status. A health check that depends on another product's output (e.g., Conclave's "are my Lenses producing valid manifests?" check) fails loudly when the partner is misbehaving.
3. **User report.** When a user notices unexpected behavior, the audit log + health output of every involved product is captured and reviewed.

When a conflict requires Constitutional resolution (i.e., it can't be resolved by patching one product), it triggers a Constitutional crisis per Constitution Article V.

## How the Atrium relates to APEX

**Updated by A1 (2026-10-23 12:21 PM CT).** "APEX" now names the suite: Conclave, Sequoia, Verity, Affine, Locutus, Obsidian and the APEX hub sit under it, and Atrium is the integration layer it uses. The rest of this section was written when "APEX" meant only Jake's original psychological-assessment indexing platform. It still holds for that platform's own Constitution (v0.5) and its data directories, so it is kept as written below.

APEX is a peer system, not an Atrium member. The relationship is asymmetric and intentional:

- **APEX has its own Constitution** (v0.5 BINDING, separate from this Constitution). The Atrium honors APEX's Constitutional rules; APEX is not bound by Atrium rules.
- **Atrium products integrate with APEX** through SIP-compliant interfaces (when APEX adopts SIP) and through APEX's own published surfaces (CLIs, the Inkblot pywebview JS bridge, file conventions like `manifest.json`).
- **APEX-bound rules apply when interacting with APEX data.** The MORTAL SIN rule is the most concrete example: any Atrium product that touches APEX's `Output/`, `kb/`, `Scrolls/`, etc. inherits APEX's protection rules.
- **APEX may eventually adopt SIP** (or not — that's APEX's choice). If it does, the Atrium gains a sixth product-class peer with full SIP-driven integration. If it doesn't, the integration remains via APEX's published surfaces.

The reason for this asymmetry: APEX predates the Atrium. APEX has its own Constitution v0.5 BINDING since 2026-04-28; the Atrium Constitution v0.1 is from 2026-05-08. APEX's authority structure was established first. The Atrium is the newcomer. The Atrium adapts; APEX does not need to.

## How the constellation evolves

The constellation will gain and lose members over time. Some likely future trajectories:

- **Conclave** is likely to ship within 6-12 months of Constitutional ratification, becoming the second active member alongside Curator.
- **Umbrella** and **Nestegg** are slower-burning; they unlock real value once at least 3 Atrium products + APEX are deployed (4-5 things to monitor and install).
- **A 6th charter member** is plausible but unforeseen at v0.1. The Charter explicitly does not enumerate future members.
- **Synergy** is not an Atrium member but its phased retirement reshapes the Curator/APEX boundary in a Constitutionally significant way; the Charter is updated when Phase 3 lands.

## The APEX suite charter rules

These rules bind every APEX suite tool (Conclave, Sequoia, Verity, Affine, Locutus, Obsidian, the APEX hub) and any future tool or suite that integrates through Atrium. They come from Jake's rulings of 2026-10-23, recorded in the `full-audit-2026-10-23/` documents named in each rule. They add to the Constitution; they do not replace any Constitutional principle.

### Rule 1. Standalone first

Every tool runs on its own. The suite adds value without ever becoming a dependency a tool cannot run without. This restates Constitution Aim 7 (Self-sufficiency) for the suite (`APEX_SUITE_DESCRIPTION.md`, APEX entry). A concrete test: a Conclave or Sequoia run with an empty Locutus Pattern Pack still works (`LOCUTUS_DESIGN.md` §3).

### Rule 2. Replayable

Every tool is replayable byte for byte from its own audit trail. Anything loaded from another tool (for example a Locutus Pattern Pack) is loaded by hash, like a config file, and the hash is recorded in the audit trail, so the run replays without the other tool running (`APEX_SUITE_DESCRIPTION.md`; `LOCUTUS_DESIGN.md` §3).

### Rule 3. Every human input generalizes

Jake, 2026-10-23 1:23 PM CT (`STRATEGY.md` §2a; restated as an acceptance rule in `BLUEPRINT.md`, "Standing acceptance rule for every human-in-the-loop item"):

> "No part of Apex should ever simply take user feedback or input and just use it for that singular instance. All of that should be used to learn from grow in its ability to recognize & improve in reliability, verification, and accuracy without the need of human assistance."

**Applies to** every human-in-the-loop point in the suite: Conclave Review, the kickback band, Chaise K3 dual review, Sequoia corrections and attestation, Verity, Affine, and any future one.

**Every clarification or correction produces two records:**
1. The correct choice for this item.
2. A **pattern record**: a structural breakdown of the item (its structure, pattern, format and presentation), filed so that similar items are recognized and handled without asking next time.

In the suite these are carried by a `RulingRecord` (one per human decision, any tool), which Locutus turns into patterns shipped back as Pattern Packs (`LOCUTUS_DESIGN.md` §4).

**Acceptance check.** A design that stores a human answer only for the one instance fails review. The verify step for each human-in-the-loop item includes: "a second, structurally similar item is resolved without a human prompt, and the record shows the pattern it matched" (`BLUEPRINT.md`).

**Guardrails that still hold:**
- Learned or augmented data stays out of clearance sets, answer keys and held-out sets.
- An independence review is required before data is used for shared training. No engine is retrained on its own corrections while still being counted as independent.
- High-stakes changes still go through the verifier and Rule 4.

**Measured targets** (Jake, 2026-10-23 1:38 PM CT, `STRATEGY.md` §2b): about ten or fewer human flags per entire source at steady state, zero repeat flags on an issue type already ruled on, and every ruling ingested every day.

### Rule 4. High-stakes content is 100% correct or deferred

High-stakes content (cutoffs, norm tables, scoring rules, decision-tree branches, validity indicators, conversion algorithms) is 100% correct or deferred to a human. No tool, mode or learned pattern may lower that bar, mark high-stakes content resolved without a human, or make a research run look certifiable (`APEX_SUITE_DESCRIPTION.md`, APEX entry; `STRATEGY.md` §2). Chaise, the clinical mode, may only tighten this rule, never loosen it (`STRATEGY.md` §3a).

### Rule 5. The original copy is always kept (SEC-2)

Jake, 2026-10-23 2:18 and 2:19 PM CT, with the wording corrected at 2:20 PM CT (`DEIDENTIFY_MODULE_SPEC.md` §8 SEC-2; `STRATEGY.md` §3f and §3g): any file of any type, audio included, may be edited or de-identified in place as the working file. The one invariant is that a **password-protected original copy is always kept**, with its password held in the vault. This sits beside the Constitution's MORTAL SIN rule (Principle 1): editing the working file is allowed, losing the original is not.

### Rule 6. Patient data passes Obsidian first

Obsidian, the de-identification module, is a hard gate before any patient data enters the suite (`STRATEGY.md` §3g). Sharing identified documents is a routine action with safeguards, not a locked one; only automated paths (cloud lanes, language-model calls, CI) default to de-identified copies (SEC-8, Jake, 2026-10-23 2:40 and 2:41 PM CT, `DEIDENTIFY_MODULE_SPEC.md` §8).

## The two data paths (A3)

**RULED by Jake, 2026-10-23 12:24 PM CT: as recommended** (decision A3, `STRATEGY.md` §3).

| Path | From | To | Tools | Status |
|---|---|---|---|---|
| **Path 1** | A published assessment manual | A reviewed knowledge base, then Sequoia decision trees | Conclave, then human Review, then Sequoia | **Build first**, to working, before path 2. |
| **Path 2** | A completed protocol or session (case data) | Scored, cited findings | Affine and Verity, then Conclave, then Sequoia | New scope. Gated on decision D1 (which audio enters the suite) and behind Obsidian, because it carries patient data. |

Two related rulings shape the end of both paths:
- **D6** (Jake, 2026-10-23 12:35 PM CT, `STRATEGY.md` §3): the Atrium Forensic scoring-engine brief merges into Sequoia as its output and form-fill layer. There is one scorer per instrument.
- **D1** (Jake, 2026-10-23 12:31 PM CT, `STRATEGY.md` §3): path 2 audio covers verbal subtest responses first, then interviews, then full session recordings.

## What the Charter is NOT

- **It does not specify products.** That's per-product DESIGN docs.
- **It does not implement the SIP.** That's the SIP spec itself (currently in `Curator/ECOSYSTEM_DESIGN.md` §3).
- **It does not bind users.** Users adopt products under each product's own license.
- **It does not bind plugin authors** beyond what each product's plugin contract requires.

---

*End of `CHARTER.md` v0.2. Implements Constitution Articles III + IV; adds the APEX suite charter rules and the two data paths (Jake's rulings of 2026-10-23).*
