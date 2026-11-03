# APEX suite conformance matrix (Atrium rules)

Status: evidence snapshot, 2026-11-03. Read-only audit; no member repo was changed.

This file checks each APEX tool against the suite rules Atrium owns. Every "Meets" cites a file. Paths are relative to the named repo, and each repo was read at the commit below (`git -C <repo> rev-parse --short HEAD`).

| Repo | Checkout | Commit read | Commit date |
|---|---|---|---|
| Conclave | /home/user/Conclave (main) | `b66d3b8` | 2026-10-29 |
| Locutus | /home/user/locutus | `f0a5d42` | (branch claude/project-thread-cglz8t) |
| Sequoia | /home/user/sequoia | `e858ca2` (moved from `4dfdad9` during this audit; the only new commit is a WORK_REGISTRY claim, see S-R5) | 2026-11-03 |
| Obsidian | /home/user/obsidian | `d50b5c7` | 2026-10-28 |

## The rules checked

Sources: `/mnt/project-files/full-audit-2026-10-23/APEX_SUITE_DESCRIPTION.md` ("Atrium" section, line 71), `STRATEGY.md` §2a (line 77), `BLUEPRINT.md` (line ~257, the standing acceptance rule and SEC-2), and this repo's `CONSTITUTION.md` Article II and `CHARTER.md`.

- **R1 Standalone first.** A tool ships and tests without importing another tool's internals. Data crosses boundaries, not symbols.
- **R2 Replayable.** Same inputs give the same output, and records carry what is needed to replay.
- **R3 Every input generalizes.** Every human ruling records the choice and a structural breakdown of the item (Locutus `RulingRecord/1`).
- **R4 High-stakes 100%-or-defer.** `defer_to_human` is a first-class outcome.
- **R5 Contracts owned by Atrium.** Versioned schema files; v1 changes additive only and logged; a breaking change is v2.
- **R6 SEC-2 original copy.** In-place edit only while a password-protected original is kept, with its password in the vault.
- **P1-P5 Constitution principles,** as named in this repo's `README.md` line 13: P1 Reversibility, P2 Hash-Verify-Before-Move, P3 Plan/Apply Two-Phase, P4 No Silent Failures, P5 Atomic Operations.

Note on P1-P5: the README list and `CONSTITUTION.md` Article II disagree. Article II's five are MORTAL SIN (no deletion of assessment-derived artifacts), Hash-Verify-Before-Move, Citation Chain Preservation, No Silent Failures, and Atomic Operations. Reversibility is Aim 6, and Plan/Apply Two-Phase appears nowhere in `CONSTITUTION.md`. This matrix uses the README list as instructed, folds MORTAL SIN into P1, and notes Citation Chain where a tool carries it. See Atrium-side gap A2.

Status words: **Meets** (cited code does it), **Partial** (done on some paths or only in part), **Gap** (not done where it applies), **N/A** (the tool does nothing the rule governs).

## Summary

| Rule | Conclave | Locutus | Sequoia | Obsidian | Verity | Affine | APEX hub |
|---|---|---|---|---|---|---|---|
| R1 standalone | Partial | Meets | Meets | Meets | not built | not built | not built |
| R2 replayable | Partial | Meets | Meets | Partial | not built | not built | not built |
| R3 generalizes | **Gap** | Meets | **Gap** | **Gap** | not built | not built | not built |
| R4 100%-or-defer | Meets | Meets | Meets | Meets | not built | not built | not built |
| R5 Atrium contracts | Gap | Partial | Gap (in flight) | Meets | not built | not built | not built |
| R6 SEC-2 original | Partial | N/A | N/A | Meets | not built | not built | not built |
| P1 Reversibility | Meets | Meets | N/A | Meets | not built | not built | not built |
| P2 Hash-verify | Partial | Meets | N/A | Meets | not built | not built | not built |
| P3 Plan/Apply | Partial | N/A | N/A | Meets | not built | not built | not built |
| P4 No silent fail | Meets | Meets | Meets | Meets | not built | not built | not built |
| P5 Atomic | Meets | Meets | N/A | Meets | not built | not built | not built |

