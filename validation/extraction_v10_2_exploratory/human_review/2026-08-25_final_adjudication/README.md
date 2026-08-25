# Final human adjudication v10.2e

Frozen production review set created on 2026-08-25 under `PROTOCOL_AMENDMENT.md`.

## Design

- 6,949 deduplicated union candidates.
- 1,390 candidates (20.0029%) independently assigned to both reviewers.
- Remaining candidates assigned once by deterministic, stratified alternation.
- Martin: 4,171 candidate rows.
- Dominik: 4,168 candidate rows.
- 36/359 dual-empty units (10.0%) independently reviewed by both authors.
- Model identity, provider code, candidate origin, allocation, and overlap membership are absent from reviewer workbooks.

`candidate_machine_mapping.csv` contains the embargoed provider and allocation mapping. Do not open it until both reviewers have returned their completed workbooks.

## Reviewer workflow

Each reviewer receives only the matching XLSX and required renders. Enter initials in `Instructions!B3`, complete `Candidate Review` and `Dual Empty Audit`, and use `Empty Supplements` when `missed_claims=yes`. `QC Summary` must contain no pending, incomplete, or needs-context rows at handoff.

## Reproduction

1. Run `scripts/prepare_production_adjudication_v10_2e.py` against the frozen OpenAI and Claude canonical outputs and the frozen production package.
2. Run `scripts/build_final_adjudication_workbooks_v10_2e.mjs` with the generated data directory, output directory, and preview directory. This formatter uses `@oai/artifact-tool`.
3. Run `scripts/verify_final_adjudication_workbooks_v10_2e.mjs` against the workbook output directory.
4. Run `scripts/package_final_adjudication_v10_2e.py` to create separate blind reviewer archives with only referenced renders.

Exact inputs, rules, counts, and hashes are recorded in `HUMAN_REVIEW_FREEZE_MANIFEST.json`; exported workbook checks are in `FINAL_ADJUDICATION_WORKBOOK_VERIFICATION.json`.
