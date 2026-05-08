# Atrium

**Governance layer for the Ad Astra suite.** Atrium is the umbrella body of constitutional principles, contributor protocols, naming conventions, and decision records that bind the suite's individual products (Curator, APEX, Synergy, and others) to a common set of values and operating rules.

This repository contains documents, not code. The code that **implements** Atrium's principles lives in the per-product repos (e.g. [`KULawHawk/Curator`](https://github.com/KULawHawk/Curator)).

---

## What Atrium is

Atrium is the answer to "how do these products stay coherent across years of evolution by a small number of contributors (currently one human + one AI collaborator)?" The answer is: a tiny core of explicit, ratified rules that everything else can be reasoned about in terms of. Specifically:

1. **A constitution** with numbered principles (Principle 1 — Reversibility, Principle 2 — Hash-Verify-Before-Move, Principle 3 — Plan/Apply Two-Phase, Principle 4 — No Silent Failures, Principle 5 — Atomic Operations). These are non-negotiable invariants every Ad Astra product must preserve.
2. **A charter** describing the suite's goals, scope, and values at a higher level than any individual product.
3. **A contributor protocol** — operating rules for human-AI collaborative development. Includes the numbered-list-with-number-replies convention, the `c` shorthand, the `Nm` 30-second-pitch convention, the wishlist-always-visible rule, the no-corner-cutting rule, and how those interact with safety practices.
4. **A glossary** pinning the meaning of every term that appears in more than one product. Avoids drift like "what does 'lineage' mean across Curator vs APEX?"
5. **A naming registry** (`NAMES.md`) tracking every brand name, capability name, and product name in the suite, with the open framing question §2.1 about Atrium-vs-Ad-Astra still under deliberation.
6. **An install-path design** (`INSTALL_PATH_DESIGN.md`) standardizing how Ad Astra products lay out their installed runtime data, so a user with multiple products gets a coherent on-disk experience.

The principles in §1 are the most important. Every product's design doc subordinates itself to the Atrium Constitution, and product PRs are evaluated against constitutional compliance.

---

## Documents

### Governance core

- [`CONSTITUTION.md`](CONSTITUTION.md) — the supreme authority. Numbered principles + their rationale. Status: ratification pending.
- [`CHARTER.md`](CHARTER.md) — suite-level goals and scope.
- [`CONTRIBUTOR_PROTOCOL.md`](CONTRIBUTOR_PROTOCOL.md) — operating rules for human-AI collaborative work, including the conventions (numbered lists, `c` shorthand, wishlist visibility, etc.) that make multi-session work navigable.
- [`GLOSSARY.md`](GLOSSARY.md) — canonical definitions for every cross-product term.
- [`ONBOARDING.md`](ONBOARDING.md) — how a new human or AI collaborator gets up to speed on the suite without re-reading all of git history.

### Naming and structural decisions

- [`NAMES.md`](NAMES.md) — brand registry. Pins "Ad Astra" as the suite name and "Tracer" as Curator's Migration capability brand, among others. §2.1 contains the open Atrium-vs-Ad-Astra framing question.
- [`INSTALL_PATH_DESIGN.md`](INSTALL_PATH_DESIGN.md) — the standardized on-disk layout for installed Ad Astra runtime data. Per-product subdirs under a single suite-level root.

### Meta

- [`META/CLAUDE_REFLECTION.md`](META/CLAUDE_REFLECTION.md) — accumulated reflections on the human-AI collaboration pattern itself; what works, what doesn't, what the AI should remember across instances.
- [`META/CLAUDE_LOGIC_GATES.md`](META/CLAUDE_LOGIC_GATES.md) — ~330 binary-toggle parameters extracted from past collaboration sessions; a meta-layer of operational rules indexed for fast retrieval.

---

## Status

| Document | Status |
|----------|--------|
| `CONSTITUTION.md` | drafted; **ratification pending** |
| `CHARTER.md` | drafted |
| `CONTRIBUTOR_PROTOCOL.md` | drafted; in active use |
| `GLOSSARY.md` | drafted |
| `ONBOARDING.md` | drafted |
| `NAMES.md` | drafted; **§2.1 (Atrium-vs-Ad-Astra framing) open** |
| `INSTALL_PATH_DESIGN.md` | drafted; deferred to end-of-build |
| `META/CLAUDE_REFLECTION.md` | living document |
| `META/CLAUDE_LOGIC_GATES.md` | living document (~330 gates) |

Ratification of the constitution is the next major governance milestone. Until then, the principles are operative-by-convention — products implement them, but they're not yet officially "the rules."

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
