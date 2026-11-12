# End-to-end operations: shared skill -> private proof-backed exam draft

This guide covers engineering, private exam review, evidence auditing and safe handoff. Read [AGENTS.md](../AGENTS.md), [SKILL.md](../SKILL.md), the [session recovery guide](AI-SESSION-RECOVERY.md), the [tool hub](TOOL-HUB.md) and [engineering history](../knowledge/ENGINEERING-HISTORY.md) before working.

## Repository roles (hard boundaries)

1. **PUBLIC skill hub**: mathorax1-hue/certpassly-exam-skill — shared scripts, checked tooling, dependencies, CI, sanitized lessons and onboarding.
2. **PUBLIC processor**: mathorax1-hue/exam — existing source-independent processing adapters, release-evidence generator and synthetic regression tests.
3. **PRIVATE source and editorial evidence**: mathorax1-hue/raw-exam — immutable owner PDF, questions, answer-reference screenshots, authoring JSON, official source snapshots, private review ledger, research archive and private AI handover.
4. **PRIVATE destination**: mathorax1-hue/ready-exams — independently verified release packages and proofs only, never raw research. Website publishing is a distinct controlled action.

An existing GitHub Actions workflow may check out a different legacy pipeline at an immutable revision. That is an **actual runtime fact**, not permission to push to the old repo, replace a protected gate, or assume our latest new skill scripts are already deployed. See the live raw-exam .github/workflows/process-exams.yml and config/repositories.json before proposing changes.

## Reusable skill engineering pass

- Find an existing implementation in tool-registry.json or the public processor. Prefer extending it to inventing a duplicate.
- Reproduce bug or capability with entirely synthetic inputs. Do not run real owner exams in public CI.
- Add one reusable script/module, one synthetic test covering failure and success, and a registry entry. Record dependencies and threat model.
- Run the full public skill tests, registry validation, public safety, and verify CI on the exact commit. Do not confuse a green test step with a successful git push.
- Record failure/lesson in knowledge/ENGINEERING-HISTORY.md and update session handover pointers. Avoid personal or private source data.
- Make private workflow pin adjustments separately, only after compatibility and a reviewed rollout plan. A source change in this repo does not automatically change pinned runtime.

## AB-900 before AI-103: private editorial/release sequence

1. **Recover actual state.** Read raw-exam/docs/AI-SESSION-HANDOVER.md, exams/AB-900/evidence/active-question-review-ledger.json, visual role reconciliation evidence, original PDF location, authoring drafts and latest processing report. Confirm the present commit, artifact SHA and date.
2. **No false counts.** An AI-supported check is not an approved answer. Report exact question IDs when completed, with evidence links. Keep a genuinely pending reviewer flag until an authorized human review event happens.
3. **Inspect original.** Read exact question wording, all answer choices and marked owner key, and for visual items view original question and answer screenshots. Maintain original option/row order. Obscured answers remain unknown. Do not change owner PDF.
4. **Verify against current official documentation.** Search current Microsoft official documentation. Use the official-page capture helper in approved private storage for the exact downloaded bytes, final URL, short verbatim quote, SHA-256 and UTC time. If inaccessible, preserve the blocker. Source presence alone is not answer truth.
5. **Crosscheck every option.** Complete per-option explanations and source references, not just a primary claim. Use the option evidence preflight; preserve uncertainty if the current docs do not settle a distractor, answer, or historical term. Keep replacement CertPassly Team originals separate from immutable owner questions. Thirteen earlier AI claim crosschecks do not imply full key approval.
6. **Reconcile media.** Review active question IDs and original screenshot ownership. Distinguish question prompts vs answer-reference images and superseded refs. Reviewer-only answer imagery must never enter learner-facing materials. Run role metadata audit and separate actual PDF/pixel/meaning review. Never equate a matching hash or matching pixels with a correct key.
7. **Validate only a complete eligible batch.** Use existing private authoring stages and independent gates for writing, bank structure, official-source audit, visual safety, importer format, package scanning, validation and final release proof. Save exact logs and hashes. Avoid repeated incomplete private Actions runs.
8. **Independent approval and promotion.** Require accountable authorized reviewer signoff when policy requires it; never forge/AI-self-approve. If a gate fails, leave in raw-exam with exact blockers. If all private gates pass, promote only the approved evidence-backed draft to ready-exams; do not publish on a website automatically.
9. **After action.** Update the existing private JSON ledger (do not fragment into many conflicting master files), private handover, and GitHub issue, with question IDs, proof URLs, run/commit IDs, test outcome and remaining gate blockers.

## What to execute when something fails

| Symptom | Safe first response |
| --- | --- |
| No source PDF or multiple possible PDFs | Stop, reconcile manifest, rights, checksum and selected source; never guess |
| Official site blocks download | Record URL, retrieval failure and unverified status; do not invent quote or SHA |
| AI source check conflicts with marked key | Preserve original, record conflict, inspect every option and dated docs; no silent overwrite |
| Matrix/dropdown answer seems hidden | Inspect original question+answer screenshots; leave pending if obscured |
| Visual count unexpectedly high | Reconcile active vs superseded owner IDs before drawing conclusions |
| Bank check passes but answer unverified | Keep accuracy and reviewer flags; technical passes alone are insufficient |
| Release verifier fails | Inspect exact proof, stage and evidence errors; do not weaken or disable gate |
| Public Actions fails to write a workflow | Check workflow-writing account scopes; don't claim the source commit succeeded |
| Library or GitHub save returns a UI error | Read back destination and commit/version; pending is not completed |
| Private Actions consumption high | Use synthetic public tests and staged private artifacts; select one exam when needed |
| Skill changed but pipeline still runs old code | Confirm pinned checkout revision; reviewed pin update is separate |
| New AI chat cannot remember progress | Read this hub plus the private AI handover, not inferred past chat claims |

## Evidence statuses

Use precise terms:

- **Source extracted**: text/media recovered from the owner file.
- **AI crosschecked**: independent reasoning draft cites official material, may still be incomplete or conflicting.
- **Option evidence documented**: each choice has written rationale and a source record; not semantically validated by scripts.
- **Full answer independently reviewed**: a qualified authorized reviewer actually inspected source, options and images.
- **Protected draft release accepted**: private verifier confirmed all required proofs; destination has commit and package.
- **Website published**: separate site import and acceptance happened. Never infer this from GitHub.

The skill is a reusable tool and documentation home. Reading it does not retrain the AI, assign review authority, unlock external accounts, or start an ongoing background job.

## New session minimum handover

State: exact repository and working branch, relevant commits/CI links, known exam code, source item count, AI crosschecked vs independent-approved counts, screenshot role counts and superseded refs, evidence snapshot dates, files updated, failed attempts, outstanding conflicts, and authorized next action. Source private details must stay in raw-exam rather than this public guide.
