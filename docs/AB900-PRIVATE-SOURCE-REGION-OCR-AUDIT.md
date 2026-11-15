# Private PDF source-region OCR triage

The authoritative PDF converter, V2 schema and fidelity rules live in [CertPassly upstream](https://github.com/msaqlainhaneef1/certpassly-exam-pipeline) at reviewed commit `d9b6bf67efb870019dd88caeffa90952b7e000d3`. This skill does **not** duplicate that converter or bypass the source/answer fidelity gate.

## Use on a private runner only

The source PDF and `out/<CODE>/export/cannot-convert.json` are private inputs. Do not put source text, page images, answer marks or the full evidence output in this public repository.

```bash
python -m pip install 'pymupdf>=1.24,<2' 'opencv-python-headless>=4.8,<5' 'numpy>=1.24,<3'
# For optional two-mode region OCR, also install Tesseract.
python scripts/audit_held_pdf_source_regions.py \
  --pdf /private/exams/AB-900/source/AB-900.pdf \
  --held /private/out/AB-900/export/cannot-convert.json \
  --pdf-sha256 <verified-original-pdf-sha256> \
  --output /private/evidence/held-source-regions.json \
  --ocr --max-ocr 500
```

The tool hashes the **actual input file bytes** and rejects a PDF that differs from the supplied source SHA-256. It walks PDF text spans and embedded image blocks in page order, assigns *candidate* source images to question IDs, detects enclosed controls and repeated radio-button columns, crops regions only in temporary memory, and uses Tesseract PSM 3 and PSM 6 to compare non-empty word-token sequences. **The output records only image/crop hashes, geometry, OCR agreement and word counts; it does not record the OCR text or answers.**

A candidate image association or OCR agreement is not proof of original question meaning, complete source coverage, option mapping, answer correctness or simulator fidelity. Unmapped or ambiguous cases remain held. Never promote or publish on these diagnostics alone.

## Real AB-900 evidence — November 15, 2026

- The original PDF has SHA-256 `e0e989699408066d157b41929d2b2bbaec6386e596a9645adacb0b48f3bc6001`.
- The upstream pipeline counted **89 source questions**, exported **36 V2 drafts**, and held **53**. Source fidelity and answer eligibility are still incomplete.
- The corrected private region audit found **89 PDF question markers**, **53 held records**, candidate image associations for **52 held questions**, with **q043 unresolved by layout-order association**.
- The audit extracted **115 candidate OCR regions** (33 matrix-statement columns and 72 enclosed controls); **56/115** had matching nonempty OCR token sequences across two Tesseract modes. **59/115** still disagreed. None of those region counts represent verified questions.
- The first agreement run was invalid due to a tokenizer escaping error that treated OCR outputs as empty. The corrected tokenizer includes regression tests for **nonempty** matching tokens and empty outputs (which must not count as agreement).
- All 53 questions **remain held**. The original upstream converter and real website have **not** been patched to use these regions as verified content, and no item has been released.

**Reproducible verification and provenance:**

- [Corrected private OCR run](https://github.com/mathorax1-hue/raw-exam/actions/runs/43707843856)
- [Private 53-question evidence JSON](https://github.com/mathorax1-hue/raw-exam/blob/chatgpt/ab900-technical-import-pilot-20261114/exams/AB-900/evidence/verified-ocr/AB900-53-held-source-region-OCR.json)
- [Permanent private evidence provenance](https://github.com/mathorax1-hue/raw-exam/blob/chatgpt/ab900-technical-import-pilot-20261114/exams/AB-900/evidence/verified-ocr/PROVENANCE.json)
- [Private evidence persistence run](https://github.com/mathorax1-hue/raw-exam/actions/runs/43708029306)
- [Source-specific ROI example verification](https://github.com/mathorax1-hue/raw-exam/actions/runs/43706511386)

## Required next release conditions

1. Every question must have complete source text and faithful layout/interaction mapping, with independently established evidence.
2. Each answer key must have verified evidence and correct scoring; uncertainty must continue to block affected questions.
3. Canonical upstream V2 and actual website import/security/accessibility tests must pass.
4. No held/unapproved questions may be silently promoted, and packaging/answer-leak checks remain strict.
5. Maintain separate verified source and acceptance manifests in the private repository. A green diagnostic test is not publication approval.
