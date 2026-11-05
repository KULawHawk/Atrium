# APEX contracts registry

**Owner of record: Atrium.** Every contract that crosses an APEX tool boundary is listed here. The member repo named in "Home" carries the schema file; Atrium owns the name, the version and the rules for changing it.

The machine-readable registry is [`registry/contracts.v1.json`](registry/contracts.v1.json). It pins the sha256 of every contract file, the tool roster, the expected tool enums and the vendored mirrors. `python -m atrium_check check` compares it with the member checkouts (see [Checking the registry](#checking-the-registry)). A test fails if this table and the JSON name different contracts.

## Contracts

| Contract | Home | File | Notes |
|---|---|---|---|
| `RulingRecord/1` | Locutus | `src/locutus/contracts/ruling_record.v1.schema.json` | One per human decision, any tool (STRATEGY §2a). **Registry revision 1.1**: the 2026-10-23 L0.2 tightenings were breaking (see Revisions). |
| `RulingRetraction/1` | Locutus | `src/locutus/contracts/ruling_retraction.v1.schema.json` | Withdraws one earlier RulingRecord (blueprint 4.6). |
| `PatternPack/1` | Locutus | `src/locutus/contracts/pattern_pack.v1.schema.json` | Signed, hash-pinned patterns shipped back to the tools. |
| `PartitionManifest/1` | Locutus | `src/locutus/contracts/partition_manifest.v1.schema.json` | Sealed datum lists per partition (the data firewall). |
| `QueryRequest/1` | Locutus | `src/locutus/contracts/query_request.v1.schema.json` | A tool asking Locutus for patterns. |
| `ForgeRequest/1` | Locutus | `src/locutus/contracts/forge.v1.schema.json` | Shares one file with ForgeOutput/1. |
| `ForgeOutput/1` | Locutus | `src/locutus/contracts/forge.v1.schema.json` | Every item is partition SYNTHETIC. |
| `ShapeCheckScope/1` | Locutus | `src/locutus/contracts/shape_check_scope.v1.schema.json` | Scope of a PatternPack artefact of kind `shape_check`; no `contract` field of its own. |
| `PhrasingRuling/1` | Locutus | `src/locutus/contracts/phrasing_ruling.v1.schema.json` | W-8 lexicon ruling. Suite contract name since Locutus #25; `ruling_id` is fixed-width with `maxLength`, `lex_id` and `merged_into` open with a `^(?!.*\n)` guard. |
| `TagProposal/1` | Locutus | `src/locutus/contracts/tag_proposal.v1.schema.json` | W-7 manual-tag proposal. The dotted name `conclave.tag_proposal.v1` is deliberate (registered with `const_value`): under W-7 design §3.5 the record is owned by Conclave and emitted by the Workbench, and any move to the suite form is a W-7 decision. Every pattern is newline-bounded since Locutus #26. |
| `TagRuling/1` | Locutus | `src/locutus/contracts/tag_ruling.v1.schema.json` | W-7 manual-tag ruling. The dotted name `conclave.tag_ruling.v1` is deliberate (registered with `const_value`): under W-7 design §3.5 the record is owned by Conclave and emitted by the Workbench, and any move to the suite form is a W-7 decision. Every pattern is newline-bounded since Locutus #26. |
| `EngineFamilies/1` | Locutus | `src/locutus/contracts/engine_families.v1.json` | Data contract from the Conclave roster (CL-3 method_family). |
| `ObsidianRequest/1` | Obsidian | `src/obsidian/contracts/obsidian_request.v1.schema.json` | De-identification request (6.19). |
| `ObsidianResult/1` | Obsidian | `src/obsidian/contracts/obsidian_result.v1.schema.json` | |
| `ObsidianSidecar/1` | Obsidian | `src/obsidian/contracts/obsidian_sidecar.v1.schema.json` | Holds no path, name or value. |
| `VaultEntry/1` | Obsidian | `src/obsidian/contracts/vault_entry.v1.schema.json` | Lives only inside the KDBX 4 vault. |
| `ShareRecord/1` | Obsidian | `src/obsidian/contracts/share_record.v1.schema.json` | The SEC-8 share log; vault only. |
| `KBInput/1` | Sequoia | `sequoia/integration/contracts/kb_input.v1.schema.json` | Inbound edge. No `contract` field (identifying field `kb_input_version`); deliberately open, four rules only the validator checks (Sequoia `CONTRACTS.md`). |
| `ApexAuditRecord/1` | Sequoia | `sequoia/integration/contracts/apex_audit_record.v1.schema.json` | Outbound edge to APEX Layers 5/6. No `contract` field (identifying field `audit_schema_version`). |

Original registry line for Obsidian (6.19, Atrium #1), kept for the record: Obsidian (APEX de-identification module): ObsidianRequest/1, ObsidianResult/1, ObsidianSidecar/1, VaultEntry/1, ShareRecord/1 — owner Atrium; files in KULawHawk/Obsidian src/obsidian/contracts/ (6.19).

**Not yet registered:** Conclave's KB master file (the producer side of `KBInput/1`) has no schema file yet. Conclave's `conclave_contracts` package holds Conclave-internal models, not cross-tool contracts.

## Tool roster and tool enums

The roster is `conclave, sequoia, verity, affine, apex_hub, obsidian, locutus`. Four enums must equal it exactly: RulingRecord `tool`, RulingRetraction `tool`, and the Obsidian `$defs/tool` used by ObsidianRequest and VaultEntry. Three are declared subsets, each with its reason in the JSON:

- PatternPack `consumer` leaves out `locutus` (Locutus produces packs).
- QueryRequest `target_tool` leaves out `apex_hub` and `locutus`.
- ForgeRequest `requester` leaves out `obsidian`. **Open question:** Obsidian's leak tests could use Forge material; if so, add it in Locutus and here in the same change.

Any other value, or any drift from these sets, fails the check.

## Vendored mirrors

Conclave vendors Locutus (`conclave_vendor_locutus/`) and part of Obsidian (`conclave_vendor_obsidian/`). The check compares every vendored contract file with the registered bytes. A difference is a warning (re-vendor), and an error under `--strict`. A mirror pinned at an older commit whose contract files are all identical is a note only.

## Single-file replicas

A member that must not import another member at run time may keep a pinned copy of one contract file for its tests. Obsidian keeps `tests/fixtures/locutus/ruling_record.v1.schema.json` (pin in `tests/fixtures/locutus/PIN.json`). The check compares each replica with the registered bytes; a difference is a warning (`REPLICA_STALE`), an error under `--strict`.

## Pattern lengths

Python's `jsonschema` applies `pattern` with `re.search`, where `$` also matches just before a final newline, so `"<64 hex>\n"` passes `^[0-9a-f]{64}$`. The check reports `PATTERN_UNBOUNDED` (a warning; an error under `--strict`) for every pattern with a `$` anchor that still accepts a trailing newline. A pattern is closed in one of two ways:

- **Fixed width:** `maxLength` at most the pattern's minimum match width (for example 64 on `^[0-9a-f]{64}$`). The extra newline always overflows.
- **Variable width:** a guard after every `$`, such as `^[a-z_]+$(?!\n)`, or a leading `^(?!.*\n)` that refuses a newline anywhere (Locutus #25's form). The leading guard counts only when the pattern has no top-level `|`: in `^(?!.*\n)a$|b$` it covers the first branch only, so such a pattern falls through to the per-anchor and width checks. A `maxLength` alone does not close a variable-width pattern: 128 on `^[a-z_]+\.[a-z_]+$` still lets `"ab.cd\n"` through. In ECMA-262, where `$` only matches at the very end, the guard never changes the result.

The check finds anchors anywhere in the pattern (inside alternations too), and skips escaped `\$` and `$` inside `[...]`. It measures width with the stdlib regex parser. A pattern it cannot parse is reported, never passed.

## Checkout commits

`python -m atrium_check check` reads each member checkout's `git HEAD`. A checkout not at its `pinned_commit` is an error (`HEAD_NOT_PINNED`), so a run cannot quietly check the wrong commit. `--allow-unpinned-head` turns it into a warning for a deliberate run against a feature branch. A folder that is not a git checkout is also an error (`HEAD_UNKNOWN`): its commit cannot be shown. `--allow-unpinned-head` lowers both to warnings. Library callers that pass no `heads` get a `HEAD_NOT_CHECKED` note.

## Revisions

A contract entry may carry `revision` (`M.N`, where M is the contract's version) and a required `revision_note`. It records a change that broke the v1 rules but was kept under the same file and `const`, so nothing on disk is renamed. The check reports it as a `CONTRACT_REVISION` note on every run, so the exception stays visible.

- `RulingRecord/1` is at **1.1** (decision 35 (ii) = A, 2026-11-03). On 2026-10-23, Locutus L0.2 made `issue_signature`, `bbox_space` and `pack_sha256` required and turned `engine_family` into an enum, under the v1 label (`docs/CONTRACT_CHANGES.md` in Locutus). No record was on file yet, so the change is grandfathered. **The next tightening must be a v2 file.**

## Changing a contract

1. A v1 change is additive only, logged with a date in the home repo's change log (`docs/CONTRACT_CHANGES.md` in Locutus, `CONTRACTS.md` in Obsidian).
2. A breaking change is a new version with its own file (`*.v2.schema.json`) and its own row here.
3. The same change updates the pin: `python -m atrium_check repin --repos-root <folder>` prints the plan, `--apply` writes it (Constitution Principle 3, plan then apply).
4. A new contract file that is not in the registry fails the check (`UNREGISTERED_FILE`).

## Checking the registry

Standard library only, Python 3.11+. From the Atrium folder, with the member repos side by side in one folder:

```
python -m pip install -e ".[test]"
python -m atrium_check check --repos-root ..
```

On Jake's PC the folder is `C:\Users\jmlee\Desktop\AL` (the registry's `dir` names match case-insensitively). One member can be pointed elsewhere with `--repo locutus=C:\path\to\Locutus`. A member with no checkout is an error, never a silent skip; `--only <member>` narrows the run on purpose and the summary line lists what was `NOT_EXAMINED`. The last line is always `ATRIUM-CHECK: PASS` or `ATRIUM-CHECK: FAIL` with counts. Exit code 0 pass, 1 fail, 2 unusable input.

Tests: `python -m pytest --cov` (100% line and branch). Set `ATRIUM_REPOS_ROOT` to the folder above to also run the live check of the committed registry; without it that one test is skipped and says so.
