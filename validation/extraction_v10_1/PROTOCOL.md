# v10.1 shared extraction protocol

`v10.1` is the candidate protocol for the final paper extraction. It becomes reserve-frozen only after independent Model A and Model B runs on all 78 development pages satisfy the pre-existing gates or after the single permitted cause-mapped revision. The 40 reserve pages remain sealed.

Calibration outcome 2026-08-21: independent Codex and Claude runs plus their verified union are sealed and archived under `runs/2026-08-21_calibration/`. E1, E2, E3 and C1 failed; S1 passed. No reserve material was accessed. Before the single v10.2 revision, the 69 reference/union paragraph disagreements must be blindly re-adjudicated because the current human reference and v10.1 scope are not consistently aligned.

## Fixed semantics

Both models use the same `PROMPT_CORE.md`, `data/codebook.csv`, input units, output schema, span verifier, matcher, and deduplication rule. Provider task files contain only interface instructions. Neither model receives human labels, calibration error cases, prior model outputs, or the other model's responses.

The extraction unit is a deterministic source chunk with an immutable `unit_id`, `block_id`, document ID, page, source offsets, language, and source hash. Long pages are split without tail truncation and with deterministic overlap. Raw overlapping outputs are retained. Semantic keyword screening is prohibited because it would create an unmeasured recall loss.

Pages marked `ocr_needed` use the frozen render in addition to available text. Empty or unavailable source is reported explicitly; it is never converted into a semantic negative. Original-language quotes are verified against normalized text offsets or the frozen render. One source-only retry is allowed. Unsupported spans are rejected and counted.

## Evaluation order

1. Build and hash the blinded 78-page package.
2. Run OpenAI and Claude independently with the frozen provider settings.
3. Archive and hash both raw outputs before matching.
4. Verify spans, then compute A, B, and verified-union metrics against `calibration_reference_v10_1.csv`.
5. Choose the production rule before reserve access. A union contains only source-verified, in-scope statements; duplicates are resolved deterministically after raw recall is measured.
6. Complete and sign blocking checklist rows. Build the reserve package only then.
7. On the reserve, seal both model outputs and the blinded human reference before one-time unblinding. Do not tune on the reserve.

## Cost control without semantic loss

Use asynchronous provider batch processing and structured outputs. Pack up to six small source units into one request while preserving identifiers; cap requests by source tokens, not page count alone. Put the shared prompt and compact codebook before variable source text. Return compact JSON only, use `quote_en=null` for English, generate statement IDs locally, and retry only failed units. Do not run a cheaper semantic screener or summarize source text before extraction.

Current dated prices are inputs to `pricing.json`, not methodological constants. Recheck them in the provider console on the run date and archive actual usage and charges. A cheaper model may replace the listed model only if it first passes the full 78-page calibration under the same gates.
