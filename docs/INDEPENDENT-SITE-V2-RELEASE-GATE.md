# CertPassly independent V2 release gate (experimental)

The **canonical** converter, schema, question-type registry and PHP importer contract are owned by [upstream CertPassly exam pipeline](https://github.com/msaqlainhaneef1/certpassly-exam-pipeline), version 1.3.0 reviewed at commit `d9b6bf67efb870019dd88caeffa90952b7e000d3`. This repository supplies an **independent fail-closed release gate**, not a replacement converter. The upstream schema and registry must be supplied from a reviewed, pinned commit, never copied by hand or silently updated.

## Private-runner command

```bash
python -m pip install 'jsonschema>=4.18,<5'
python scripts/verify_site_v2_release_gate.py \
  --exam /private/out/AB-900/AB-900.site-format.v2.json \
  --schema /pinned-upstream/reference/site-format/v2/question.schema.json \
  --registry /pinned-upstream/reference/site-format/v2/question_types.json \
  --evidence /private/evidence/AB-900-release-evidence.json \
  --report /private/evidence/AB-900-release-gate.json
```

The private evidence manifest contains `source_sha256` (64 lowercase hex), `source_question_count` (integer), and a `questions` object keyed by stable `question_key`. Each record requires independently established booleans: `source_verified`, `interaction_verified`, `answer_mapping_verified`, `visual_verified`, and `held`. Missing evidence **blocks** release. These booleans are assertions, **not proof**; supporting signed review logs, source-page coordinates and independent source-to-render comparisons must remain in the private repository.

Gate checks: schema validity, no raw HTML/scripts, learner answer leakage, canonical registry type and publishability, duplicate keys, source count completeness, status and scoring eligibility, held flags and independent evidence presence. Reports contain hashes and error codes only, never stems, options or answer keys.

**Limits:** No tool can guarantee 100% correctness. This gate cannot itself prove source fidelity, answer truth, encrypted database storage, live importer compatibility, keyboard/mobile behavior or practice/exam reveal security. Keep publication blocked until independent visual source review and real website staging/security tests pass. Do not relax thresholds to obtain a green report.

**Public repository safety:** Never commit private PDFs, questions, answer keys, screenshots, review evidence or generated exam packages here. All real exam artifacts stay private. The tests use synthetic toy records only.

**Proof:** CI tests and commit URLs are evidence of code checks, not of AB-900 publication readiness.
