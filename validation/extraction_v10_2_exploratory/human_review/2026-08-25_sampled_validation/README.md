# Sampled human validation v10.2e

Current human-review design under `PROTOCOL_AMENDMENT_2_SAMPLED_VALIDATION.md`.

## Frozen design

- Candidate frame: 6,949 deduplicated, source-verified claims.
- Common sample: 365 claims (5.2526%), independently reviewed by Martin and Dominik.
- Design precision: 95% confidence, worst-case finite-population-corrected half-width 4.993 percentage points.
- Selection: deterministic SHA-256 rank without replacement, stratified by language and provider-origin type.
- Separate dual-empty audit: 36/359 units reviewed by both authors.
- Human workload: 401 review items per author, plus supplement rows only when a dual-empty miss is found.

Both workbooks contain the same cases in the same blind order. Do not compare workbooks or begin consensus until both completed XLSX files have been returned and hash-locked. The plaintext machine mapping is sealed outside the repository until that point; its pre-review SHA-256 is frozen in the manifest. It contains provider provenance, strata, inclusion probabilities, and survey weights required for analysis.

The archived full-census workbooks in `../2026-08-25_final_adjudication/` are deprecated and must not be used.

## Reviewer files

- `VALIDATION_SAMPLE_v10_2e_MARTIN.xlsx`
- `VALIDATION_SAMPLE_v10_2e_DOMINIK.xlsx`

Separate ZIP packages with the matching workbook and four required page renders are generated outside the repository by `scripts/package_sampled_validation_v10_2e.py`. Their external manifests are stored here.

## Reproduction

1. Regenerate the full blinded payloads and machine mapping with `scripts/prepare_production_adjudication_v10_2e.py` from the frozen production package and the committed OpenAI and Claude canonical outputs.
2. Run `scripts/prepare_sampled_validation_v10_2e.py` against that mapping and the two blind payloads.
3. Build both workbooks with `scripts/build_final_adjudication_workbooks_v10_2e.mjs`; it automatically detects `SAMPLED_VALIDATION_FREEZE_MANIFEST.json`.
4. Run `scripts/verify_final_adjudication_workbooks_v10_2e.mjs`. `SAMPLED_VALIDATION_WORKBOOK_VERIFICATION.json` must pass.
5. Run `scripts/package_sampled_validation_v10_2e.py` with the frozen production package to create one blind archive per reviewer.

The freeze manifest records all selection parameters and hashes. After both reviews are locked, the mapping is unsealed, hash-checked, and added to the repository; population estimates then use its `survey_weight`. This sample estimates candidate validity and coding agreement, not full-production recall; the latter remains the separately frozen calibration result.
