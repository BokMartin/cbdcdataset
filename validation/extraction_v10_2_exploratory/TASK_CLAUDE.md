# Claude production task

Use only this package. Verify every file against `package_manifest.json`, read `PROTOCOL_AMENDMENT.md`, `PROMPT_CORE.md`, `run_config.production.json`, `codebook.csv`, `source_authority.csv`, and `output_schema.json`, then process every line of `inputs.jsonl` through the Anthropic Messages Batch API with the frozen settings.

Do not inspect calibration gold, reserve material, OpenAI output, or prior extraction results. Do not re-chunk, screen, remove, reorder, or add units. Preserve untouched provider responses and provider metadata before parsing or source checking. One source-only retry is allowed only for transport, schema, coverage, or quotation-support failure and only for the failed units. Reject quotations still unsupported after that retry.

Return a sealed ZIP containing raw responses, parsed provider output in request order, retry and rejection logs, coverage and usage reports, a SHA-256 manifest, and the exact returned model identifier. Do not compare models or adjudicate substantive relevance in this run.
