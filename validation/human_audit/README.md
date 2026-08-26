# Sampled human validation v10.2e

This directory preserves the frozen double-blind validation boundary used by the paper.

- Population: 6,949 deduplicated, source-verified candidates.
- Common candidate sample: 365 claims (5.2526%), independently reviewed by Martin and Dominik.
- Separate dual-empty audit: 36 of 359 units reviewed by both authors.
- Design: deterministic SHA-256 selection without replacement, stratified by language and provider-origin type.
- Precision target: two-sided 95% interval with a worst-case finite-population-corrected half-width of 4.993 percentage points.

The two reviewer workbooks contain the same cases in the same blind order. Do not compare them or begin consensus until both completed files have been returned and hash-locked:

- `VALIDATION_SAMPLE_v10_2e_MARTIN.xlsx`
- `VALIDATION_SAMPLE_v10_2e_DOMINIK.xlsx`

`SAMPLED_VALIDATION_FREEZE_MANIFEST.json` records the sampling design and frozen hashes. `SAMPLED_VALIDATION_WORKBOOK_VERIFICATION.json` records workbook structure and pre-review hashes; the reviewer manifests record the externally distributed blind packages. The historical workbook-generation toolchain is intentionally omitted because it is not required to reproduce the released paper results.

The human review is pending. The current production findings therefore remain exploratory, and no validity or inter-reviewer agreement values are imputed.
