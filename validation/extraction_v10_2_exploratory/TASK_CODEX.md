# OpenAI production task

Use only this package and the frozen OpenAI settings in `run_config.production.json`. Submit every supplied request through the Batch API. Do not inspect calibration gold, reserve material, Claude output, or prior extraction results before the raw provider output is sealed.

Do not re-chunk, screen, remove, reorder, or add units. Preserve untouched provider responses and provider metadata before parsing or source checking. One source-only retry is allowed only for transport, schema, coverage, or quotation-support failure and only for the failed units. Reject quotations still unsupported after that retry.
