# Claude v10.2 CBDC source-coding run

Use only the files in this package. Read `PROMPT_CORE.md`, `output_schema.json`, `run_config.json`, `codebook.csv`, and `source_authority.csv`, then process `inputs.jsonl`. Do not inspect any human-reference workbook, calibration labels, OpenAI output, previous Claude output, or the sealed reserve.

Use the exact Anthropic model and effort listed in `run_config.json`. Submit the 13 requests through the Messages Batch API. Use `output_config.format.type=json_schema` with the unmodified `output_schema.json`; its `strength` field already uses the provider-compatible enum `[1,2,3]`. Omit temperature. Set `max_tokens` to 12000 per request. If prompt caching is available for the shared prompt and codebook, use it and record cache usage; otherwise continue without changing content.

For each input line, return one compact schema-valid JSON object with the same `request_id` and complete unit coverage. No explanation or rationale is requested. Preserve raw responses before validation. One retry is allowed only for transport, schema, unit-coverage, or source-support failure, and only for the failed units. Unsupported quotations are rejected and logged; they are never repaired silently.

Archive:

- batch create/status/result metadata and returned model;
- every raw response, including failed attempts and retries;
- final schema-valid outputs in request order;
- per-request input/output/cache token usage and provider charge if shown;
- SHA-256 for the package, prompt, schema, codebook, inputs, each raw response, and final output;
- a rejection/retry log.

Seal the archive before any comparison. Return the sealed ZIP and a short operational summary containing request/unit/statement counts, empty units, rejected spans, retries, model, effort, and usage.
