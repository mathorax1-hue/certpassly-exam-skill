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

**Rule:** the private repository must not keep a separately evolving copy of this generic code (see the private tool-promotion policy); only narrowly justified private adapters may remain. A green public CI run or a promoted tool does not verify answer truth, approve answers, or authorize publication.

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
