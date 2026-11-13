# CertPassly engineering history: failures, fixes, passes and open gaps

This is a **sanitized historical lessons ledger** for future AI sessions. No owner questions, answer options, exam screenshots, private source text, credentials, human identities or unverified answer corrections belong here. Consult private raw-exam handover and live workflow evidence for exact current status.

## 2026-11-11: stage progress mistaken for answer truth

**Observed:** The AB-900 pipeline processed 89 source slots, passed 15 of 15 technical stages, 64 formal validation checks and 4,135 bank checks. Independent release still blocked 89 unverified accuracy statuses and 55 human-review flags. The owner material includes visual item types requiring separate review.

**Root cause:** Structural correctness and generated content conformance do not establish factual correctness. An owner-highlighted key is a claim, not an independent reference.

**Permanent rule:** Track at least five distinct states: extracted, AI source-supported, all choices crosschecked, independent review approved, ready-exams release accepted. Never merge counts. Source URLs, quote and raw-byte SHA-256 are provenance fields; independent subject review remains separate.

**Prevention:** Central skill evidence and option auditors; independent protected release verifier. **Open:** current answer verification, reviewer sign-off and final gates.

Reference: https://github.com/mathorax1-hue/raw-exam/actions/runs/43071568426 (private, authorized access required).

## 2026-11-12: screenshots were double-counted across bank revisions

**Observed:** Active packaged media comprised 89 pixel-verified original screenshot references, previously grouped as 47 question and 42 answer references. Another 20 original image refs belonged to superseded owner items. Initial counts incorrectly mixed active and superseded items. Pixel matching alone did not establish what selected answers meant.

**Root cause:** Role reconciliation was not scoped to the active question ID set.

**Permanent rule:** Each screenshot needs immutable asset identity, owner question ID, role, active/superseded state, hash, learner visibility and image-answer review status. Report superseded count separately and block any reviewer-only leak. Preserve original matrix/dropdown row and option order.

**Fix staged and tested:** scripts/reconcile_visual_roles.py with tests/test_reconcile_visual_roles.py; image role metadata only, **not** a pixel or semantic accuracy engine.

**Open:** check full original PDF image/answer contents in the private repo; no AI review impersonation.

## 2026-11-12: source checks lacked complete archived proof

**Observed:** Private ledger once recorded 47 AI-supported crosschecks out of 89 but 0 independent release approvals. A subsequent private preflight reported 34 URL-bearing records without a saved source-hash field, outstanding source-key disputes, incomplete original PDF reinspection and missing human review.

**Root cause:** A link or an AI justification is not itself a downloadable, hash-verified source snapshot, a complete option-by-option rationale or an accountable approval.

**Prevention tools:** scripts/capture_official_source.py (HTTPS allowlist, max-size, SHA-256, exact quote-in-visible-page check, distinguishing downloaded vs offline origin); scripts/verify_saved_receipts.py (offline rehash and quote check from saved bytes, no fabricated origin); scripts/audit_option_evidence.py (all original options, rationale, source fields, rows); scripts/audit_question_evidence.py (private ledger preflight). All operate fail-closed and **do not** approve an answer.

**Open:** download real official pages privately, check every option, original images, conflicts and evidence; re-run independent release only after full eligible batch.

Private proof: https://github.com/mathorax1-hue/raw-exam/actions/runs/43184329405

## 2026-11-12: historical artifacts were hard to inspect when only zipped

**Observed:** A previous Actions result was available as nested artifact archives, difficult to browse and verify in GitHub.

