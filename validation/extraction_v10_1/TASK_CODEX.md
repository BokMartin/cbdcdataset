# OpenAI / Codex extraction task

Read `PROMPT_CORE.md`, `output_schema.json`, `run_config.json`, and the packaged `codebook.csv` (the repository source is `data/codebook.csv`). Process the blinded package in `inputs.jsonl`; do not open files under `validation/human_gold`, `validation/calibration_v10`, or any Claude output directory.

Use the exact OpenAI model and effort in `run_config.json`. For an API run, use structured outputs and asynchronous Batch processing. For a Codex app run, record the displayed model, interface, start/end UTC times, and any settings the interface exposes; record unavailable backend parameters as unavailable rather than guessing.

For each request, apply `PROMPT_CORE.md` to every supplied unit and return only one schema-valid JSON object. Do not add explanations or analysis text. Preserve raw responses in request order, then create a manifest containing request IDs, usage, source/input/prompt/schema hashes, model returned by the provider, and response SHA-256. Do not inspect gold or Claude results until the OpenAI archive is sealed.
