# Codex v10.2 CBDC source-coding run

Use only the files in this package. Read `PROMPT_CORE.md`, `output_schema.json`, `run_config.json`, `codebook.csv`, and `source_authority.csv`, then process `inputs.jsonl`. Do not inspect any human-reference workbook, calibration labels, Claude output, prior model output, or the sealed reserve.

Use the exact OpenAI model and effort in `run_config.json`, the Batch API, and structured output with the unmodified schema. Return one compact JSON object per request with the same `request_id` and full unit coverage. No explanation or rationale is requested.

Archive raw responses and usage before validation. Retry only failed units once for transport, schema, coverage, or source-support failure. Reject and log unsupported quotations. Seal the archive before any comparison and record model, effort, request/unit/statement counts, empty units, retries, usage, and SHA-256 values.
