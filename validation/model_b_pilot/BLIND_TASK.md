# Model B extraction task

Use only the files in this package. Do not open the project repository, human annotations, prior extraction outputs, or external sources.

For every `ready` row in `input_manifest.csv`, read the corresponding file in `prompts/` and apply it independently. Save one JSON object per line to `responses.jsonl`:

```json
{"input_id":"B001","status":"ok","response":[...]}
```

For every `skipped_lt250` row, copy the recorded status without inventing a response:

```json
{"input_id":"B008","status":"skipped_lt250","response":null}
```

Process inputs in ascending `input_id`. Do not revise earlier responses after seeing later pages. Do not deduplicate against any other extraction. Preserve the raw arrays exactly except for removal of accidental Markdown fences required to parse JSON.

Create `run_metadata.json` with the fields required by `protocol.json`. Record the exact model name shown by the interface; do not infer a version that is not displayed.

