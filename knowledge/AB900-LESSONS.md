# AB-900: verified engineering lessons (sanitized)

**Purpose:** Prevent repeating development and release mistakes. No owner exam content or answer keys are stored here.

## Observed technical results (November 2026)

- The pinned private AB-900 workflow completed **15/15 technical stages**, **64/64 formal validation checks**, and **4,135/4,135 bank checks**. These are *technical* results, not evidence of answer truth.
- The last recorded private workflow status was `needs_human_or_evidence_review`, and no approved package was promoted to `ready-exams`.
- All **89** active packaged media assets were compared against the original PDF and found pixel-identical. Pixel identity does not verify the answer content.
- A prior release-audit visual mismatch counted screenshots belonging to superseded items. The fix requires mapping visual roles by **active** question IDs and separately tracking superseded screenshot owners.
- The independent release ledger identified **89 unverified answer accuracy flags**, **55 flagged human-review questions**, **42 active unverified answer-reference screenshots**, and **89 unapproved active media assets**. Counts refer to that last recorded gate and can change after evidence review.
- The package privacy audit checked 84 reviewer-only images and reported no reviewer-only media paths referenced by learner-facing schemas in the tested candidate. It did not test a live web importer.
- For 13 source slots, independently authored CertPassly Team replacement drafts were created. They are not proof that every replacement answer and distractor has been verified.

## Failure patterns -> permanent requirements

| Failure mode | Corrective engineering pattern | Gate |
|---|---|---|
| Technical checks pass but answer keys remain uncertain | Separate key accuracy and independent reviewer state from structural validation | Evidence gate |
| Source PDF highlights appear to provide answers | Treat highlighted answers as **claims**, verify all selections and distractors | Answer review |
| Visual count unexpectedly includes superseded items | Resolve screenshot roles against the active bank, record old media as superseded | Image role mapping |
| Screenshot matches its PDF pixels, but its meaning is unreviewed | Record image integrity independently from answer verification | Visual review |
| Reviewer answer screenshots accidentally shown to learners | Keep reviewer-only assets separate; inspect actual learner payload refs | Privacy gate |
| Repeated private workflow runs consume Actions minutes | Public synthetic tests, checkpoints, stage-level reruns, manual bounded private jobs | Actions budget |
| Every conversation generates new temporary scripts | Promote successful fixes into shared modules with regression tests | Skill repository |
| AI checks an official page but does not verify every option | Store vendor URL, page hash, quote, option-by-option rationale and uncertainty | Question evidence |
| AI says package is approved before independent reviewer approval | Protected private release environment with explicit approval | Release gate |
| Upstream dependencies drift without review | Full-commit pin and incompatibility test before upgrades | Supply chain |

## Links (no private source content)

- Release review tracking: https://github.com/mathorax1-hue/raw-exam/issues/2
- Processor public repository: https://github.com/mathorax1-hue/exam
- Original reference upstream: https://github.com/msaqlainhaneef1/certpassly-exam-pipeline

Never infer that all source answers are incorrect from an `unverified` count. Never transform a synthetic test into a production attestation.
