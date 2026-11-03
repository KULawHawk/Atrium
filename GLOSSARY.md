# The Atrium Glossary

**Status:** v0.2 (APEX suite terms added)
**Date:** 2026-05-08 (v0.1); 2026-11-03 (v0.2)
**Authority:** Subordinate to `CONSTITUTION.md`. This document defines the terminology used across Atrium documents.

Terms are listed alphabetically. Cross-references are linked. APEX-borrowed terms are marked with [APEX] for attribution. Since v0.2, [APEX] marks terms from Jake's original assessment-indexing platform; terms for the APEX *suite* (see [APEX](#apex)) are plain entries.

**v0.2 note.** Jake ruled on 2026-10-23 12:21 PM CT (decision A1, `full-audit-2026-10-23/STRATEGY.md` §3) that APEX is the suite, Atrium is the integration layer, and Ad Astra is his developer and portfolio name. Entries below follow that ruling. Names are registered in `NAMES.md` v0.2.

---

## A

**Ad Astra** — Jake's developer and portfolio name for all of his projects, including ones unrelated to APEX. **Not the suite name** (A1, 2026-10-23 12:21 PM CT). v0.1 of `NAMES.md` used it as the suite name; that use is retired. The filesystem spelling `AdAstra` (the install root) still stands as the portfolio root.

**Affine** — APEX suite member that detects and corrects skew and warp on scanned or photographed pages and reports a confidence for each correction and the residual it could not fix. A correction that moves a table cell or a number is a high-stakes event and is deferred, not silently applied. **Formerly Deskew and MissSkew**, merged into one tool by Jake's ruling A2 (2026-10-23 12:23 PM CT, `full-audit-2026-10-23/STRATEGY.md` §3).

