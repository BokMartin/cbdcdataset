# v10.2 protocol-exact calibration result

## Decision

Calibration is complete. The OpenAI run, Claude run, and their source-verified union fail the frozen E1 and E2 recall gates. None is eligible for the reserve or full-corpus production run. The 40-page reserve remains sealed. The v10.2 protocol permits no further tuning on these development pages or on the reserve.

This result supports an exploratory or explicitly human-reviewed workflow. It does not support a claim of validated automated extraction, automated classification, or gate-qualified LLM-assisted candidate retrieval.

## Runs and source verification

- OpenAI main Batch API run: `gpt-5.6-terra`, medium reasoning, 13/13 requests completed, 78/78 units parsed, no provider or schema failures.
- Six unsupported quotations in five units triggered the one permitted source-only retry. The retry completed 5/5 with no provider or schema failures.
- Final OpenAI output: 116 accepted statements; all 116 are exact source substrings after 92 deterministic whitespace restorations. One statement remained unsupported after retry and was rejected. No render review remains open.
- Claude final output: 141 accepted statements; all 141 are source-supported.
- Raw OpenAI main and retry outputs were separately archived and hashed before parsing or comparison. Their hashes are in `RUN_MANIFEST.json`.

## Frozen-gate results

| Output | Probability precision | Probability recall | Recall 95% document-cluster CI | Stress-long recall | Workload / positive reference | Span fidelity | Exact-code recall |
|---|---:|---:|---:|---:|---:|---:|---:|
| OpenAI | 1.0000 | 0.6250 | 0.5222–0.7308 | 0.5882 | 1.4146 | 1.0000 | 0.1935 |
| Claude | 0.9767 | 0.6563 | 0.5319–0.7593 | 0.5882 | 1.7195 | 1.0000 | 0.2258 |
| Verified union | 0.9800 | 0.7656 | 0.6327–0.8814 | 0.7059 | 1.9024 | 1.0000 | 0.2903 |

For all three outputs: E1 fail, E2 fail, E3 pass, S1 pass, C1 fail. The strongest retrieval rule is the union, but it still misses 15 of 64 probability-sample positive paragraphs and 5 of 17 stress-long positives. Its point recall is 0.7656 against the required 0.90, and its lower 95% bound is 0.6327 against the required 0.85.

Cross-model overlap is 101 one-to-one matches among 141 Claude statements (0.7163). Exact-code agreement among matched spans is 0.4554. Binary paragraph agreement is Krippendorff's alpha 0.6795 and Gwet AC1 0.8553.

## Reproduction

From the repository root:

```powershell
python scripts/evaluate_extraction_v10_1.py `
  --package <EXTRACTION_v10_2_CALIBRATION_CLAUDE_FINAL> `
  --model-a validation/extraction_v10_2/runs/2026-08-25_protocol_exact/openai/openai_extractions_v10_2_source_canonical.jsonl `
  --model-b validation/extraction_v10_2/runs/2026-08-25_protocol_exact/claude/claude_extractions_v10_2_source_canonical.jsonl `
  --model-a-run-status protocol_exact `
  --model-b-run-status protocol_exact `
  --reference validation/extraction_v10_2/reference/calibration_reference_v10_2.csv `
  --out-dir <empty-output-directory> `
  --threshold 0.80
```

The final evaluation was rerun into a clean directory. `calibration_results.json`, `statement_assignments.csv`, and `paragraph_audit.csv` reproduced byte-exactly.

## Cost

OpenAI main plus retry usage was 245,925 input tokens, including 143,864 cached tokens, and 34,283 output tokens. The estimated Batch API cost is USD 0.32. The provider billing record is authoritative.

## Paper consequence

Do not open the reserve and do not start the full automated extraction under v10.2. For the current deadline, the defensible path is to report this calibrated failure transparently and base substantive article results on a documented human-reviewed extraction. A new automated-validation attempt would require a newly versioned protocol, a new untouched development sample, and a new reserve; it cannot be obtained by further tuning on these 78 pages.
