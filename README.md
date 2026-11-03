# Atrium

**The integration layer for the APEX suite and any future suite.** Atrium owns the contracts that cross tool boundaries and the charter rules every tool keeps, together with the constitutional principles, contributor protocols, naming conventions, and decision records that bind the products to a common set of values and operating rules. It runs nothing.

Names, per Jake's ruling of 2026-10-23 12:21 PM CT (decision A1, recorded in `full-audit-2026-10-23/STRATEGY.md` §3):
- **APEX** is the suite: Conclave, Sequoia, Verity, Affine, Locutus, Obsidian and the APEX hub sit under it.
- **Atrium** is the integration layer that lets APEX and future suites integrate with one another.
- **Ad Astra** is Jake's developer and portfolio name for all of his projects. It is not the suite name (earlier versions of these docs called Ad Astra the suite).

This repository is mostly documents. Its one piece of code is `atrium_check` (`src/atrium_check/`, standard library only), which checks the contracts registry against the member repos. The code that **implements** Atrium's principles lives in the per-product repos (e.g. [`KULawHawk/Curator`](https://github.com/KULawHawk/Curator)).

---

## What Atrium is

Atrium is the answer to "how do these products stay coherent across years of evolution by a small number of contributors (currently one human + one AI collaborator)?" The answer is: a tiny core of explicit, ratified rules that everything else can be reasoned about in terms of. Specifically:

1. **A constitution** with numbered principles (Principle 1 — the MORTAL SIN rule, Principle 2 — Hash-Verify-Before-Move, Principle 3 — Citation Chain Preservation, Principle 4 — No Silent Failures, Principle 5 — Atomic Operations Where Atomicity Is Claimed). These are non-negotiable invariants every product governed by Atrium must preserve.
2. **A charter** describing the suite's goals, scope, and values at a higher level than any individual product, including the APEX suite charter rules (standalone first, replayable, every input generalizes, high-stakes 100%-or-defer, the original-copy rule) and the two data paths.
3. **A contracts registry** (`CONTRACTS_REGISTRY.md`, machine-readable in `registry/contracts.v1.json`) listing the cross-tool contracts Atrium owns, with sha256 pins that `python -m atrium_check check` compares against the member repos.
4. **A contributor protocol** — operating rules for human-AI collaborative development. Includes the numbered-list-with-number-replies convention, the `c` shorthand, the `Nm` 30-second-pitch convention, the wishlist-always-visible rule, the no-corner-cutting rule, and how those interact with safety practices.
5. **A glossary** pinning the meaning of every term that appears in more than one product. Avoids drift like "what does 'lineage' mean across Curator vs APEX?"
6. **A naming registry** (`NAMES.md`) tracking every brand name, capability name, and product name, with the ruling date and source for each.
7. **An install-path design** (`INSTALL_PATH_DESIGN.md`) standardizing how Jake's products lay out their installed runtime data, so a user with multiple products gets a coherent on-disk experience.

The principles in §1 are the most important. Every product's design doc subordinates itself to the Atrium Constitution, and product PRs are evaluated against constitutional compliance.

---

## Documents

### Governance core

- [`CONSTITUTION.md`](CONSTITUTION.md) — the supreme authority. Numbered principles + their rationale. Status: RATIFIED v0.3 (2026-05-08).
- [`CHARTER.md`](CHARTER.md) — suite-level goals and scope, the APEX suite charter rules, and the two data paths.
- [`CONTRACTS_REGISTRY.md`](CONTRACTS_REGISTRY.md) — the cross-tool contracts Atrium owns.
- [`CONTRIBUTOR_PROTOCOL.md`](CONTRIBUTOR_PROTOCOL.md) — operating rules for human-AI collaborative work, including the conventions (numbered lists, `c` shorthand, wishlist visibility, etc.) that make multi-session work navigable.
- [`GLOSSARY.md`](GLOSSARY.md) — canonical definitions for every cross-product term.
- [`ONBOARDING.md`](ONBOARDING.md) — how a new human or AI collaborator gets up to speed on the suite without re-reading all of git history.