**APEX** — **the suite** (A1, 2026-10-23 12:21 PM CT, `full-audit-2026-10-23/STRATEGY.md` §3): a data-integrity and fidelity suite whose tools ([Conclave](#conclave), [Sequoia](#sequoia), [Verity](#verity), [Affine](#affine), [Locutus](#locutus), [Obsidian](#obsidian), [APEX hub](#apex-hub)) each work alone and also check one another as adversarial inspectors. Its slogan is **over.built**. Before A1 the name meant only Jake's Constitution-governed psychological assessment indexing platform at `C:\Users\jmlee\Desktop\AL\Apex\APEX\`, which has its own [Constitution](#constitution-apex) v0.5 BINDING since 2026-04-28; terms marked [APEX] in this Glossary come from that platform.

**APEX hub** — the APEX suite's front door and display. It shows each tool's outputs, the suite's numbers (human flags per source, repeat-flag rate, the blind audit slice's error bound, how often engines fail together, which [Pattern Packs](#patternpack) are in force), the [Obsidian](#obsidian) checklist and share screen, and the [Chaise](#chaise) status of every knowledge base. It hosts no computation and holds no authority.

**Atrium** — **the integration layer** that lets [APEX](#apex) and any future suite integrate with one another (A1, 2026-10-23 12:21 PM CT, `full-audit-2026-10-23/STRATEGY.md` §3). It owns the contracts that cross tool boundaries (see [contracts registry](#contracts-registry)) and the charter rules every tool keeps (`CHARTER.md`). It runs nothing. Originally (v0.1) the working name for the constellation of products this Glossary belongs to: [Curator](#curator), [Conclave](#conclave), [Umbrella](#umbrella), [Nestegg](#nestegg), with [APEX](#apex) as a peer. Lives at `C:\Users\jmlee\Desktop\AL\Atrium\` for governance docs (repo `KULawHawk/atrium`); products live at `C:\Users\jmlee\Desktop\AL\<Product>\`.

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

**Chaise** — the APEX suite's **clinical mode**: a named strictness profile, selected like a preset, that only ever tightens defaults. Required for any knowledge base certified for clinical use. Three knobs: **K1** auto-accept bar (every cleared voter agrees at very high confidence, from at least three independent Lens families), **K2** human kickback band (a wider share of the least-certain accepted values sent to review anyway), **K3** dual independent blind review on high-stakes values. A knowledge base records which mode produced it. Named by Jake 2026-10-23 3:35 PM CT; adopted 1:09 PM CT (`STRATEGY.md` §2 and §3a). "Clinical mode" in older text means Chaise.

**Charter** — `CHARTER.md`, the Atrium's operational elaboration of [Constitution](#constitution-atrium) Articles III + IV. Defines the constellation pattern, membership criteria, retirement criteria, and cross-product authority. Since v0.2 it also carries the APEX suite charter rules (standalone first, replayable, every input generalizes, high-stakes 100%-or-defer, the SEC-2 original-copy rule, Obsidian before patient data) and the two data paths (A3).

**ColPali** — late-interaction visual retrieval model (Faysse et al. 2024). Different role than extraction Lenses: serves as the [Verification Lens](#verification-lens) in [Conclave](#conclave) by cross-checking extracted claims against rendered page images.

**Compounding Learning** [APEX] — Constitution §4 (NON-NEGOTIABLE) principle: every component produces TWO outputs — the artifact AND a learning trace. Atrium honors this via per-vote learning traces in Conclave audit logs and per-plugin trace fields in Curator audit entries.

**Conclave** — APEX suite member (originally proposed as an Atrium charter member). Multi-Lens ensemble indexer that converts assessment manuals into reviewed, APEX-compatible knowledge bases. **19 engines** in public text: 18 built [Lenses](#lens) plus LENS-19 ABBYY FineReader, designed and not yet built (Jake, 2026-10-23 4:17 PM CT, `APEX_SUITE_DESCRIPTION.md`). Consensus is weighted by each Lens's measured calibration and counts only across different method families. Repo `KULawHawk/Conclave`. Original proposal in `Curator/docs/CONCLAVE_PROPOSAL.md`. Voting-body metaphor.

**Constellation** — collective name for the Atrium's product family. Each product is a "star"; SIP is the gravitational binding. See [Charter](#charter) for the design pattern.

**Constellation pattern** — the architectural choice to build many tools that compose vs. one monolith. See `CHARTER.md`'s "Why standalone-first matters."

**Constitution (Atrium)** — `CONSTITUTION.md`, the binding governance document for the Atrium. Ten Aims, Five Non-Negotiable Principles, six Articles. RATIFIED v0.3 on 2026-05-08. It still uses the pre-A1 names; aligning them needs an Article V amendment.

**Constitution (APEX)** [APEX] — separate document, `Apex_Constitution_v0.5.docx`, BINDING since 2026-04-28. Atrium honors it; Atrium-side rules cannot override it.

**Contracts registry** — `CONTRACTS_REGISTRY.md`, Atrium's list of the contracts that cross tool boundaries, one line per module, each owned by Atrium so that any current or future suite can use it. Examples: Locutus's [RulingRecord](#rulingrecord), [PatternPack](#patternpack), PartitionManifest, QueryRequest and ForgeRequest/ForgeOutput; Obsidian's ObsidianRequest, ObsidianResult, ObsidianSidecar, VaultEntry and ShareRecord. Tools exchange these as files, so no tool needs another running.

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

**Locutus** — the APEX suite's **shared learning component**. Every human ruling from every tool arrives as a [RulingRecord](#rulingrecord) and is assimilated into a central, versioned pattern library (the Canon), which flows back to each tool as signed, hash-pinned [Pattern Packs](#patternpack). Learned patterns start with authority only to flag, veto or defer and earn more through a measured promotion gate; high-stakes classes need Jake's explicit ruling. Locutus measures how often engines fail together and refuses any change that raises it, and a data firewall keeps learned or synthetic data out of clearance sets. It is never in a run's decision path at run time. Its Forge supplies degraded and synthetic test material to every tool. Own repo `KULawHawk/locutus` (J1, Jake, 2026-10-23 1:44 PM CT; design in `LOCUTUS_DESIGN.md`).

**Locker** [APEX] — APEX subsystem (subAPEX9). Course tools: PY638 Psychometrics, PY428 Stats II.

**Lorax** [APEX] — APEX's Constitution amendment codeword. Set to literal value `Lorax` at `Apex/Lorax`. Both signals required (verbal invocation + file presence).

## M

**Marker** — PDF-to-Markdown library (Vik Paruchuri). Used as Lens 4 (`MarkerPdf`) in Conclave. License: GPL-3 with commercial-use exception (license watch item).

**Master Scroll** [APEX] — APEX's `MASTER_SCROLL_v0_4.md`. Ranks above the Roadmap; below the Constitution. Names [Synergy](#synergy) as the canonical state-of-disk authority. Modifying requires Class C confirmation per [HRP](#high-rigor-protocol-hrp). The Synergy retirement triggers a Master Scroll edit in Phase 3 of the realignment.

**MCP** — Model Context Protocol. Anthropic's standard for AI-tool integration. Curator's planned MCP server (Candidate 2 in `ECOSYSTEM_DESIGN.md` §5) exposes read APIs as MCP tools. SIP §3.6 defines the cross-product naming convention `<tool>__<verb>`.

**MORTAL SIN rule** [APEX] — Constitution Principle 1 (NON-NEGOTIABLE): "NEVER delete or treat as regenerable any file generated from assessment sources — `Output\`, `kb\`, scrolls, extractions, indexes, `manifest.json`, `profile.json`, `verification_report`, or any processed artifact." Inherited from APEX Standing Rule 9 + user memory 2026-05-01. Operationalized via [`curator_pre_trash`](#curator_pre_trash) and the planned `curatorplug-atrium-safety` plugin.

## N

**Nestegg** — proposed Atrium charter member. Installer generator + system-spec-aware install + upgrade orchestration. Spun out of Curator's original Phase Δ Feature I.

**Obsidian** — the APEX suite's **de-identification module**. It removes identifiers from any file before the file leaves the PC or enters a shared store: a checklist of identifier types, burned-in boxes on images and forms, redaction markers in text, tone or silence over audio spans, and a leak check over every layer of the output. A password-protected original is always kept, with its password in the vault (SEC-2). It is a hard gate before any patient data enters the suite. Named by Jake 2026-10-23 3:32 PM CT (`STRATEGY.md` §2 and §3g; spec `DEIDENTIFY_MODULE_SPEC.md`). Its contracts are owned by Atrium. "De-identification module" in older text means Obsidian.

**Nougat** — Meta's "Neural Optical Understanding for Academic Documents" (Blecher et al. 2023). Equation-aware scientific PDF extraction. Used as Lens 6 (`NougatScience`) in Conclave's expanded roster.

## O

**OQ-N** — Conclave open question prefix (OQ-1 through OQ-8 in `CONCLAVE_PROPOSAL.md` §9).

## P

**Phase** — Curator's development phases:
- **Phase α (alpha):** v0.0–v0.10. Foundational architecture. Closed.
- **Phase β (beta):** v0.11–v0.41. Optional plugins, GUI, gdrive plugin. Currently ~98% complete.
- **Phase γ (gamma):** Polish (bundle creation UI, gdrive auth helper, etc.).
- **Phase Δ (delta):** Migration, Sync, Update protocol. (Asset monitor + Installer spun out as Umbrella + Nestegg.)

**PatternPack** — a Locutus contract (v1): a signed, hash-pinned bundle of promoted patterns for one consuming tool and authority level. It carries a pack id, consumer tool, Canon version, the list of artefacts (each with id, version, scope predicate, authority level, evidence summary and lineage hash), a signature and a SHA-256. Authority levels in order: `OBSERVE`, `FLAG`, `VETO`, `PREFILL`, `APPLY`. A tool loads a pack by hash and records the hash in its audit trail, so the run replays without Locutus; an empty pack must still work. Owned by Atrium (`LOCUTUS_DESIGN.md` §4).

**Path 1 / Path 2** — the APEX suite's two data paths (A3, Jake, 2026-10-23 12:24 PM CT). Path 1: a published manual becomes a reviewed knowledge base, then Sequoia decision trees; built first. Path 2: a completed protocol or session becomes scored, cited findings; new scope, gated on decision D1 and behind Obsidian. See `CHARTER.md`.

**Periscope / Ark / Scrolls / Sources / Output / Tools / Lorax** [APEX] — APEX's canonical directory layout (Constitution v0.5).

**Pluggy** — the plugin framework Curator uses. Atrium products that need plugin extensibility default to pluggy unless they have a specific reason otherwise.

## R

**RulingRecord** — a Locutus contract (v1): one record per human decision, from any tool. It holds the correct choice for the item and the structural breakdown of the item (its structure, pattern, format and presentation), plus the data partition assigned at capture. It is how the "every input generalizes" rule (`CHARTER.md`, Rule 3) is carried in practice: a human answer is never spent on one item. Owned by Atrium (`LOCUTUS_DESIGN.md` §4; schema `contracts/ruling_record.v1.schema.json` in the Locutus repo).

**Rule 1.7** — see [`CONTRIBUTOR_PROTOCOL.md`](CONTRIBUTOR_PROTOCOL.md). Folder numbers persist forever; never reused.

## S

**Scribe** [APEX] — APEX's deductive cognitive entity (vs. [Augur](#augur)). Retrieval-only; produces clinical answers; never reasons from training data priors. Atrium-derived metadata can enrich Scrolls but never becomes a Scribe claim by itself.

**SHA256** — the cryptographic hash used across the Atrium for cross-product compatibility. APEX uses SHA256 throughout (Synergy snapshots, Inkblot audit chains). Curator uses xxh3_128 internally for speed; SHA256 is added as secondary per `ECOSYSTEM_DESIGN.md` §2.5.

**SIP** — Suite Integration Protocol. Currently v0.1; defined in `Curator/ECOSYSTEM_DESIGN.md` §3. Will move to `Atrium/SIP_SPEC.md` in a future revision. Defines health check, audit log format, hash discipline, configuration, plugin discovery, MCP convention, CLI conventions, version + compatibility, naming, and optional Compounding Learning.

**Sequoia** — APEX suite member that compiles the rules in a verified knowledge base into decision forests: every variable becomes a logic gate, the generator expands exhaustively, and a symbolic verifier proves each gate set has no gaps or overlaps. Paths replay byte-identically. The Atrium Forensic scoring-engine brief merged into Sequoia as its output and form-fill layer (D6, Jake, 2026-10-23 12:35 PM CT). Repo `KULawHawk/sequoia`.

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

**Verity** — APEX suite member for high-fidelity transcription that verifies a transcript against its audio span by span. Corrections build an accent and pronunciation lexicon and expected-answer equivalence classes per test item. Staging per D1 (Jake, 2026-10-23 12:31 PM CT): verbal subtest responses first, then interviews, then full sessions. Session audio is patient data and goes through Obsidian.

**Verification Lens** — a Conclave Lens whose role is verifying extracted content against the source page rather than independently extracting. ColPali (late-interaction retrieval) is the canonical example. See `CONCLAVE_LENSES_v2.md`.

## W

**Whats_Next, KB_Query, File_Placer, Rules_Editor, Session_Unzipper, Sort_Inventory, State_Bundle, Work_Package, Deploy_Session** [APEX] — Synergy ecosystem workflow tools.

---

## Cross-references and conventions

- **[APEX]** marks terms inherited from APEX with attribution.
- **Authority order:** Atrium Constitution > Charter > Contributor Protocol > Glossary > per-product docs. Where a term has product-specific meaning, the per-product doc may extend but not contradict the Glossary's definition.
- **Updates:** Add new terms when first used in any Atrium document. Don't define forward-looking terms speculatively.

---

*End of `GLOSSARY.md` v0.2.*