**Fix:** A generic safe ZIP-to-directory extractor with path checks, nested expansion, collision checks and per-file SHA-256 manifest. Private [run 43184063276](https://github.com/mathorax1-hue/raw-exam/actions/runs/43184063276) populated a browsable recovery archive of 278 source workflow files, including 89 images and 132 JSON files.

**Rule:** Archive generated private evidence in organized directories and checked manifests, not only opaque ZIPs. Keep source originals unchanged. A hash proves byte identity, not correctness or independent approval.

**Reuse:** scripts/unpack_artifact_tree.py and tests/test_unpack_artifact_tree.py. This tool is generic and does not contain private files.

## 2026-11-12: GitHub App workflow permission failure

**Observed:** Public skill bootstrap [run 43087739001](https://github.com/mathorax1-hue/certpassly-exam-skill/actions/runs/43087739001) passed 27 synthetic tests, but Git rejected updating a workflow file from a token without workflow-writing rights.

**Fix:** Separate author-controlled workflow-file changes from routine content changes. Keep read-only public CI and push ordinary source through properly authorized actions. [Run 43088200619](https://github.com/mathorax1-hue/certpassly-exam-skill/actions/runs/43088200619) subsequently passed.

**Rule:** A green test suite does not mean the repository push succeeded; verify commit SHA, remote branch head and CI conclusion. See knowledge/GITHUB-ACTIONS-LESSONS.md.

## 2026-11-11 to 2026-11-12: private Actions runtime costs

**Observed:** Automatic multi-exam processing could fan out across dozens of eligible owner sources, consuming private runner credits before evidence was reviewed. Other sources were blocked for missing official mapping or source research.

**Fix:** Manual target exam selection, default one exam per run, public synthetic QA, bounded private job timeouts and retention, and reuse of valid stage artifacts. No repeated expensive test runs just to change a partial AI review draft.

**Rule:** Never weaken a gate, run a large batch or fabricate missing vendor blueprint weights to reduce CI time. Prefer targeted tests and explicit blockers.

## 2026-11-12: original upstream lacked available write access

**Observed:** The existing external pipeline was checked out by Actions, but the connected account could not push to that other owner's repo. Cross-repository checkout is not edit permission.

**Resolution:** Use mathorax1-hue/certpassly-exam-skill as the canonical, writable shared knowledge and tooling home. The older pipeline remains a pinned external compatibility dependency for existing established stages, until a legally permitted and tested replacement exists. Its root did not show a LICENSE at the last review; avoid unpermitted vendoring.

**Proven passes:** New generic preflight/archive helpers were validated by public processor CI [43183489036](https://github.com/mathorax1-hue/exam/actions/runs/43183489036), then integrated into this central skill with its own synthetic CI. No real private release gates were relaxed.

## 2026-11-12: Library master update was not confirmed

**Observed:** A proposed in-place update to a conversation archive encountered an approval UI error (Not found / Please try later). Local preparation did not prove persistent Library overwrite.

**Rule:** Treat a draft file, prepared payload or rejected UI request as uncommitted. For durable handovers, keep sanitized general guidance in this public skill and private per-exam evidence, status and research links under the private raw-exam handover. Never claim a file or version was saved until reading it back successfully.

## 2026-11-12: public media privacy checks passed but were narrow

**Observed:** A candidate package had no reported reviewer-only answer references in the checked learner-facing schema paths. This did not constitute live site rendering/import acceptance or validate answer meaning.

**Rule:** Continue using reviewer-only/learner roles and explicit source references. Re-run the private proof checker for the release package and separate website import acceptance from build and bank checks.

## 2026-11-13: Phase 1 extraction toolkit promoted from private pilot to public skill

**Observed:** The proven Phase 1 PDF-extraction engine (source audit, xref media mapping, structured/v1 builder, fail-closed exports, validation, reconciliation, visual QA, 27-scenario adversarial suite) lived only in a private repository review branch, forcing every future worker to duplicate generic code privately.

**Fix:** Promoted all 15 generic files into the public `certpassly.phase1` package with a `phase1` extra (PyMuPDF/Pillow/numpy/jsonschema pinned ranges), 10 registry entries, `certpassly phase1-info`/`phase1-audit`/`phase1-extract` CLI commands, checkpoint/resume orchestration, a fully synthetic public test suite (config, exports determinism, answer-privacy fail-closed, orchestrator resume logic, CLI surface, no-network import scan), and complete install/cache/doctor/troubleshooting/rollback documentation. The pinned external upstream remains a read-only external dependency (never vendored; its root has no confirmed redistributable LICENSE).

**Bug found and fixed during promotion:** the read-only audit detected encryption but then attempted page-level analysis, which raises on unauthenticated encrypted documents. The public port now fails closed immediately with a BLOCKED report and no fabricated counts; the historical private toolkit crashed unhandled in that path. Regression: the synthetic encrypted-PDF test.

**Bug found and fixed during the first real batch run:** the reconciliation answer-accounting check demanded that every question carry a typed key or an answer image, so a source question that genuinely has NO answer (recorded fail-closed as answer.source_kind=missing with an answer_missing_in_source unresolved item) failed reconciliation. The check now accounts for the measured missing set (check name gains a `_N_missing_` segment only when missing>0, keeping previously accepted reconciliations byte-identical), and the split-preservation check also accepts stem-only records. Regression: synthetic fixture question with a missing answer (tests/test_phase1_reconcile.py::test_missing_answer_source_kind_accounted).

**Byte-compatibility rule:** provenance label defaults keep the historical private-toolkit strings so a config from a previously accepted extraction reproduces its outputs byte-identically; new runs declare the public module and pinned commit via the optional config `provenance` block. Verified by replaying accepted pilot extractions with their original configs.

**Incident during the first five-exam batch (version sensitivity):** PyMuPDF 1.28.2 (inside the original >=1.24,<2 range) produced a different text reading order on a /Rotate 90 multi-question page than the validated 1.26.7 line, assigning two spans of a later question to the previous question's segment. The builder's per-question page-set cross-check against the pinned extractor caught it and BLOCKED the whole run with an explicit assertion — the fail-closed design worked; no corrupt layer was emitted. Fix: pin the phase1 extra to the validated minor line (>=1.26,<1.27), document the reason in pyproject and DEPENDENCIES.md, and require a full adversarial + pilot replay before ever widening.

**Schema fix from the same batch:** owner exam codes may contain underscores (e.g. FCP_FGT_AD-7.6); the structured/v1 template's exam_code pattern now allows them. Previously accepted extractions (codes without underscores) remain valid under the widened pattern; only the emitted extraction-schema.json pattern string differs on replay.

## 2026-11-13: director audit P0 corrections to the promoted Phase 1 toolkit

**Observed (director independent content/code audit):** (P0-A) image-based questions carrying a typed letter were classified `single_choice` from the letter alone - on VCE-style sources the letter is a template literal (observed `A` on all 34 combined-key items of one pilot), not widget evidence; q002/q004/q006 of that pilot are actually dropdown / 3-row Yes-No matrices. (P0-B) the type-count check only compared values already stored in config, so an unknown/low-confidence type could pass as a release-ready gate. (P0-C) `audit_source` reported `AUDIT_COMPLETE`/exit 0 for identity-ambiguous, zero/duplicate-marker or unextractable-image sources; `run_all` never invoked the audit; the standalone validator silently skipped PDF readback when the PDF was missing. (P0-D) `export-blockers.json` counted rows with NO blocking reasons (34/89 on one pilot, 56/114 on another), making the blocked counter misleading.

**Fix:** typed letters on image questions are now recorded as `answer.typed_key_status = source_literal_only_key_status_unknown` and are never used for typing; the type comes from visual evidence or stays `unknown`/low confidence. The audit gained hard BLOCK criteria (encrypted, identity-ambiguous, zero/duplicate/noncontiguous markers, unextractable images -> exit 2) and is stage 0 of `run_all`; the validator fails `pdf_present_for_readback` when the configured PDF is missing and adds a cross-gate that recomputes rows-with-reasons from the blocker items and requires every unknown-type / low-confidence / unverified-typed-key question to be explicitly blocked. Exports add the typed-key gate and a standalone independent-review reason so every row carries at least one real reason, with honest `blocked_questions_with_reasons` counters.

**Tests:** 4 new adversarial scenarios (typed A + dropdown, typed A + 3-row Yes/No, legitimate text-only single choice control, typed placeholder + ambiguous image fail-closed; 31/31 total) plus unit tests for the audit BLOCK criteria (no markers / duplicates / gap / mixed geometry), the validator cross-gate, missing-PDF fail-closed and honest counters. Full public suite 142/142.

**Rule:** structural count checks prove structure, never interaction semantics; a typed letter is source evidence, not a validated key; counters must be recomputed from data, never trusted from stale fields. Classification corrections to already-extracted layers are intentional divergences to be documented per record, not silent data changes.

**Rule:** the private repository must not keep a separately evolving copy of this generic code (see the private tool-promotion policy); only narrowly justified private adapters may remain. A green public CI run or a promoted tool does not verify answer truth, approve answers, or authorize publication.

## 2026-11-13: director audit-2 corrections (P0-1 / P0-2 / P0-3 / P1-4 / P1-5)

**Observed (director second independent audit):** (P0-1) `visual_qa` ended with `return 0 if not low_vis else 0` - ALWAYS exit zero, so machine visibility failures could never stop `run_all`. (P0-2) `reconcile` contained two hardcoded-True checks (`pinned_stage_log_line_reproduced`, `visual_draft_reproduced`) that counted as passed without comparing any actual pinned-stage evidence; published check totals included these synthetic-true tests. (P0-3) the standalone validator skipped the PDF readback when the source PDF was absent. (P1-4) `audit_source` recorded `identity_ambiguous` without blocking. (P1-5) a question record treated a team EDITORIAL replacement draft (explicitly marked `original_certpassly_team_editorial_not_owner_pdf` in the prior manual transcription file) as one of its PDF answer-transcription candidates - crossed provenance.

**Fix:** `visual_qa` now exits 2 on MACHINE VISIBILITY FAILURE (any not-visible/unreadable/degenerate image placement, or an image-bearing page that renders blank) and 0 otherwise; clipped-at-edge, text-sparse and content-free blank pages stay recorded warnings; pending human semantic review is reported as `human_review_pending` and deliberately never changes the exit code. The two reconcile checks became GENUINE recomputation checks - `reconcile_notes.stage_log_claims` / `visual_draft_claims` are re-derived from the pinned upstream output files (split.json, cleanups.json, unparsed.json, layout.json, visual_draft.json) and must match exactly - while prose-only legacy configs emit informational notes OUTSIDE the passed-check denominator (`informational_notes` in reconciliation.json; check totals honestly shrink by two on such configs). Editorial drafts are routed to a separate `answer.editorial_overlay_candidates` field with explicit provenance and an export blocker reason, never into `selection_candidates_unapproved`; the validator gained `editorial_overlay_never_a_transcription_candidate` (crossed-provenance regression) and `editorial_overlay_provenance_explicit_and_unapproved`; the schema template documents the new field. P0-3/P1-4 were already covered by the earlier P0-C correction (missing-PDF fails `pdf_present_for_readback`; identity/marker/unextractable-image conditions BLOCK the audit with exit 2) and gained an explicit validator-side SHA/bytes tamper test.

**Tests:** 3 new adversarial scenarios (34/34 total): visual_qa clean exit 0 vs tampered-asset exit 2; editorial overlay separation with honest validator 0 and hand-corrupted crossed-provenance 1; stage-log/visual-draft claims honest 0 vs tampered 1 with both claim checks flipping to failed. 8 new unit tests (150 total): claims genuine pass, altered stage log fails, altered visual draft fails, prose notes outside denominator, PDF SHA/bytes tamper fails closed, crossed provenance fails, provenance marker required, well-formed overlay passes.

**Rule:** a check that cannot fail is not a check - hardcoded-True results and always-zero exits must never sit in a passed-check denominator; editorial (non-source) content must remain in an explicitly provenance-marked overlay and can never be presented as source transcription evidence.

## 2026-11-13: director final correction - --resume/--start-from could bypass the source checks

**Observed (director review of the correction package):** the stage orchestrator's `--resume` matched only the config file PATH, and `--start-from` simply began at the named stage - so after any completed run, a changed or deleted source PDF, an edited config, a swapped upstream pin or a hand-edited/stale checkpoint could skip the stage-0 source audit (and every other passed stage) without the SHA-256, identity or integrity checks ever re-running. Nothing enforced that the checkpoint still described the current source.

**Fix:** every checkpoint now embeds a `source_fingerprint` (actual PDF SHA-256 + bytes, config content SHA-256, pinned upstream scripts tree hash, engine label, measured at run START) and the stage-0 audit summary (verdict, source sha, identity flag) read back from source-audit.json. A fail-closed SOURCE GUARD runs before any stage may be skipped: the PDF must exist right now and hash to the config-pinned `expected_pdf_sha256`/`expected_bytes`; the config must pin the source; the prior checkpoint must belong to this config, carry the SAME fingerprint and a valid AUDIT_COMPLETE / non-identity-ambiguous audit summary of that exact source; the on-disk source-audit.json (when present) must not describe a different source; and `--start-from` additionally requires every earlier planned stage to have exited 0 in that verified checkpoint. Refusal = exit 3 with NO stage run and the checkpoint left untouched; `--resume` with a missing/foreign checkpoint degrades to a FULL run from stage 0 (audit re-runs, nothing skipped). `--dry-run` also evaluates and reports the guard verdict so a would-be bypass is visible without side effects.

**Tests:** 1 new adversarial scenario (35/35 total) running the REAL pipeline end-to-end: full pass then positive controls (resume no-op 0, start-from single stage 0) and negative fixtures - changed PDF (resume 3 / start-from 3), missing PDF (resume 3 / start-from 3), stale checkpoint (resume 3). 15 new unit tests (165 total): changed/missing PDF refusals, unpinned-config refusal, stale checkpoint (tampered pdf hash, edited config, swapped upstream tree, pre-fingerprint checkpoint), invalid/conflicting audit summaries, start-from without verified checkpoint, start-from past unmet prerequisites, positive start-from control, checkpoint fingerprint/audit recording, dry-run guard refusal. The public synthetic fixture now creates a real (deterministic) source PDF whose hash is pinned consistently across config/manifest/provenance.

**Rule:** a checkpoint is a receipt, not a permission slip - skipping a verification stage is only ever valid while the receipt still provably describes the exact source, config, pinned code and engine it was issued for; when in doubt, re-run from stage 0.

## 2026-11-14: director final correction 2 - --resume could no-op over deleted or modified outputs

**Observed (director review of the verified correction package):** the hardened source guard fingerprinted the INPUTS (PDF, config, pinned upstream scripts, engine label) but never verified the GENERATED OUTPUTS of already-passed stages. When a verified checkpoint said all stages exited 0, `--resume` set all-done and returned success WITHOUT OPENING ANY OUTPUT FILE - so after a fully checkpointed run, deleting a question record, corrupting an asset binary or removing a validation/reconciliation report still produced a green no-op. The engine component of the fingerprint was also a fixed label, so silently updating the toolkit code under an unchanged version label carried the same stale-output risk.

**Fix:** every completed stage now persists, in the checkpoint, a deterministic output inventory (exact generated file paths + per-file SHA-256 of what the stage actually wrote - question JSON, asset binaries, exports, manifests, validation/reconciliation/visibility reports) alongside an input baseline (SHA-256 of every monitored pipeline input: pinned upstream split output, pmap, build-stats sidecar, audit record), both bound to the source fingerprint recorded in the same checkpoint; the engine component became a CONTENT HASH of the installed certpassly package tree (`toolkit_tree_sha256` + declared `toolkit_version`, with `toolkit_root` recorded but intentionally not compared - identical content at a relocated path must not refuse). Before `--resume` may no-op or any stage may be skipped, an OUTPUT-INVENTORY GUARD re-hashes the input baseline and every skipped stage's recorded outputs (accumulated in plan order, since later stages legitimately rewrite earlier files) and compares: a deleted/edited question JSON, swapped asset binary, removed report or tampered input refuses with exit 3 naming the file and the writing stage, running nothing and leaving the checkpoint untouched. A checkpoint that predates inventories cannot authorize skipping: `--resume` degrades to an explicit FULL rebuild from stage 0 (loud notice, nothing skipped), `--start-from` refuses exit 3. `--dry-run` reports both guards' verdicts.

**Tests:** 1 new adversarial scenario (36/36 total) running the REAL pipeline end-to-end over a synthetic exam with a real extracted image asset: full pass; verified no-op resume and single-stage start-from; deleted question JSON (resume 3 / start-from 3), edited question JSON (3), swapped asset binary (3), deleted validation report (3), changed toolkit code with unchanged version label (3, probe restored byte-exactly), inventory-less old checkpoint (explicit full rebuild, all stages re-run); final verified no-op again. 12 new unit tests via a contract-accurate output-writing stage fake (200 total): inventory/baseline recording with exact SHAs, toolkit fingerprint as content hash, deleted/edited question refusals, swapped asset refusal, deleted validation/reconciliation report refusals, skipped-output start-from refusal, later-stage-output precision control, tampered-input refusal, real toolkit-drift refusal + clean resume after restore, inventory-less checkpoint full rebuild + start-from refusal, dry-run refusal visibility, verified no-op message.

**Rule:** a receipt for inputs is not a receipt for outputs - skipping is only valid while every artifact the skipped stages produced (and every input they read) still hashes to what the checkpoint recorded, and while the engine that produced them still hashes to the fingerprint; green without re-verification is the bug, not the feature.

## Sustainable incident-record format

Every future incident or test finding should record:

- Timestamp, operation, exam code if relevant (no private content in public).
- Exact commit SHA and workflow run link; whether observed or inferred.
- Expected versus actual results; privacy exposure and severity.
- Confirmed root cause; workaround versus permanent fix.
- New reusable script/test file and failure reproduction using synthetic data.
- Dependency changes and scope.
- Rerun CI conclusion with exact commit.
- What remains blocked and who has authority to approve.

**Source of truth:** This historical ledger is supplementary. The public scripts and private evidence always outrank any conversation summary.
