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
- Phase 2 source-region OCR: four held questions each had candidate regions but zero strict two-pass regions on the original PDF. All root causes were input-side: sub-30-pixel crops degraded the second OCR pass below the unchanged 90/95 floors while the first pass read the same words clearly; unboxed text rows were never localized once any UI control existed; a 24-region budget truncated later panels' text bands; and full-width bands mixed toolbar icons with clean labels. Generic region preparation (growing small crops, retaining the already-computed localization, reordering the bounded budget, and splitting bands at wide ink gaps) produced strict regions for all four questions with both passes, thresholds and agreement rules unchanged. Strict regions remain source evidence only, never release approval.
- Phase 2 source-coverage verification: a per-question verifier built over the converter's own records plus OCR-line crop batteries established, for all 89 questions, that every reference word is either verified (text layer, canonical strict region, or a strict two-pass reading of the word's OCR line box at a documented input preparation) or carries a recorded, exhausted attempt battery. Full-image OCR line boxes fail both unchanged passes whenever a dropdown border, dense navigation icon, or sparse arrow glyph sits inside the box; border trimming and narrow-glyph skipping recover those lines without touching any gate. Remaining uncovered words are genuinely marginal at the unchanged quality bar (degraded tiny text where the two passes produce different misreads); they stay documented deficiencies, never verified coverage, and never release approval.

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
| Tiny UI crops fail the second OCR pass while the first reads clearly | Grow small region crops before the unchanged pass scaling; hash the native crop and record the input transform separately | Source OCR |
| Unboxed text rows keep UI chrome once any control exists | Keep the localization already computed for collision checks as its own region candidate | Source OCR |
| Bounded crop budget starves later panels' text bands | Read all control text bands before whole control crops; drop low-contrast bands duplicating original panels | Source OCR |
| Full-width bands mix toolbar icons and clean labels in one crop | Split bands at wide ink gaps into word-cluster candidates; each still faces both gates | Source OCR |
| OCR line boxes include dropdown borders and UI icons, so both unchanged passes fail clear text | Trim near-full-height border columns and skip narrow leading glyphs before re-reading; record every attempt | Source coverage |
| Coverage summary quietly mixes verified words with candidate-only OCR | Classify every reference word as verified (named class) or evidenced deficiency with its attempt battery; candidates never count | Source coverage |

## Links (no private source content)

- Release review tracking: https://github.com/mathorax1-hue/raw-exam/issues/2
- Processor public repository: https://github.com/mathorax1-hue/exam
- Original reference upstream: https://github.com/msaqlainhaneef1/certpassly-exam-pipeline

Never infer that all source answers are incorrect from an `unverified` count. Never transform a synthetic test into a production attestation.