Three of the four built tools fail R3 on the path a human uses. Conclave and Obsidian both have a working RulingRecord emitter, but no production code path constructs or configures it. Sequoia has no emitter at all. All three are wiring gaps, not design gaps.

---

## Conclave (`b66d3b8`)

Large monorepo of `conclave_*` spokes. Grep-based reading; the repo's own CLAUDE.md files were read as context only.

**R1 standalone first: Partial.**
Evidence for: per-spoke directories with an enforced OFF-LIMITS list (`scripts/check_off_limits.py`, header lines 1-25). The GUI never imports the runner; it composes a subprocess argv (`conclave_infra_workbench/src/conclave_workbench/pages/runs/launch/plan.py`, docstring lines 1-20). Peer tools are consumed through pinned, sha-checked vendored mirrors (`conclave_vendor_locutus/README.md`, `tests/test_vendor_parity.py`; `conclave_vendor_obsidian/VENDORED_FROM.json` at Obsidian `ce33e77`).
Evidence against: production code imports Locutus and Obsidian symbols, not only their data. `conclave_integration_locutus_rulings/src/conclave_locutus_rulings/adapter.py:45-46` (`locutus.firewall.PartitionRegistry`, `locutus.signature.fallback_signature`), `.../lens_map.py:14` (`locutus.families`), `conclave_integration_locutus_pack/src/conclave_locutus_pack/consumer.py:30-31` (`locutus.contracts.validate`, `locutus.packs.verify`), `conclave_integration_e2e_regression/src/conclave_e2e_regression/firewall_gate.py:38,48`, `conclave_infra_votingengine/src/conclave_voting/shape_veto.py:227` (lazy `locutus.contracts.validate_scope`), `conclave_lens_adjudicator/src/conclave_lens_adjudicator/lens.py:1052` and `conclave_lens_visionclaude/src/conclave_lens_visionclaude/lens.py:740` (`obsidian.egress.for_automated`). The core voting engine declares `locutus>=0.1,<0.2` as a hard dependency (`conclave_infra_votingengine/pyproject.toml:42`) although its only use is lazy. `conclave_sequoia_bridge/integration_gui.py:172-173` imports `sequoia` symbols, guarded by try/except.
Gap: Conclave cannot be installed without Locutus, and its ruling and pack paths execute Locutus code. Smallest fix: move `locutus` in `conclave_infra_votingengine/pyproject.toml` to an optional extra (the import is already lazy), and record the Obsidian egress import as a sanctioned fail-closed safety dependency in the Atrium Charter, since replacing it with data would weaken the patient-file gate.

**R2 replayable: Partial.**
Evidence: the harness requires a `ReplayManifest` before any release-gate verdict (`conclave_test_harness/src/conclave_test_harness/schemas/replay_manifest.py`, docstring lines 1-5; field `self_replay_verified` at line 627). The in-process self-replay engine re-runs the CPU-deterministic slice (`conclave_harness_adapters/src/conclave_harness_adapters/self_replay.py`, lines 1-40).
Gap: model-inference stages (Lens invocation, Adjudicator) are recorded as unreplayable here (same file, lines 11-17, 76), so a full run is not byte-replayable from its records; the deterministic slice is. Smallest fix: none needed for the CPU slice; for the rest, the GPU acceptance side build is the stated mechanism, so the gap is to record per-stage model id and weights hash in the manifest so a GPU replay can be checked, if not already present.

