# GUI design principles: ruling notes

Notes that Jake has approved in writing against `GUI_DESIGN_PRINCIPLES.md`. Each note narrows or qualifies one principle. A note does not change the principle's text anywhere else, and a note applies only as worded.

`GUI_DESIGN_PRINCIPLES.md` (v0.1, cited by the member specs) is kept in Jake's local Atrium folder and is not yet in this repository. Until it is, its notes are recorded here. When the file is brought in, each note below goes next to the principle it qualifies, word for word.

---

## Note 1: bounded group confirm for pattern-backed clusters (§5)

**Principle qualified.** §5 lists "batch accept on flagged items without per-item review" as a forbidden anti-pattern.

**Note.** A review screen may offer **one confirm for a cluster of look-alike items** only when every condition below holds. Outside these conditions §5 applies unchanged.

1. The cluster is built on a **known (Canon) pattern with a real scope test**. A cluster grouped by fingerprint alone, with no known pattern, gets one question per item.
2. The confirm covers **ordinary members only**. Every **high-stakes** member (cutoffs, norm tables, scoring rules, decision-tree branches, validity indicators, conversion algorithms, cross-reference resolutions) gets its own confirm. Pre-filling a high-stakes answer is a separate switch that ships **off** and is turned on only by Jake.
3. Each unshown member is covered only if it **passes the pattern's scope test on its own**. A member that fails becomes its own question. A member the reviewer marks "not the same" is split off and asked again.
4. The reviewer sees the examples the program is **least confident about first, then the most different**. The same item is never shown twice, exact duplicates are shown once with their count, and every shown item carries its confidence number. The confirm is offered only when **at least 3 distinct examples** were shown (until the member's uniform audit sample is live) and every example got the same ruling.
5. **No answer is pre-selected** on the screen (the never-nudge rules stay whole). Members accepted through a group confirm are recorded as such and are kept out of accuracy numbers.

**Approval.** Jake, in writing:
- **Decision 78** (2026-11-16): a cluster confirm covers ordinary members (option A).
- **Decision 84** (2026-11-16, 7:24 PM CT, reply "A A", where the second "A" answers item 2): "Decision 78 stands, and a short note is added to the top-level rules allowing it for pattern-backed groups only." Project chat message `cmsg_01ADpmwVyVfM6MQjhZTm9nKtLim8jemasca2h95nuUZTMr`, answering `cmsg_01ADpmwVyVfM6MQjhZTm9nKt7mzEJaSrEuKLHamdKr4LU6`.

**First user.** Conclave `SPEC_INFRA_ReviewConsole` v0.4 §4A (Conclave PR #2569). That spec's build gate holds the confirm control until this note is merged.
