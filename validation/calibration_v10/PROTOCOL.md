# v10 extraction calibration protocol

Status 2026-08-21: Phase 1 is complete (41 FN, 20 FP and 5 span cases adjudicated). The corrected development reference is `calibration_reference_v10_1.csv`; it versions 17 scope exclusions and one false-negative correction while preserving the original human workbook. Independent v10.1 runs are archived in `validation/extraction_v10_1/runs/2026-08-21_calibration/`. The protocol did not pass E1, E2, E3 or C1; S1 passed. The reserve remains sealed.

The verified union reached probability precision 0.662 and recall 0.592 (document-cluster bootstrap 95% recall CI 0.392–0.746), stress-long recall 0.650 and exact-code recall 0.240. Inspection of the disagreement directions showed a material conflict between the existing reference and the frozen v10.1 scope: several apparent false negatives are explicit exclusions under v10.1, while several apparent false positives are eligible own-project decisions or pilot findings. The next permitted development action is therefore blind human scope re-adjudication of all 69 reference/union disagreements, not prompt tuning to the current labels. The workbook intentionally hides model identity, model text and disagreement direction.

## Scope

The 78 unsealed pages are development data. They may be inspected and reused for prompt and parser calibration. The 40 `reserve_sealed` pages remain unopened until the revised protocol is frozen.

Current diagnostic baseline on probability pages: TP 51, FP 20, FN 41, TN 173; recall 0.554 (document-cluster bootstrap 95% CI 0.390–0.703), precision 0.718. Strict span fidelity is 0.792; five spans remain unsupported by the extracted source layer.

Known prerequisite: `JP_BoJ_Pilot_JP` is Japanese, but the frozen metadata labels it `zh` and records `chi_sim` as the OCR language. Two unresolved span cases are from this page. Correct the prospective metadata to `ja` and obtain Japanese-capable review/translation, or retain an explicit language exclusion. Do not rewrite the archived v9 pilot.

## Units

- Recall unit: gold paragraph. `ANO` and `ANO-částečně` are positive. A paragraph is recovered when at least one eligible model span matches it on the same page at the frozen 0.80 rule.
- Precision unit: gold paragraph for gate E3. Statement-level conservative precision is reported separately.
- Span unit: one model statement checked against the frozen source text. A translation is never accepted as the original-language quote.
- Exclusions: `skip_language` and `structural_blank` are not semantic negatives and do not enter recall or precision denominators.

## Phase 1 — human error audit

1. Open `CALIBRATION_AUDIT_v10.xlsx` and read `Instructions` and `Taxonomy`.
2. Review all 41 rows in `FN audit`. Confirm whether the gold label is valid. If valid, mark the smallest verbatim span that should have been extracted and assign one primary cause.
3. Review all 20 rows in `FP audit`. Judge the model output, not only the paragraph label. Assign one primary cause. Use `FP_GOLD_FALSE_NEGATIVE` when the model is right and the reference label should change.
4. Review the five rows in `Span audit` against the original PDF/render. Record whether the quote is exact, normalization-only, OCR-equivalent, a paraphrase, on the wrong page, or unsupported. Supply a corrected verbatim quote when available.
5. Use secondary causes only when they imply a different corrective action. Do not infer a cause from the gold label alone.
6. Set `status=adjudicated`, add initials, and return the filled workbook. The machine-readable `error_cases.csv` is then updated from the workbook and frozen with SHA-256.

The error audit is human adjudication. An LLM may summarize completed categories but must not decide whether its own output or the human reference is correct.

## Phase 2 — protocol revision on calibration pages

1. Summarize counts by confirmed error cause. Separate extractor errors, reference-standard corrections, matcher errors, and source-layer failures.
2. Map every material cause to a specific change in `change_log.csv`. Record expected benefit and failure risk before testing.
3. Apply two semantic stages within one structured request to avoid a second API pass:
   - high-recall screening of paragraph/layout blocks for own-project design-relevant claims;
   - classification of retained exact spans using the current 35-code v10 codebook.
4. Prefer conclusions, decisions and explicit proposals over topic headings, literature, foreign projects and lists without a substantive assertion.
5. Remove silent `<250`-character loss. Use the frozen OCR/render text where the PDF layer is insufficient; otherwise emit an explicit unresolved-source status.
6. Chunk long pages without truncating the tail. Preserve block identifiers and deterministic overlap. Deduplicate only after raw recall is measured.
7. Require verbatim original-language quotes. Run the offset-mapped span verifier. Retry failed spans once using only the source block; unresolved spans are rejected or flagged, never silently repaired.
8. Run Model A and Model B independently on the 78 calibration pages. Neither model receives gold labels, prior outputs or the other model’s response.
9. Archive raw A and B outputs before matching. Report A, B and the pre-specified verified union `A∪B`. The primary production rule must be chosen and recorded before reserve evaluation.
10. Iterate only on these 78 pages. Stop when no planned change remains and calibration performance is compatible with E1, E2, E3 and S1. Calibration success is not confirmatory evidence.

## Phase 3 — freeze

1. Freeze and hash prompt, 35-code codebook, preprocessing/OCR, chunker, output schema, span verifier, matcher threshold, deduplication, model identifiers/configuration, A/B union rule and stopping rule.
2. Freeze the human coding instructions and decide HUMAN-002: either independent second-human audit or an explicit single-coder reference-standard limitation.
3. Complete `freeze_checklist.csv`. No reserve file is opened before all blocking rows are signed.
4. Prefer API runs for the reserve because exact model IDs and parameters can be archived. Codex runs remain usable only with the already stated limitation that backend identifier and temperature may be unavailable.

## Phase 4 — one-time reserve evaluation

1. Prepare identical blind input packages for the 40 sealed pages. Verify source hashes.
2. Run Model A and Model B independently. Seal and hash both raw outputs before comparison.
3. Human-code reserve pages without seeing model outputs. Freeze and hash the reference labels before unsealing model results.
4. Unseal once. Compute paragraph precision/recall/F1, document-cluster bootstrap intervals, subgroup results, workload, strict span fidelity, A/B overlap and verified-union metrics.
5. Apply the frozen gates without changing thresholds after seeing reserve results.
6. If the primary rule passes, run the frozen protocol on the full corpus. If it fails, do not tune on the reserve and call it held-out again. Either report the extraction as exploratory, or revise on development data and draw a new untouched validation sample from the remaining held-out pool.

## Role of the second LLM

For the present multi-model claim, the revised protocol must be run with both Model A and Model B on calibration and reserve pages. A second LLM is not a substitute for a second human coder and does not adjudicate gold. If the paper drops the multi-model robustness claim, one pre-specified production model is sufficient for the primary gate, but the design and Methods section must be changed before opening the reserve.