**R3 every input generalizes: Gap (high-stakes path).**
Evidence: the emitter exists and is correct: `conclave_integration_locutus_rulings/src/conclave_locutus_rulings/console.py:48` (`LocutusReviewConsole`), `adapter.py` (`LocutusRulingsAdapter`, writes `out/locutus/rulings.jsonl`), with K3 support (`tests/test_k3.py`).
Verified against code: no production code constructs it. The only two production Console constructions are plain `ReviewConsole`: `conclave_infra_workbench/src/conclave_workbench/pages/review/store.py:178` (GUI) and `conclave_infra_reviewconsole/src/conclave_review/cli.py:353` (CLI). Every `LocutusReviewConsole(` / `LocutusRulingsAdapter(` call site is under a `tests/` directory. The e2e suite pins the gap with a strict xfail: `conclave_integration_e2e_regression/tests/test_chain_review_daemon.py:403` (`reason="L0.3a: GUI Console has no ruling_sink"`). Matches ASSIGNMENTS.md row L0.3a (priority raised 10/27) and DELIVERY_LOG 10/29 2:25 AM ("the remaining xfail is L0.3a RulingRecord").
Gap: every human ruling made in the Workbench or the review CLI, including high-stakes cutoffs and K3 dual reviews, is used for that one instance only, which is exactly what STRATEGY §2a forbids. Note the scope is wider than L0.3a states: the CLI path is also plain. Smallest fix: in `console_factory` (`store.py:168`) and `cli.py:353`, wrap the Console in `LocutusReviewConsole` with a `LocutusRulingsAdapter` over the run's `out/`, then flip the strict xfail at line 403.

**R4 high-stakes 100%-or-defer: Meets.**
Evidence: `conclave_infra_votingengine/src/conclave_voting/voting.py:902-910` (Stage 4 refuses to vote a `defer_to_human` routing) and `:986`, `:1009` (`adjudicator_verdict_kind = "defer_to_human"` on voter failure and high-stakes disagreement). The KB writer withholds a PLACEHOLDER rather than letting a human ACCEPT land a refused value (`conclave_infra_apexbridge/src/conclave_bridge/kb_output.py:38-41`). Page-level defers are first-class review items (`conclave_infra_reviewconsole/src/conclave_review/kb_patcher.py:148`, `apply_page_defer`).

**R5 contracts owned by Atrium: Gap.**
Evidence: Conclave's outbound contracts (the APEX KB master bundle, `verify_apex_format` at `conclave_infra_apexbridge/src/conclave_bridge/apex_format.py:237`; the shared models in `conclave_contracts/src/conclave/contracts/`, e.g. `finalize.py`; the Conclave-to-Sequoia KB-input translation in `conclave_sequoia_bridge/`) are Python models inside Conclave, not versioned schema files, and none appears in `CONTRACTS_REGISTRY.md`. Inbound Locutus contracts are consumed by vendoring all of Locutus at `f0a5d42` (`conclave_vendor_locutus/VENDORED_FROM.json`), which pins the schemas but also pins the code.
Gap: the KB master and the Sequoia hand-off are suite-crossing edges with no Atrium-registered schema or change log. Smallest fix: export a JSON Schema for the KB master record and register it (one line) in `CONTRACTS_REGISTRY.md`, with a CONTRACTS.md change log in Conclave on the Obsidian pattern.

