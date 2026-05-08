# The Atrium Glossary

**Status:** v0.1 — first issued
**Date:** 2026-05-08
**Authority:** Subordinate to `CONSTITUTION.md`. This document defines the terminology used across Atrium documents.

Terms are listed alphabetically. Cross-references are linked. APEX-borrowed terms are marked with [APEX] for attribution.

---

## A

**APEX** — Jake's Constitution-governed psychological assessment indexing platform. Predates the Atrium; not an Atrium member but a peer system with first-class integration. Lives at `C:\Users\jmlee\Desktop\AL\Apex\APEX\`. Has its own [Constitution](#constitution-apex) v0.5 BINDING since 2026-04-28.

**Atrium** — the constellation of products this Glossary belongs to. Working name; alternatives offered in `CHARTER.md`. Five charter members planned: [Curator](#curator), [Conclave](#conclave), [Umbrella](#umbrella), [Nestegg](#nestegg) — and integration with [APEX](#apex) as a peer. Lives at `C:\Users\jmlee\Desktop\AL\Atrium\` for governance docs; products live at `C:\Users\jmlee\Desktop\AL\<Product>\`.

**Audit log** — append-only JSONL log of every change to user data. Per [SIP](#sip) §3.2 it has required fields: `timestamp`, `tool`, `version`, `actor`, `action`, `entity_type`, `entity_id`, `details`. Optional fields include `previous_hash` (chain links per Inkblot's `audit_trail.py` pattern) and `learning_trace` (per [Compounding Learning](#compounding-learning)).

**Augur** [APEX] — APEX's inductive cognitive entity (vs. [Scribe](#scribe)). Currently internal-only; clinical output reserved for future Lorax-confirmed amendment. Atrium-derived inferences map to Augur territory and inherit the same restriction.

## B

**Band-Aid** [APEX] — APEX's first platform-component codename (`apex_patch/`). The other five platform-component codenames (apex_control, drive_sync, self_repair, apex_v2, rule_engine) are pending Jake's naming pass.

**Beacon** — proposed alternative codename for the Atrium constellation, emphasizing the lighthouse / health-and-status motif. Not selected; [Atrium](#atrium) currently used.

**BUILD_TRACKER.md** — per-product append-only revision log. Every meaningful work session gets an entry, even if no version was bumped. Detailed, internal-facing. Counterpart to user-facing [CHANGELOG.md](#changelog).

**Bundle** — a Curator concept: a curated collection of files that share a logical relationship (e.g., "all files for assessment X"). Distinct from [Lineage](#lineage) edges (pairwise relationships).

## C

**`c` (the command)** — single-character user input meaning "continue per default." Always the first option in the most recent menu unless explicitly identified otherwise. See [`CONTRIBUTOR_PROTOCOL.md`](CONTRIBUTOR_PROTOCOL.md) §1.11. Synonym: `cont`.

**CHANGELOG.md** — per-product user-facing changelog per [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. Terse. Released versions only (plus `[Unreleased]` for in-flight work).

**Charter** — `CHARTER.md`, the Atrium's operational elaboration of [Constitution](#constitution-atrium) Articles III + IV. Defines the constellation pattern, membership criteria, retirement criteria, and cross-product authority.

**ColPali** — late-interaction visual retrieval model (Faysse et al. 2024). Different role than extraction Lenses: serves as the [Verification Lens](#verification-lens) in [Conclave](#conclave) by cross-checking extracted claims against rendered page images.

**Compounding Learning** [APEX] — Constitution §4 (NON-NEGOTIABLE) principle: every component produces TWO outputs — the artifact AND a learning trace. Atrium honors this via per-vote learning traces in Conclave audit logs and per-plugin trace fields in Curator audit entries.

**Conclave** — proposed Atrium charter member. Multi-Lens ensemble indexer for assessment knowledge bases. 5-12 [Lenses](#lens) run on the same source, vote on best output section-by-section. Full proposal in `Curator/docs/CONCLAVE_PROPOSAL.md`. Working name; voting-body metaphor.

**Constellation** — collective name for the Atrium's product family. Each product is a "star"; SIP is the gravitational binding. See [Charter](#charter) for the design pattern.

**Constellation pattern** — the architectural choice to build many tools that compose vs. one monolith. See `CHARTER.md`'s "Why standalone-first matters."

**Constitution (Atrium)** — `CONSTITUTION.md`, the binding governance document for the Atrium. Six Aims, Five Non-Negotiable Principles, six Articles. Version 0.1 awaiting Jake's ratification as of 2026-05-08.

**Constitution (APEX)** [APEX] — separate document, `Apex_Constitution_v0.5.docx`, BINDING since 2026-04-28. Atrium honors it; Atrium-side rules cannot override it.

**Curator** — Atrium's flagship charter member. File knowledge graph + lineage + bundles + sync + migration. Currently v0.41.0; Phase β at ~98%. Lives at `C:\Users\jmlee\Desktop\AL\Curator\`. Will become canonical state-of-disk authority in [Synergy](#synergy) realignment Phase 3.

**`curator_pre_trash`** — Curator plugin hook. Veto-style: any plugin returning `ConfirmationResult(allow=False, ...)` blocks the trash operation. Required mechanism for honoring the [MORTAL SIN rule](#mortal-sin-rule).

## D

**DE-N** — decision-pending tracker prefix used in `Curator/ECOSYSTEM_DESIGN.md`. Other prefixes: DM-N (migration decisions), DS-N (sync decisions), DA-N (asset monitor / Umbrella decisions), DI-N (installer / Nestegg decisions), DU-N (update protocol decisions), OQ-N (Conclave open questions). Numbers persist forever per [Rule 1.7](#rule-17).

## E

**ECOSYSTEM_DESIGN.md** — `Curator/ECOSYSTEM_DESIGN.md`. Captures Curator + APEX + Atrium integration design. Will eventually be split: Atrium-level pieces move to `Atrium/` directory; Curator-specific pieces stay in Curator.

## G

**GLOSSARY.md** — this document.

## H

**Hash discipline** — Atrium's commitment to SHA256 as the universal cross-product hash. Curator uses xxh3 internally for speed; SHA256 is added as secondary (per `ECOSYSTEM_DESIGN.md` §2.5). Conclave's audit logs use SHA256-chained JSONL per Inkblot's pattern.

**Hash-verify-before-move** — Constitution Principle 2 (NON-NEGOTIABLE): no file move completes without source-absent + destination-present + SHA256-hash-match verification. Inherited from APEX cleanup discipline (user memory 2026-05-01).

**High-Rigor Protocol (HRP)** [APEX] — APEX's `APEX_HIGH_RIGOR_PROTOCOL_v0_3_1.md`. Five-step workflow for modifying canonical APEX documents. Atrium does not adopt HRP wholesale but inspires the Atrium's Contributor Protocol's documentation discipline.

## I

**Inkblot** [APEX] — APEX subsystem (subAPEX1 + subAPEX6 combined). Rorschach scoring engine + Rorschach KB. Engine v1.1.0; KB partial. Source of the SHA256-chained JSONL audit log pattern Atrium adopts.

## L

**Late interaction** — retrieval architecture (ColBERT, ColPali) where query and document are encoded separately and matched at retrieval time via fine-grained interactions. Used by [Conclave](#conclave)'s [Verification Lens](#verification-lens).

**Lens** — a single extractor in [Conclave](#conclave)'s ensemble. Each Lens has a stable interface (takes source file + page range, returns `LensOutput`). Lenses run independently; failure in one doesn't affect others. Roster in `CONCLAVE_PROPOSAL.md` §3 + `CONCLAVE_LENSES_v2.md`.

**Lineage** — Curator concept: pairwise relationships between files (`duplicate`, `near_duplicate`, `version_of`, `derived_from`, `renamed_from`). Distinct from [Bundle](#bundle) (curated collections).

**Locker** [APEX] — APEX subsystem (subAPEX9). Course tools: PY638 Psychometrics, PY428 Stats II.

**Lorax** [APEX] — APEX's Constitution amendment codeword. Set to literal value `Lorax` at `Apex/Lorax`. Both signals required (verbal invocation + file presence).

## M

**Marker** — PDF-to-Markdown library (Vik Paruchuri). Used as Lens 4 (`MarkerPdf`) in Conclave. License: GPL-3 with commercial-use exception (license watch item).

**Master Scroll** [APEX] — APEX's `MASTER_SCROLL_v0_4.md`. Ranks above the Roadmap; below the Constitution. Names [Synergy](#synergy) as the canonical state-of-disk authority. Modifying requires Class C confirmation per [HRP](#high-rigor-protocol-hrp). The Synergy retirement triggers a Master Scroll edit in Phase 3 of the realignment.

**MCP** — Model Context Protocol. Anthropic's standard for AI-tool integration. Curator's planned MCP server (Candidate 2 in `ECOSYSTEM_DESIGN.md` §5) exposes read APIs as MCP tools. SIP §3.6 defines the cross-product naming convention `<tool>__<verb>`.

**MORTAL SIN rule** [APEX] — Constitution Principle 1 (NON-NEGOTIABLE): "NEVER delete or treat as regenerable any file generated from assessment sources — `Output\`, `kb\`, scrolls, extractions, indexes, `manifest.json`, `profile.json`, `verification_report`, or any processed artifact." Inherited from APEX Standing Rule 9 + user memory 2026-05-01. Operationalized via [`curator_pre_trash`](#curator_pre_trash) and the planned `curatorplug-atrium-safety` plugin.

## N

**Nestegg** — proposed Atrium charter member. Installer generator + system-spec-aware install + upgrade orchestration. Spun out of Curator's original Phase Δ Feature I.

**Nougat** — Meta's "Neural Optical Understanding for Academic Documents" (Blecher et al. 2023). Equation-aware scientific PDF extraction. Used as Lens 6 (`NougatScience`) in Conclave's expanded roster.

## O

**OQ-N** — Conclave open question prefix (OQ-1 through OQ-8 in `CONCLAVE_PROPOSAL.md` §9).

## P

**Phase** — Curator's development phases:
- **Phase α (alpha):** v0.0–v0.10. Foundational architecture. Closed.
- **Phase β (beta):** v0.11–v0.41. Optional plugins, GUI, gdrive plugin. Currently ~98% complete.
- **Phase γ (gamma):** Polish (bundle creation UI, gdrive auth helper, etc.).
- **Phase Δ (delta):** Migration, Sync, Update protocol. (Asset monitor + Installer spun out as Umbrella + Nestegg.)

**Periscope / Ark / Scrolls / Sources / Output / Tools / Lorax** [APEX] — APEX's canonical directory layout (Constitution v0.5).

**Pluggy** — the plugin framework Curator uses. Atrium products that need plugin extensibility default to pluggy unless they have a specific reason otherwise.

## R

**Rule 1.7** — see [`CONTRIBUTOR_PROTOCOL.md`](CONTRIBUTOR_PROTOCOL.md). Folder numbers persist forever; never reused.

## S

**Scribe** [APEX] — APEX's deductive cognitive entity (vs. [Augur](#augur)). Retrieval-only; produces clinical answers; never reasons from training data priors. Atrium-derived metadata can enrich Scrolls but never becomes a Scribe claim by itself.

**SHA256** — the cryptographic hash used across the Atrium for cross-product compatibility. APEX uses SHA256 throughout (Synergy snapshots, Inkblot audit chains). Curator uses xxh3_128 internally for speed; SHA256 is added as secondary per `ECOSYSTEM_DESIGN.md` §2.5.

**SIP** — Suite Integration Protocol. Currently v0.1; defined in `Curator/ECOSYSTEM_DESIGN.md` §3. Will move to `Atrium/SIP_SPEC.md` in a future revision. Defines health check, audit log format, hash discipline, configuration, plugin discovery, MCP convention, CLI conventions, version + compatibility, naming, and optional Compounding Learning.

**Sketch** [APEX] — APEX subsystem (subAPEX8). TAT Analysis Protocol (formerly codename "Cocoon"). Paused at v9 wrapper-prompt design.

**Standing Rule 3** [APEX] — "No new memory systems. Do not invent new master files, catalogs, blueprints, indexes, or memory systems. Use the existing ones in project knowledge." Formally rules out side-by-side Curator+Synergy as long-term state.

**Standing Rule 9** [APEX] — "Never delete assessment-derived artifacts." Same as the [MORTAL SIN rule](#mortal-sin-rule).

**Standing Rule 11** [APEX] — "Precision over Summarization." When in doubt, cite the document and section verbatim rather than paraphrasing. Atrium's documentation style follows this when referring to APEX rules.

**Succubus** [APEX] — APEX subsystem (subAPEX3). Next-generation 3-lane indexer (programmatic / offline / online). Design locked, not built. Conclave's relationship to Succubus is an OQ-1 question — Conclave could be Succubus's evolution, or a parallel constellation product.

**Synergy** [APEX] — APEX subsystem (subAPEX12). Multi-drive inventory + drift detection. Built v0.2.2 (2026-04-30). The canonical state-of-disk authority per Master Scroll v0.4. The Synergy/Curator overlap is the central ecosystem realignment question; phased B → A path documented in `ECOSYSTEM_DESIGN.md` §1.

## T

**Tessera trio** [APEX] — APEX's three operational documents at v1.9: Handoff (session-to-session), Claude Reference (what Claude needs to know), Project Chat Onboarding (for new chats).

**Triple-check** — shorthand for [hash-verify-before-move](#hash-verify-before-move) discipline.

## U

**UAP** [APEX] — Universal Assessment Protocol. APEX's predecessor; partially superseded by the Constitution.

**Umbrella** — proposed Atrium charter member. Health monitoring + dependency tracking + auto-Claude-troubleshoot. Spun out of Curator's original Phase Δ Feature A.

## V

**Vampire** [APEX] — APEX subsystem (subAPEX2). Current standalone PDF indexer (`APEX_Indexer`). Working v1.6, to be superseded by Succubus.

**Verification Lens** — a Conclave Lens whose role is verifying extracted content against the source page rather than independently extracting. ColPali (late-interaction retrieval) is the canonical example. See `CONCLAVE_LENSES_v2.md`.

## W

**Whats_Next, KB_Query, File_Placer, Rules_Editor, Session_Unzipper, Sort_Inventory, State_Bundle, Work_Package, Deploy_Session** [APEX] — Synergy ecosystem workflow tools.

---

## Cross-references and conventions

- **[APEX]** marks terms inherited from APEX with attribution.
- **Authority order:** Atrium Constitution > Charter > Contributor Protocol > Glossary > per-product docs. Where a term has product-specific meaning, the per-product doc may extend but not contradict the Glossary's definition.
- **Updates:** Add new terms when first used in any Atrium document. Don't define forward-looking terms speculatively.

---

*End of `GLOSSARY.md` v0.1.*
