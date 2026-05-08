# The Atrium Charter

**Status:** v0.1 — first issued
**Date:** 2026-05-08
**Authority:** Subordinate to `CONSTITUTION.md`. This Charter elaborates Article III (the constellation roster) and Article IV (cross-product governance) into operational practice.

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

## Why standalone-first matters

Per Constitution Aim 3 (Self-sufficiency):

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

The third is Constitutional: by joining, the product accepts the Six Aims and Five Non-Negotiable Principles. Products that can't accept these (e.g., a tool that needs to ignore the MORTAL SIN rule for performance reasons) don't join the Atrium — they remain standalone tools that may interoperate at arm's length.

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

## What the Charter is NOT

- **It does not specify products.** That's per-product DESIGN docs.
- **It does not implement the SIP.** That's the SIP spec itself (currently in `Curator/ECOSYSTEM_DESIGN.md` §3).
- **It does not bind users.** Users adopt products under each product's own license.
- **It does not bind plugin authors** beyond what each product's plugin contract requires.

---

*End of `CHARTER.md` v0.1. Implements Constitution Articles III + IV.*