### Naming and structural decisions

- [`NAMES.md`](NAMES.md) — brand registry. Pins APEX as the suite, Atrium as the integration layer, Ad Astra as the portfolio name, and registers every suite member (Conclave, Sequoia, Verity, Affine, Locutus, Obsidian, Chaise, the APEX hub), plus "Tracer" as Curator's Migration capability brand.
- [`INSTALL_PATH_DESIGN.md`](INSTALL_PATH_DESIGN.md) — the standardized on-disk layout for installed runtime data under the `AdAstra` portfolio root (its "Ad Astra suite" wording predates the A1 ruling). Per-product subdirs under a single portfolio-level root.

### Meta

- [`META/CLAUDE_REFLECTION.md`](META/CLAUDE_REFLECTION.md) — accumulated reflections on the human-AI collaboration pattern itself; what works, what doesn't, what the AI should remember across instances.
- [`META/CLAUDE_LOGIC_GATES.md`](META/CLAUDE_LOGIC_GATES.md) — ~330 binary-toggle parameters extracted from past collaboration sessions; a meta-layer of operational rules indexed for fast retrieval.

---

## Status

| Document | Status |
|----------|--------|
| `CONSTITUTION.md` | **RATIFIED v0.3** (2026-05-08); still uses pre-A1 names, alignment needs an Article V amendment |
| `CHARTER.md` | v0.2; APEX suite charter rules and the two data paths added (2026-10-23 rulings) |
| `CONTRACTS_REGISTRY.md` + `registry/contracts.v1.json` | living; 17 contracts pinned, checked by `atrium_check` |
| `CONTRIBUTOR_PROTOCOL.md` | drafted; in active use |
| `GLOSSARY.md` | v0.2; APEX suite terms added |
| `ONBOARDING.md` | drafted |
| `NAMES.md` | v0.2; §2.1 (Atrium-vs-Ad-Astra framing) **closed by A1** (2026-10-23) |
| `INSTALL_PATH_DESIGN.md` | drafted; deferred to end-of-build |
| `META/CLAUDE_REFLECTION.md` | living document |
| `META/CLAUDE_LOGIC_GATES.md` | living document (~330 gates) |

The constitution was ratified on 2026-05-08 (v0.3). The next governance milestone is an Article V amendment that brings its roster and authority sections in line with the A1 naming ruling.

---

## Relationship to product repos

Atrium is not a code dependency. Product repos do not import Atrium. The relationship is **doctrinal**:

- Each product's design doc cites the Atrium Constitution as its supreme authority.
- Each product's commit messages cite specific Atrium principles when relevant ("preserves Constitution Principle 2").
- Each product's CHANGELOG entries note constitutional compliance for major features.

The first product to fully cite Atrium is [`KULawHawk/Curator`](https://github.com/KULawHawk/Curator). v1.1.0's `docs/TRACER_PHASE_2_DESIGN.md` and `CHANGELOG.md` both reference Atrium Principle 2 (Hash-Verify-Before-Move) as the discipline every migration path must preserve.

---

## How to read this repo if you're new

1. Start with [`CHARTER.md`](CHARTER.md) — the suite's goals.
2. Then [`CONSTITUTION.md`](CONSTITUTION.md) — the rules.
3. Then [`GLOSSARY.md`](GLOSSARY.md) if any term confuses you.
4. Then [`CONTRIBUTOR_PROTOCOL.md`](CONTRIBUTOR_PROTOCOL.md) if you're going to collaborate.
5. Everything else is reference material — read on demand, not front-to-back.

---

## License

TBD. Atrium docs are currently under no public license; treat them as all-rights-reserved by Jake Leese until a formal license is chosen. (Suggested default when the time comes: CC BY 4.0 for documents, MIT for any code that ships in this repo.)
