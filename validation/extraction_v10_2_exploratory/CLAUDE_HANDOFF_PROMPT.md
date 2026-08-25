I am attaching `EXPLORATORY_PRODUCTION_PACKAGE_v10_2e.zip` for a structured academic source-extraction run.

This is an operational data-processing task. Do not provide hidden reasoning, chain-of-thought, or a methodological essay. Do not browse the repository or internet. Use only the attached package and your locally configured Anthropic API key.

1. Extract the ZIP into a new empty directory.
2. Verify the package SHA-256 is `6874c8947f9a8578dcc36d17b1cbffa8f34703a70efb9d03044fbebcc013923f` and verify every contained file against `package_manifest.json`.
3. Read `TASK_CLAUDE.md`, `PROTOCOL_AMENDMENT.md`, `PROMPT_CORE.md`, `run_config.production.json`, `codebook.csv`, `source_authority.csv`, and `output_schema.json`.
4. Process all 661 requests / 3,963 units from `inputs.jsonl` through the Anthropic Messages Batch API using exactly the frozen Claude settings. Do not re-chunk, prefilter, reorder, omit, or add units. Do not use calibration gold, reserve material, OpenAI output, or prior extraction results.
5. Preserve and hash untouched provider responses before parsing or validation. Apply the package's single source-only retry rule only to failed units. Reject quotations that remain unsupported after that one retry.
6. Return one sealed ZIP containing raw responses, batch metadata, parsed output in request order, coverage, retry, rejection and usage reports, the returned model identifier, and a complete SHA-256 manifest.

In your response give only concise operational counts, hashes, usage/cost, deviations, and the sealed ZIP. Do not compare with another model and do not claim that the prior automated-extraction gate passed.

End with exactly one of:

- `RUN COMPLETE AND SEALED — NO PROTOCOL DEVIATION`
- `RUN COMPLETE AND SEALED — DEVIATION RECORDED`
- `RUN INCOMPLETE — DO NOT USE FOR PAPER`
- `NOT STARTED — PACKAGE PREFLIGHT FAILED`
