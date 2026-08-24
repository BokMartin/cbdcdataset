# Independent audit request: v10.2 calibration freeze and evaluation

## Purpose

Independently audit the recorded files, code, and reproducible outputs described below. This is a technical and methodological review; it does not request hidden reasoning, private chain-of-thought, or a new extraction. Report observable evidence, test results, discrepancies, and proposed corrections.

The immediate question is whether the v10.2 reference freeze, evaluation correction, and prepared OpenAI Batch input are safe to use for the final protocol-exact cross-model calibration. Do not edit any file unless separately asked.

## Materials

Required:

- GitHub repository `BokMartin/cbdc-msed-v10`, branch `main`.
- Baseline implementation commit `dafe37a` (`Freeze v10.2 reference and batch evaluation tooling`) or a later commit containing it.
- Claude run-2 archive `files (2).zip` if provider-output and preliminary-metric reproduction is requested.
- The frozen 78-unit v10.2 package used for both providers. Its `inputs.jsonl` SHA-256 is `4764ae7a0b3d0c6c07a03adecffc1c2df1b61f7495c744175185a257724d8467`.

Do not request or inspect the sealed 40-page reserve. Do not use any API key found in a message or file. The OpenAI Batch has not yet been submitted.

## Recorded procedure

### 1. Scope decisions were frozen

The author accepted all 25 remaining checks in the completed blind readjudication workbook. Cells `Final checks!H9:H33` were set to `accept`; the summary then contained 25 accepted and 0 open checks. The workbook was saved as:

`validation/extraction_v10_2/reference/SCOPE_READJUDICATION_v10_2_FROZEN.xlsx`

Recorded workbook SHA-256:

`557a4bf0d8d13f923df4d64b59565937a2e3c2348a0f36d34584882f6a455f70`

The workbook was rendered sheet by sheet and visually inspected. All six sheets rendered, and the formula-error scan found no `#REF!`, `#DIV/0!`, `#VALUE!`, `#NAME?`, or `#N/A` cells.

The 69 final scope decisions were exported to:

`validation/extraction_v10_2/reference/author_decisions_v10_2.json`

Expected properties:

- 69 unique `review_case_id` values;
- 24 `keep` and 45 `exclude` decisions;
- no unresolved decision;
- every kept decision has a non-empty final code;
- JSON SHA-256 `e3f51a491ef94e3a1588be24cb7628cf3ce96fd1db24c430e640ac77c20f1bb2`.

### 2. The v10.2 human reference was generated

The portable decisions were applied to the previously frozen v10.1 reference with:

```text
python scripts/freeze_reference_v10_2.py \
  --base-reference validation/calibration_v10/calibration_reference_v10_1.csv \
  --decisions validation/extraction_v10_2/reference/author_decisions_v10_2.json \
  --output-dir <empty-audit-directory>
```

The generated files were compared with the committed reference and change log. Compare parsed CSV content or normalize line endings when checking across operating systems; raw CSV hashes can differ after a Git CRLF/LF checkout.

Expected semantic result:

- 351 reference rows on 78 pages;
- all strata: 82 positive, 209 negative, 60 excluded;
- probability stratum: 64 positive, 186 negative, 40 excluded;
- transitions: 23 negative-to-excluded, 8 negative-to-positive, 22 positive-to-excluded, and 16 positive-to-positive;
- reserve status remains `sealed`.

Authoritative summary:

`validation/extraction_v10_2/reference/calibration_reference_v10_2.json`

Expected logical hashes recorded by the generator:

- base v10.1 reference: `3e9b318b8de25ccfc682c07db263c668d111fc63ad22e52e34bc8c5db86fbadc`;
- generated v10.2 reference CSV: `a6dcd733b2d3175b34a20785f9ce19e9928bd70d5fc4005d24285421be90e1a9`;
- generated change log: `d5d2c723f86f78a3b1188697c6d26c983cc035430aedd38eb12157ba875e5f83`.

Audit whether every one of the 69 decisions changes exactly one `(gold_id, paragraph_id)` row and whether excluded rows have both an empty reference code and an empty reference span.

### 3. A legacy matching defect was corrected

The earlier evaluator allowed one statement to match more than one reference paragraph and allowed one Model A statement to deduplicate more than one Model B statement. The diagnostic contradiction was 66 reported cross-model matches from only 23 Model A statements.

`scripts/evaluate_extraction_v10_1.py` now uses deterministic maximum-cardinality, maximum-score, one-to-one bipartite assignment implemented as integer-cost min-cost flow. The semantic overlap threshold remains 0.80. Neither provider output, the codebook, nor the frozen reference was changed as part of this correction.

Audit record:

`validation/extraction_v10_2/matching_erratum_v10_2.json`

Please inspect and test these properties directly:

1. No left or right node can appear in more than one returned pair.
2. Maximum cardinality takes precedence over total similarity score.
3. Among maximum-cardinality solutions, total score is maximized.
4. Ties are deterministic across repeated runs and input ordering.
5. A graph requiring an augmenting path still reaches maximum cardinality.
6. One Model A statement and two identical Model B statements produce one match and a deduplicated union workload of two, not one.
7. Reference assignment applies the same one-to-one restriction.
8. The 0.80 threshold and all substantive inclusion rules are unchanged.

Also audit the document-cluster bootstrap implementation, observed-statistic reporting, Gwet AC1, Krippendorff alpha, classification denominator, and gate comparisons. These functions supply paper-facing validation numbers.