**R6 SEC-2 original copy: Partial.**
Evidence: `KBPatcher` edits `kb_output.jsonl` in place (`conclave_infra_reviewconsole/src/conclave_review/kb_patcher.py:58`, `:114` reads original bytes, `:141` restores them on rollback). The pre-review sealed generation is kept separately (5.1 sealed generations, #2275, per DELIVERY_LOG) and sealing is read-only (`conclave_infra_apexbridge/src/conclave_bridge/cli.py:263`).
Gap: the kept original is read-only but not password-protected and has no vault entry. Whether SEC-2 covers Conclave's own derived artifacts (not patient files) is not ruled. Smallest fix: Atrium rules the scope of SEC-2 for derived artifacts; if it applies, call Obsidian `keep_original` (or an equivalent) before the first `KBPatcher` write per run.

**P1 Reversibility: Meets.** Reopen retracts a ruling's KB patch and page-defer (`kb_patcher.py:236` `retract_page_defer`, `:291` `retract_resolution`); the Locutus side gets a `RulingRetraction/1` from `conclave_locutus_rulings/console.py:99` (when that console is used, see R3). Sealed bundles are never overwritten (`kb_output.py:46-52`, `KbOutputExistsError`).

**P2 Hash-Verify-Before-Move: Partial.** Conclave moves almost no user files; the corpus manifest is hash-frozen and re-checked (`self_replay.py:20-23`). Gap: the ruling adapter content-addresses a crop and then copies it with no post-copy verify and no temp file (`conclave_integration_locutus_rulings/src/conclave_locutus_rulings/adapter.py:503-512`), so an interrupted copy leaves a truncated file under a valid-looking hash name that later runs skip because `dest.exists()`. Smallest fix: copy to a temp name, re-hash, then `os.replace`.

**P3 Plan/Apply: Partial.** The seal always prints a dry-run preview and runs only with `--confirm` (`conclave_infra_apexbridge/src/conclave_bridge/cli.py:263-282`), and launches are composed as plans before spawn (`pages/runs/launch/plan.py`). Gap: Review-page rulings apply KB patches immediately with no preview step; this is acceptable only because P1 reopen exists. Smallest fix: none required if Atrium accepts reopen-as-undo as the second phase; otherwise state that in the Charter.

**P4 No Silent Failures: Meets.** Runs end as `degraded` rather than succeeded when Lenses fail (`conclave_harness_adapters/src/conclave_harness_adapters/run_events.py:118-144`); missing Obsidian fails closed with a named reason (`conclave_lens_adjudicator/.../lens.py:1050-1056`); candidate conflicts raise rather than pick (`kb_output.py:42-45`).

**P5 Atomic Operations: Meets.** KB writes go temp + fsync + `os.replace` (`kb_output.py:174`; `kb_patcher.py` header lines 5-6) inside an `AtomicTransaction` with registered undo (`conclave_infra_reviewconsole/src/conclave_review/transaction.py:35`). The one documented non-atomic window is named in the docstring (`kb_output.py:50-55`).

Citation chain (Article II P3): carried by design (Constitution operationalization names Conclave page references); not separately audited here.

---

## Locutus (`f0a5d42`)

**R1 standalone first: Meets.** Runtime dependencies are `jsonschema` and `cryptography` only (`pyproject.toml:10`). No `src/` module imports Conclave, Sequoia or Obsidian (grep of `src/`). Tools load packs by hash and an empty pack is valid (`README.md` ground rules; `src/locutus/contracts/pattern_pack.v1.schema.json:5`). One dev driver outside the package imports Conclave (`tools/coupling_run.py:26-28`) under the optional `coupling` extra; it is not shipped.

**R2 replayable: Meets.** Packs have canonical bytes, `pack_sha256` and Ed25519 sign/verify (`src/locutus/packs.py:25-54`). The audit log is hash-chained (`src/locutus/audit.py`, `append` line 62, `verify` line 77). The Bus re-reads every drop file each scan (`src/locutus/bus/ingest.py`, docstring lines 1-6). Partition assignment is a keyed hash, write-once (`src/locutus/firewall/registry.py:76-86`, no-delete triggers). Committed Track S data reproduce without rebuild (`README.md`, 6.13 row).

**R3 every input generalizes: Meets.** Locutus is the receiving end. `RulingRecord/1` requires both `decision` and `structure` plus `issue_signature` (`src/locutus/contracts/ruling_record.v1.schema.json:8`); `structure` requires `described_by`, `features`, `reviewer_confirmed` (line 141). Invalid records are quarantined with a reason, not dropped (`bus/ingest.py:117-119`). Retractions are honored by every store query (`src/locutus/store/store.py:147`, `include_retracted=False` defaults at 174-181).

**R4 100%-or-defer: Meets.** Locutus "can make the suite ask; it cannot make the suite accept" (`README.md`). `APPLY` on a high-stakes class requires a graduation record, enforced in the schema (`pattern_pack.v1.schema.json:40,46-47`). `would_have_shipped` is null when the vote would have deferred (`ruling_record.v1.schema.json:103`).

**R5 contracts owned by Atrium: Partial.** Versioned schema files ship as package data (`src/locutus/contracts/*.v1.schema.json`; `pyproject.toml:20-21`), and changes are logged with dates (`docs/CONTRACT_CHANGES.md`).
Gap: (a) none of the six Locutus contracts (RulingRecord, RulingRetraction, PatternPack, PartitionManifest, QueryRequest, Forge) is in `CONTRACTS_REGISTRY.md`, although `APEX_SUITE_DESCRIPTION.md:73` names them as Atrium-owned. (b) The 2026-10-23 L0.2 entry made `issue_signature`, `bbox_space` and `pack_sha256` required and turned `engine_family` into an enum, and the log itself says "Tightenings beyond pure addition" (`docs/CONTRACT_CHANGES.md:5,15`); under R5 that is a breaking change kept at v1, justified only by there being no records on file yet. Smallest fix: add the Locutus line to `CONTRACTS_REGISTRY.md`, and add a one-line note there that pre-first-record tightenings on 2026-10-23 are grandfathered as v1 and that the next one must be v2.

**R6 SEC-2: N/A.** Locutus edits no user or source file; the Reference Store and blob store are append-only (`store/store.py:93-101`).

**P1 Reversibility: Meets.** Append-only ruling store; retraction is a new record and there is no un-retract (`README.md`; `docs/CONTRACT_CHANGES.md` 2026-10-28). SQLite triggers block deletes on assignments and manifests (`firewall/registry.py:76,83`).
**P2 Hash-verify: Meets.** Blobs are content-addressed (`store/store.py:93-101`); packs are loaded by hash and verified (`packs.py:42-54`).
**P3 Plan/Apply: N/A.** No user-file mutation. (Pattern promotion is gated by the Promotion Gate, which is a stronger analogue.)
**P4 No Silent Failures: Meets.** Quarantine with reason; T5 coverage report (`python -m locutus.bus.report`, `bus/report.py`); `check_clearance_run` refuses rather than warns (`docs/CONTRACT_CHANGES.md` 2026-10-28).
**P5 Atomic: Meets.** Blob write is temp + replace (`store/store.py:98-100`); audit append holds an exclusive lock (`audit.py:29`). Minor: report writers in `observatory/coupling_adapter.py:421-425` write directly, but those are regenerable reports, not records.

---

## Sequoia (`e858ca2`)

**R1 standalone first: Meets.** SD-9 firewall stated in every integration module (`sequoia/integration/kb_input.py:10`, `sequoia/integration/audit.py:10-11`) and enforced by a test that greps the package for any `conclave`/`apex` import (`tests/compile/test_fixtures.py:216-219`). Runtime imports are stdlib only (grep of `sequoia/`); z3 is an optional cross-check that the scoring path never imports (`tests/generate/test_crosscheck_z3.py:113`).

**R2 replayable: Meets.** The audit record carries inputs, forest version, interpreter version and path, and `replay()` re-derives the run and compares a canonical-JSON digest (`sequoia/integration/audit.py:1-13`, `canonical_json` line 36, `replay` line 215). Generated forests replay via certificate hashes (`docs/SPEC_REPLAY.md`, `sequoia/integration/generated.py`).

**R3 every input generalizes: Gap.** Human input in Sequoia is the go-live attestation: `HumanConfirmation` (`sequoia/verify/golive.py:114`) and `GeneratorAttestation` (`golive.py:165`) record reviewer, date, counts and a pass verdict. Neither carries a structural breakdown, and nothing in `sequoia/` emits a `RulingRecord` (grep finds no `RulingRecord` or `rulings.jsonl`), although `tool: sequoia` is already in the RulingRecord enum (Locutus `ruling_record.v1.schema.json:37`) and STRATEGY §2a names "Sequoia corrections and attestation" explicitly.
Gap: a reviewer's walk-through findings and any correction are spent on one forest. Smallest fix: when a `HumanConfirmation`/`GeneratorAttestation` is recorded with findings, write one RulingRecord per finding to `<out>/locutus/rulings.jsonl` using the existing `gate_id` locator kind (`ruling_record.v1.schema.json:73`), as plain JSON with no Locutus import.

**R4 100%-or-defer: Meets.** `defer_to_human` is a first-class terminal that propagates through sub-trees (`sequoia/interpreter.py:103-110`, `:401-403`, `:530-532`); wrongly typed input defers rather than errors (`interpreter.py:103`). The go-live gate requires the HUMAN class and `attestation_policy` can only be `"required"` (`sequoia/verify/gateset/certificate.py:28`, `:141-142`).

**R5 contracts owned by Atrium: Gap (work in flight).** The inbound `KBInput` contract is specified in prose with a semver field (`docs/SPEC_KB_INPUT.md` §2, `kb_input_version`), and the outbound audit record is versioned only by a code constant (`sequoia/integration/audit.py:27`, `AUDIT_SCHEMA_VERSION = "0.1.0"`). There is no schema file and no Atrium registry line. Commit `e858ca2` adds a WORK_REGISTRY claim "ATRIUM-C" for exactly this: JSON Schema 2020-12 files for `KBInput/1` and `ApexAuditRecord/1` plus CONTRACTS.md. Smallest fix: land ATRIUM-C and add its line to `CONTRACTS_REGISTRY.md`.

**R6 SEC-2: N/A.** Sequoia writes no files (grep of `sequoia/` for `write_text`, `os.replace`, `unlink`, `rmtree` is empty).

**P1-P3, P5: N/A** (pure functions over data; no file mutation). **P4 No Silent Failures: Meets.** An invalid or absent confirmation is a finding, never a silent pass, and each reason is reported (`golive.py:138-157`, SD-12); certificate mismatches name every disagreeing member (`docs/SPEC_REPLAY.md:24`).

Citation chain: every audit record carries claim to citation to node `source_pages` to registry page and optional SHA (`audit.py:3-5`, `_citation_chain` line 80). Meets.

---

## Obsidian (`d50b5c7`)

**R1 standalone first: Meets.** Locutus is never imported at module load; the partitioner is injected and the one Locutus import is lazy and optional (`src/obsidian/locutus_bridge.py:1-8,19-23`; `src/obsidian/rulings.py:1-12`). The RulingRecord shape is pinned by a schema replica, not an import (`tests/fixtures/locutus/PIN.json`).

**R2 replayable: Partial.** The sidecar records version, preset, item types replaced, counts, verification result, source and output sha256 and name-detection mode (`src/obsidian/contracts/obsidian_sidecar.v1.schema.json`, required list).
Gap: the sidecar does not identify the reviewed checklist (which occurrences were toggled and the replacement text per item), and a `custom_<hex8>` preset's content lives in settings, so the output cannot be re-derived from the record. Smallest fix: add an optional `checklist_sha256` (hash of the canonical reviewed checklist, no values) to `ObsidianSidecar/1` as a logged additive v1 change, and keep the checklist next to the vault entry.

**R3 every input generalizes: Gap.** The emitter exists: each confirmed detection, reviewer-added miss and rejected false positive becomes a RulingRecord with positions, shapes and features, never values (`src/obsidian/rulings.py:1-12`, `build` line 66; `locutus_bridge.py:36-40`).
Verified against code: the UI emits only when `self.locutus` is set (`src/obsidian/ui/session.py:195-197`), it is initialised to `None` (`session.py:113`), and nothing in `src/` ever sets it. So the shipped checklist UI writes no RulingRecord, the same failure class as Conclave L0.3a. Rulings from a save that fails verification are also never emitted (the emit is inside `status == "saved"`). BLUEPRINT tracks the wiring as 6.25 ("not started", DELIVERY_LOG line 660). Smallest fix: always append to a local drop dir (`<out>/locutus/rulings.jsonl`) on every reviewed session, with partition left to the Bus when no registry is configured, rather than skipping when Locutus is absent.

**R4 100%-or-defer: Meets (adapted).** The high-stakes output here is "no identifier leaves." A leak on any route gives `failed_verification` with no output (`src/obsidian/text.py:15`, `:310`; `burnin.py:456-460`), and an unavailable verification route fails closed (`burnin.py:453-455`). No patient file enters any tool until the hash-pinned HARD GATE record exists (`src/obsidian/gate.py:1-10`, `GATE_RECORD_SHA256 = None`).

**R5 contracts owned by Atrium: Meets.** Five closed JSON Schema 2020-12 files with owner of record Atrium (`CONTRACTS.md`; `src/obsidian/contracts/*.v1.schema.json`), additive-only rule stated (`CONTRACTS.md`, "Changing a contract"), and the registry line is in `CONTRACTS_REGISTRY.md` here. Minor drift: the Locutus replica is pinned at Locutus `f706080` and lacks the additive `decision.k3.third` field now in Locutus `f0a5d42`; harmless while additive, but nothing at suite level checks replica freshness.

**R6 SEC-2: Meets.** The original is hashed, archived as 7-Zip AES-256 with a generated password, verified byte-for-byte, its password written to the KDBX vault and re-read, and only then is a Receipt minted (`src/obsidian/original.py:1-17`, `keep_original` line 61). Every engine requires the receipt and re-checks both hashes before writing, including `in_place` mode (`original.py:103-111`; `text.py:264,284-285`; `burnin.py:413-423`).

**P1 Reversibility: Meets** (in-place edit recoverable from the protected original; a copy that cannot be protected is deleted and the user told why, `ui/session.py:185-194`). **P2 Hash-verify: Meets** (`original.py:97-111`; `burnin.py:443`, source re-hashed before write). **P3 Plan/Apply: Meets** (the reviewed checklist is the plan; `save` refuses if the source changed since the checklist was made, `text.py:264-270`). **P4 No Silent Failures: Meets** (failed protection is audited and raised, `original.py:73,94`; BitLocker status reported, `platform_status.py`). Minor: a missing OCR route is reported as `internal_error` rather than naming the route (`burnin.py:453-455`). **P5 Atomic: Meets** (temp + `os.replace` in `text.py:317`, `burnin.py:476`, `vault.py:232,249`, `store.py:52`, `settings.py:124`).

---

## Not built

| Tool | State | Design pointer | Rules the design already addresses |
|---|---|---|---|
| Verity | Not built in the cloud repos; code on Jake's PC (`AL\Verity`) not read | `/mnt/project-files/full-audit-2026-10-23/VERITY_BLUEPRINT.md` | R3 (an adapter on the Conclave L0.3 pattern writing `<out>/locutus/rulings.jsonl`, line 18), R4 (unreviewed words reach the suite as defer, never as text, line 15), SEC-2 via Obsidian (line 22). Lesson from this audit: the build plan should require the adapter to be wired into the operator path in the same PR, not only built. |
| Affine | Not built | `APEX_SUITE_DESCRIPTION.md` "Affine" (line 27) | R4 in prose (a correction that moves a table cell or number is high-stakes). No R3 or R5 design yet. |
| APEX hub | Not built | `APEX_SUITE_DESCRIPTION.md` "APEX hub" (line 79); `BLUEPRINT.md` row 6.24 (Obsidian checklist UI in the hub; depends on E1) | Holds no authority and hosts no computation by design, so R2, R4 and the principles apply only to what it displays. R3 applies once it hosts any review screen. |

---

## Atrium-side gaps (this repo)

**Status in Atrium PR #2:** A1 fixed (all 14 Locutus and Obsidian contracts are pinned in `registry/contracts.v1.json`; Sequoia and the Conclave KB master are still to come). A2 and A3 fixed by README, CHARTER v0.2 and GLOSSARY v0.2. A4 fixed: `atrium_check` compares Conclave's vendored copies and Obsidian's RulingRecord replica with the registry. Its first run found the Obsidian replica stale (pinned at Locutus `f706080`, before the additive `decision.k3.third` field); an Obsidian re-pin PR follows.

- **A1. Registry incomplete.** `CONTRACTS_REGISTRY.md` lists only Obsidian. Locutus (6 contracts), Sequoia (2, in flight), and Conclave's KB master are missing.
- **A2. Principle lists disagree.** `README.md:13` names Reversibility and Plan/Apply as Principles 1 and 3; `CONSTITUTION.md` Article II names MORTAL SIN and Citation Chain instead. `CHARTER.md:50` says "Six Aims" while the Constitution has Ten. One source should own the list.
- **A3. Charter lacks the suite rules.** `CHARTER.md` states standalone-first but not replayable, every-input-generalizes, 100%-or-defer, Atrium contract ownership, or SEC-2. BLUEPRINT (line ~257) already says the Charter needs SEC-2 and §2a added.
- **A4. No suite-level replica check.** Obsidian pins a Locutus schema replica and Conclave pins a full Locutus copy, at different commits (`f706080` and `f0a5d42`), with no Atrium check that pins track the registry.

---

## Gaps ranked by risk (high-stakes accuracy first)

1. **Conclave R3, Review GUI and CLI write no RulingRecord** (`conclave_infra_workbench/.../pages/review/store.py:178`, `conclave_infra_reviewconsole/.../cli.py:353`; strict xfail at `test_chain_review_daemon.py:403`). High-stakes cutoffs, norm values and K3 dual reviews are ruled and then lost to learning, so the same high-stakes question will be asked again and the repeat-flag target (0) cannot be measured. Fix: wrap both Console constructions in `LocutusReviewConsole` and flip the xfail (L0.3a, widened to the CLI).
2. **Sequoia R3, attestation and corrections are one-off** (`sequoia/verify/golive.py:114,165`). Scoring-path findings from a human walk-through are not recorded as patterns, on the component whose errors are uncatchable downstream. Fix: emit RulingRecords with the `gate_id` locator for each walk-through finding.
3. **Obsidian R3, checklist UI never emits** (`src/obsidian/ui/session.py:113,195`). De-identification misses that a reviewer adds by hand are not learned, so the next document can leak the same identifier shape until a human catches it again. Fix: always write the local drop file; wire 6.25.
4. **Conclave P2, unverified non-atomic crop copy** (`conclave_integration_locutus_rulings/.../adapter.py:503-512`). Once item 1 is fixed this path goes live, and a truncated crop under a valid hash name would silently feed Locutus a wrong image for a high-stakes ruling. Fix: temp copy, re-hash, `os.replace`.
5. **Locutus R5, v1 tightenings and no registry entry** (`docs/CONTRACT_CHANGES.md:5,15`; `CONTRACTS_REGISTRY.md`). The RulingRecord is the contract every tool's human input flows through; unregistered, and with a precedent of breaking changes kept at v1, a future tightening can silently invalidate a tool's records. Fix: register, grandfather 10/23 explicitly, require v2 from now on.
6. **Conclave R5, KB master and Sequoia hand-off unregistered.** The highest-stakes data edge in the suite (KB to scoring forest) has no Atrium schema. Fix: export and register a KB master schema; Sequoia's ATRIUM-C covers the receiving side.
7. **Conclave R1, hard Locutus dependency in the voting engine** (`conclave_infra_votingengine/pyproject.toml:42`). Not an accuracy risk today, but it breaks "Locutus is never in a run's decision path" at install level. Fix: optional extra.
8. **Obsidian R2, sidecar cannot re-derive the output.** Fix: additive `checklist_sha256`.
9. **Conclave R6 / P3, unprotected KB in-place edit and immediate apply.** Needs an Atrium ruling on SEC-2 scope for derived artifacts before any code change.
10. **Conclave R2, model stages unreplayable on CPU.** Already handled by the GPU acceptance side build; listed for completeness.
