# Claude extraction task

Read `PROMPT_CORE.md`, `output_schema.json`, `run_config.json`, and the packaged `codebook.csv` (the repository source is `data/codebook.csv`). Process the blinded package in `inputs.jsonl`; do not open files under `validation/human_gold`, `validation/calibration_v10`, or any OpenAI output directory.

Use the exact Claude model and effort in `run_config.json`. Prefer the Messages Batch API with `output_config.format.type=json_schema`. If using the Claude web interface, record the displayed model, interface, start/end UTC times, and available settings; record unavailable backend parameters as unavailable rather than guessing.

For each request, apply `PROMPT_CORE.md` to every supplied unit and return only one schema-valid JSON object. Do not add explanations or analysis text. Preserve raw responses in request order, then create a manifest containing custom IDs, usage, source/input/prompt/schema hashes, returned model, and response SHA-256. Do not inspect gold or OpenAI results until the Claude archive is sealed.
