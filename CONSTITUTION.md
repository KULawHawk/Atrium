# The Atrium Constitution

**Status:** v0.1 — first ratified version
**Date:** 2026-05-08
**Authority:** This is the binding governance document for the Atrium constellation of products. Where this Constitution conflicts with any other document in any constellation product, this Constitution prevails.
**Ratification:** Jake Leese, 2026-05-08
**Amendment codeword:** TBD by Jake (proposed: `Keystone` — the load-bearing stone of an arch, fitting Atrium's architectural metaphor; alternatives: `Cornerstone`, `Threshold`, `Beacon`)

---

## Preamble

The Atrium is a constellation of independent software products that share a common foundation: each product fully functional standalone, each enhances the others when present, each respects the others' authority within their domains. The constellation exists because no single monolithic tool can serve every workflow well, but coordinated tools sharing common protocols can.

The five charter products are: **Curator** (file knowledge graph), **Conclave** (multi-Lens ensemble indexer), **Umbrella** (health monitoring + auto-troubleshoot), **Nestegg** (installer + system-spec orchestration), and bidirectional integration with **APEX** (Jake's Constitution-governed psychological-assessment platform; a peer system, not an Atrium member, but the integration is first-class).

This Constitution defines what the Atrium is, what it must always be, what it must never do, and how it is governed. Subordinate documents (the Charter, the Contributor Protocol, individual product DESIGN docs) implement these principles; they cannot contradict them.

---

## Article I — The Six Aims

Every Atrium product, every feature, every plugin, and every code change must serve these aims. Conflicts between aims are resolved by the order listed (earlier wins ties), with the following exception: any safety concern outranks all aims.

### Aim 1: Accuracy

Information that flows through the constellation must be correct. Where uncertainty exists, it must be surfaced — never silently elided. For derived data (hashes, classifications, lineage edges, ensemble votes), the derivation method and confidence must be recoverable from the audit log.

**Concrete commitments:**
- All hash claims are SHA256-verified before being trusted across product boundaries.
- All ensemble outputs (Conclave votes) preserve dissenting votes for review.
- All extracted content carries a chain back to its source.
- Where Conclave is involved, the constellation aspires to ≥99.5% accuracy on assessment KB construction (matching APEX's own §1 aim).

### Aim 2: Reversibility

Every action that changes user data must be reversible, or must explicitly declare itself irreversible and require confirmation proportional to the consequences.

**Concrete commitments:**
- File mutations go through trash/restore cycles, not direct delete (Curator's Phase α `TrashService` model).
- Database changes are append-only where possible; updates are logged with prior-state.
- Migrations record source-state hash so a botched migration is recoverable to the byte.
- Hard delete (no recovery) is gated by explicit user confirmation per file.

### Aim 3: Self-sufficiency

Every product runs standalone. No product requires another to function. When a product can leverage another (Curator queries from APEX, Conclave from Curator, etc.), the integration is opt-in and gracefully degrades when the partner is absent.

**Concrete commitments:**
- A user installing only Curator gets full Curator value.
- A user installing only Conclave gets full Conclave value.
- Cross-product integrations are gated by capability detection, not version pinning.
- An offline machine runs every Atrium product completely. (Cloud features — Curator's Drive plugin, Conclave's VisionClaude Lens — are explicit opt-ins with offline alternatives.)

### Aim 4: Auditability

Every change to user data is recorded in an audit trail. Every ensemble decision in Conclave records its votes. Every cross-product API call is logged. The constellation aspires to "every fact about every file at every moment in history is recoverable."

**Concrete commitments:**
- Append-only JSONL audit logs with SHA256 chain links (per APEX's `core/audit_trail.py` pattern).
- Cross-product audit-viewer compatibility (SIP §3.2).
- Per-vote learning traces in Conclave (matching APEX Constitution §4 Compounding Learning).

### Aim 5: Composability

Products integrate cleanly. The integration surface is small, documented, and SIP-compliant. Tight coupling between products is rejected even when convenient. Where products genuinely share logic, it lives in a separately-distributable plugin — never embedded in one product's core.

**Concrete commitments:**
- The Suite Integration Protocol (SIP) defines all cross-product contracts.
- Shared logic = pip-installable plugin packages, not internal copies.
- No product imports another's internals; only published interfaces.

### Aim 6: Portability

Every product must run on Windows, macOS, and Linux. Platform-specific code is explicitly isolated. A user moving from one OS to another loses no data and no functionality.

**Concrete commitments:**
- Cross-platform send2trash (Curator's Phase β gate 2 model).
- Cross-platform Filesystem operations through tested platform dispatchers.
- Configuration files are file-format-portable (TOML or JSON; never platform-specific binary formats).

---

## Article II — Non-Negotiable Principles

These principles cannot be amended by ordinary process. Modifying them requires the amendment codeword AND a written rationale AND an explicit acknowledgment from Jake that the principle is changing AND a 7-day waiting period before the change takes effect.

### Principle 1: The MORTAL SIN Rule

**No Atrium product, under any circumstances, deletes assessment-derived artifacts produced by APEX or any equivalent governance-bound system.**

This is inherited from APEX's Standing Rule 9 and the user memory entry of 2026-05-01: "NEVER delete or treat as regenerable any file generated from assessment sources — `Output\`, `kb\`, scrolls, extractions, indexes, `manifest.json`, `profile.json`, `verification_report`, or any processed artifact."

**Operationalization:**
- Curator's `curator_pre_trash` hook is required to be called for every trash operation.
- The Atrium-distributed `curatorplug-atrium-safety` plugin (when installed) registers veto handlers for assessment-derivation patterns.
- Violation of this rule is a Constitutional crisis requiring immediate investigation.

### Principle 2: Hash-Verify-Before-Move

**No file move, copy, or migration completes without source-absent + destination-present + SHA256-hash-match verification.**

Inherited from APEX's cleanup execution discipline (user memory 2026-05-01).

**Operationalization:**
- Curator's Migration tool (Phase Δ Feature M) implements this as non-negotiable, not configurable.
- All sync, migration, and bulk-move operations log the triple-check.
- A failed verification means the operation is rolled back AND the failure is escalated to user review.

### Principle 3: Citation Chain Preservation

**Information that originated in a sourced document maintains a chain back to that source through every transformation.**

Inherited from APEX Constitution §3 (Verification Mandate). Atrium products cannot break this chain even when they don't directly produce clinical claims.

**Operationalization:**
- Conclave outputs include source page references for every extracted claim.
- Curator's lineage edges preserve "this file derived from that file" relationships.
- Any cross-product data flow includes provenance metadata.

### Principle 4: No Silent Failures

**Errors are surfaced. Degraded modes are surfaced. Cost decisions (e.g., Conclave VisionClaude API calls) are surfaced before incurring.**

Atrium products never silently fall back to a worse mode without notifying the user. If Curator can't reach a gdrive source, it says so. If Conclave's VisionClaude Lens hits its budget cap, it pauses and asks. If Umbrella's health check finds a regression, it surfaces it.

**Operationalization:**
- Inherited from APEX's "no-API-key behavior" pattern (Standing Rule 8): never default to offline silently; alert + offer 3 options (proceed offline / pause / cancel).
- Per-product status commands (`<product> status`) report degraded modes explicitly.

### Principle 5: Atomic Operations Where Atomicity Is Claimed

**If an operation is documented as atomic, it must be atomic. Partial states are not acceptable.**

Examples currently in code: `Filesystem:edit_file` is per-call atomic (whole batch rolls back if any edit fails); Curator's `_perform_send_to_trash` is atomic (audit log + trash record + state update happen together or not at all); the planned Conclave write phase is atomic (all-or-nothing per assessment).

**Operationalization:**
- Atomicity claims in documentation are tested.
- Where true atomicity isn't possible (cross-process operations), the operation is documented as "checkpoint-based" not "atomic" and includes resume semantics.

---

## Article III — The Constellation Roster

### Charter members (committed)

1. **Curator** — file knowledge graph + lineage + bundles + sync + migration. **Status:** v0.41.0 shipped, Phase β at ~98%.
2. **Conclave** — multi-Lens ensemble indexer for assessment KBs. **Status:** Proposed (`docs/CONCLAVE_PROPOSAL.md`). ~120h to v1.0.
3. **Umbrella** — health monitoring + dependency tracking + auto-Claude-troubleshoot. **Status:** Spun out of Curator's original Phase Δ Feature A; not yet started.
4. **Nestegg** — installer generator + system-spec-aware install + upgrade orchestration. **Status:** Spun out of Curator's original Phase Δ Feature I; not yet started.

### Peer systems (integration partners)

- **APEX** — Constitution-governed psychological assessment indexing platform. Not an Atrium product, but Atrium products honor APEX's Constitutional constraints (MORTAL SIN, Self-sufficiency, Citation chain) and provide first-class integration via the SIP.

### Membership criteria

A new product joins the constellation only if it:
1. Is fully functional standalone (Aim 3)
2. Implements SIP-required protocols (Charter §4)
3. Is governed by this Constitution (no opt-out; charter membership = Constitutional acceptance)
4. Fills a domain not adequately covered by existing members (no internal competition)

### Retirement criteria

A constellation member is retired only when:
1. Another member fully covers its domain
2. The retiring member has no active users dependent on it
3. Jake explicitly approves
4. The Constitution is updated to remove the retiring member from Article III

---

## Article IV — Cross-Product Governance

### The Suite Integration Protocol (SIP)

The SIP defines the contract every Atrium product follows. Current version: **SIP v0.1**, defined in `Curator/ECOSYSTEM_DESIGN.md` §3 (will move to `Atrium/SIP_SPEC.md` in a future revision).

SIP v0.1 covers: health check protocol, audit log format, SHA256 universal hash, configuration conventions, plugin discovery, MCP server convention, CLI conventions, version + compatibility, naming conventions, optional Compounding Learning.

**Constitutional requirement:** Every charter member must implement all SIP-required protocols within 90 days of the SIP being formalized at v1.0. Current members get a v0.1-to-v1.0 grace period.

### Domain authority

Each product has authority within its domain. Other products consume its outputs but do not override its decisions:
- **Curator** is the canonical state-of-disk authority (in Synergy realignment Phase 3; in Phase 1-2 this is Synergy).
- **Conclave** is the canonical assessment-KB authority.
- **Umbrella** is the canonical health-status authority.
- **Nestegg** is the canonical installation-and-upgrade authority.
- **APEX** retains its full Constitutional authority over assessment workflows.

When products disagree on a fact within another product's domain, the domain-owner's view prevails.

### Cross-product safety

The MORTAL SIN rule (Principle 1) applies across the constellation. Any product implementing destructive operations on user files must respect every other product's stated safety rules. The mechanism: SIP-distributed safety plugins.

### Versioning across products

Atrium products use independent semver. Cross-product compatibility is declared explicitly:
- A product publishes a `compatibility.toml` listing the SIP version it implements + minimum versions of partner products it relies on for opt-in integrations.
- Breaking changes to the SIP require a major version bump on the SIP itself + a coordinated transition plan.

---

## Article V — Amendment Process

### Ordinary amendments

Amendments to Articles I (Aims), III (Roster), IV (Governance), or V (this article) require:
1. A written proposal with rationale
2. Jake's explicit affirmative approval (in writing in chat or in a commit)
3. Version bump on this Constitution

### Reinforced amendments

Amendments to Article II (Non-Negotiable Principles) additionally require:
1. The amendment codeword (TBD; proposed: `Keystone`)
2. A 7-day waiting period after Jake's affirmative
3. Written rationale documenting why the principle no longer holds

### Constitutional crisis

A "Constitutional crisis" is declared when:
- A non-negotiable principle is violated (intentionally or by bug)
- Two products' authority within their domains comes into irreconcilable conflict
- A product has shipped behavior that contradicts the Constitution

When declared:
1. All affected work pauses
2. The cause is documented
3. The fix is implemented
4. The Constitution may be updated to prevent recurrence
5. The crisis + resolution is recorded in `Atrium/CRISIS_LOG.md` (created on first crisis)

---

## Article VI — What This Constitution Is NOT

To prevent scope creep:

- **It is not a product specification.** Each product has its own DESIGN doc.
- **It is not an implementation plan.** That's the per-product roadmaps.
- **It is not a how-to guide for contributors.** That's `CONTRIBUTOR_PROTOCOL.md`.
- **It is not a glossary.** That's `GLOSSARY.md`.
- **It is not a status report.** That's per-product BUILD_TRACKER files.
- **It does not bind APEX.** APEX has its own Constitution (v0.5). The Atrium honors APEX's Constitution; APEX is not bound by this one.
- **It does not bind external Atrium-product users or plugin authors** beyond the licenses of each product. It binds the products themselves and anyone (human or Claude session) building on them within Jake's project.

---

## Ratification

This Constitution is ratified upon Jake Leese's affirmative acknowledgment in chat or in a commit message. Until ratified, it operates in `provisional` status — non-binding but informative.

**Ratification status:** Awaiting Jake's affirmation as of 2026-05-08.

---

*End of `CONSTITUTION.md` v0.1. Subordinate documents implement; this document governs.*