### 4. Claude run 2 was technically validated before reference comparison

The supplied provider archive contains 13 successful main requests and a permitted source-only retry for two units. Final coverage is 78/78 units, with 141 accepted statements and 47 empty units.

The raw provider archive was preserved. A source-only canonical derivative was created before comparison with the reference:

- 100 whitespace-normalized quotations that mapped uniquely to source text were restored to the exact source substring;
- 23 non-empty text units incorrectly labelled `structural_blank` were relabelled `ok`, without adding statements;
- one repeated table quotation was source-supported but had ambiguous offsets; no interpretive text or code was changed;
- all 141 final statements were source-supported after canonicalization.

Expected canonical JSONL SHA-256:

`c06ce8c71d0eefbbdd19b5f0c6ac6dcf2c89908b25647fecf3ec3f7ede5bee5a`

Audit the provider archive and transform log if they are supplied. Confirm that canonicalization is mechanical, source-only, fully logged, and does not add, remove, paraphrase, or recode a statement. Flag the ambiguous repeated table span separately; do not silently choose an offset.

### 5. Preliminary Claude-only results were recomputed with corrected matching

These are development-calibration results, not confirmatory paper results:

- probability paragraphs: TP 42, FP 1, FN 22, TN 185;
- precision `0.9767441860`;
- recall `0.65625`;
- F1 `0.7850467290`;
- document-cluster bootstrap recall 95% interval `[0.5319148936, 0.7592995169]` with 2,000 finite draws;
- stress-long recall `10/17 = 0.5882352941`;
- raw workload `141/82 = 1.7195121951` statements per positive reference paragraph;
- source-span fidelity `141/141 = 1.0`;
- exact-code classification recall `7/31 = 0.2258064516`;
- gates: E1 fail, E2 fail, E3 pass, S1 pass, C1 fail.

The old non-protocol Codex chat extraction is diagnostic only and cannot serve as final Model A evidence. Consequently, any preliminary union metric that includes it is also not paper-eligible. The final Model A, Model B, and verified-union comparison must wait for a protocol-exact OpenAI API Batch run.

Recorded impact of the one-to-one correction:

- Claude recall unchanged at `0.65625`;
- preliminary union recall unchanged at `0.6875`;
- union deduplicated workload corrected from 98 to 141;
- workload ratio corrected from `1.1951219512` to `1.7195121951`;
- E3 still passes.

Please reproduce the metrics when the v10.2 package, canonical Claude JSONL, diagnostic Codex JSONL, and frozen reference are available:

```text
python scripts/evaluate_extraction_v10_1.py \
  --package <v10.2-package-directory> \
  --model-a <diagnostic-codex-responses.jsonl> \
  --model-b <claude-source-canonical.jsonl> \
  --model-a-run-status diagnostic_not_protocol_exact \
  --model-b-run-status protocol_exact \
  --reference validation/extraction_v10_2/reference/calibration_reference_v10_2.csv \
  --out-dir <empty-audit-directory> \
  --threshold 0.80
```

### 6. The final OpenAI Batch input was prepared offline

`scripts/openai_batch_v10_2.py` implements `prepare`, `submit`, `status`, and `collect`. Preparation used the same frozen 78-unit package and the committed v10.2 prompt, codebook overrides, authority overrides, and unmodified output schema.

Frozen configuration:

- model `gpt-5.6-terra`;
- endpoint `/v1/responses`;
- Batch processing;
- reasoning effort `medium`;
- temperature omitted;
- structured output with the unmodified schema;
- 13 requests, 78 units, and 9 base64 render pages.

Offline preparation command:

```text
python scripts/openai_batch_v10_2.py prepare \
  --package <v10.2-package-directory> \
  --out-dir <empty-audit-directory>
```

Expected `batch_input.jsonl` SHA-256:

`87dfabe25eea5fe12fdfb85da8dbc4da3a20718ceca8de464a2b2125ee1998b7`

Preparation was repeated in a second empty directory and produced the same hash. Audit all 13 request bodies for unit coverage, unique `custom_id`, model/config parity, image attachment only for the nine render units, absence of reference/reserve material, and absence of secrets.

Do not submit the batch during this audit. Submission is the next controlled action after the audit is clean and a fresh API key is provided through an environment variable.

### 7. Repository verification performed

The Python scripts compiled successfully. The v10.2 reference generation, batch preparation, and evaluation outputs were deterministic across clean reruns. A repository secret scan over the new committed files found no GitHub PAT or provider API key.

One unrelated local state was deliberately excluded: the user's modified v10.1 workbook `validation/extraction_v10_1/runs/2026-08-21_calibration/evaluation/SCOPE_READJUDICATION_v10_1_BLIND.xlsx` and its Excel lock file. Do not treat those uncommitted local files as part of this v10.2 change set and do not overwrite or commit them.

## Required audit response

Return a compact report with:

1. commit and file hashes actually inspected;
2. `PASS`, `FAIL`, or `NOT REPRODUCIBLE FROM SUPPLIED MATERIALS` for sections 1-7;
3. test cases and observed outputs for the one-to-one matcher and statistical metrics;
4. any discrepancy classified as blocker, major, or minor;
5. an explicit verdict: `SAFE TO SUBMIT OPENAI BATCH` or `DO NOT SUBMIT`, with concrete reasons;
6. the smallest corrective patch or action list for every blocker or major issue.

Do not infer a pass from the expected values above. Recompute them from the supplied artifacts and cite the relevant file and line or output field.
