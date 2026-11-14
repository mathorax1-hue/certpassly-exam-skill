# Question format V2: isolated validation and merge blockers (2026-11-14)

## Scope and pinned provenance

- Source: msaqlainhaneef1/certpassly-exam-pipeline branch feat/question-format-v2.
- Pinned source commit: 462fd237ae7f0c607bb00229e173b22d0f3298d2.
- Source branch is *not* merged into its main; this skill branch does *not* modify skill main.
- This public repository uses a temporary external Git checkout at test time. Upstream has no confirmed redistribution license; do not vendor its source. No real exams, answer keys, original screenshots, or private logs are copied here.

## Review steps

1. Run upstream unit/regression tests and all existing shared-skill tests.
2. Compare 30 authoritative question types with v2 schema and reject fictitious types.
3. Verify all bundled valid examples pass and invalid examples are rejected.
4. Run adversarial learner answer-leak and HTML/SVG sanitization tests, including unquoted dangerous attributes and data URI misuse.
5. Confirm reviewer-only image variants stay out of learner media, particularly hotspot/active-screen migration.
6. Check draft-only migration policy, unresolved image conversion and answer-not-found scoring exclusion.
7. Explicitly record what is *not* testable here: real-PDF source fidelity, all 30 real interactive renderers, visual CSS fidelity/accessibility, site scoring, server-side reveal policy, and publication gates.

## Run

python -m unittest tests.test_upstream_v2_gate -v

git clone --no-checkout https://github.com/msaqlainhaneef1/certpassly-exam-pipeline.git /tmp/certpassly-v2-upstream

git -C /tmp/certpassly-v2-upstream checkout --detach 462fd237ae7f0c607bb00229e173b22d0f3298d2

python -m pip install -e /tmp/certpassly-v2-upstream "jsonschema>=4.22,<5"

python scripts/audit_upstream_question_v2.py --upstream /tmp/certpassly-v2-upstream --output v2-synthetic-audit.json

Expected behavior: exit 1 while any security/accuracy/coverage gate remains blocked. Exit 0 means only the synthetic contract tests passed; it does not establish production approval.

## Pre-existing design limitations and recommended remediation

The upstream docs explicitly keep V2 imports as *draft/unverified*, describe only a subset of the 30 types in runnable examples, and identify three website answer-key reveal bugs. Also the V2 branch is divergent from upstream main. The PHP site renderer and live importer are outside this source repository; independent acceptance is required.

### Potential image leak to test first

In upstream scripts/migrate_v1_to_v2.py the hotspot/active-screen path iterates reviewer reference_media and skips only filenames containing answer-review. Paths such as answer-area or answer_review may therefore be appended to learner.media despite a reviewer-only visibility flag. The synthetic audit is designed to confirm or falsify that hypothesis on the pinned source commit. Fix requires filtering all reviewer-only media by trusted role/visibility, not filename, and adding negative fixtures for all naming variants.

### Merge criteria

Do not merge this staging branch or promote an exam until all fail gates are fixed, all critical unverified gates have independent evidence, the upstream licensing question is resolved for any desired redistribution, and the web team has validated live V2 import, rendering, scoring and answer-reveal behavior. An engineering smoke check is not a human content approval.
