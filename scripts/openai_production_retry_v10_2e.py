#!/usr/bin/env python3
"""Run and seal the single source-only retry for OpenAI v10.2e production."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from openai_batch_production_v10_2e import (
    TERMINAL,
    api_request,
    deterministic_zip,
    download_file,
    encoded_image,
    output_text,
    upload_batch_file,
    validate_subset,
    verify_package,
)


MODEL = "gpt-5.6-terra"
MAX_UNITS_PER_REQUEST = 2
MAX_OUTPUT_TOKENS = 32_000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def normalized(text: str) -> str:
    return re.sub(r"\s+", "", text)


def source_support(statement: dict, unit: dict) -> str:
    quote = statement.get("quote", "")
    source_text = unit.get("source_text", "")
    if quote and quote in source_text:
        return "exact_text"
    if quote and normalized(quote) in normalized(source_text):
        return "whitespace_normalized_text"
    if (
        statement.get("source_mode") in {"render", "text_and_render"}
        and unit.get("render_file")
    ):
        return "render_review_required"
    return "unsupported"


def package_context(package: Path) -> tuple[str, dict, dict]:
    prompt = (package / "PROMPT_CORE.md").read_text(encoding="utf-8").strip()
    codebook = (package / "codebook.csv").read_text(encoding="utf-8").strip()
    config = read_json(package / "run_config.production.json")["models"]["openai"]
    expected = {
        "model": MODEL,
        "endpoint": "/v1/responses",
        "processing": "batch",
        "reasoning_effort": "medium",
        "structured_outputs": True,
        "temperature": None,
        "max_output_tokens_per_request": MAX_OUTPUT_TOKENS,
    }
    if config != expected:
        raise ValueError("frozen OpenAI settings changed")
    return f"{prompt}\n\nCODEBOOK CSV\n{codebook}", read_json(package / "output_schema.json"), config


def main_provider_path(run_dir: Path) -> Path:
    return run_dir / "validated" / "openai_extractions_v10_2e_provider_parsed.jsonl"


def prepare(package: Path, run_dir: Path) -> None:
    verify_package(package)
    retry_dir = run_dir / "retry"
    if retry_dir.exists() and any(retry_dir.iterdir()):
        raise FileExistsError("retry directory is not empty")

    source_requests = read_jsonl(package / "inputs.jsonl")
    source_outputs = read_jsonl(main_provider_path(run_dir))
    input_units = {
        unit["unit_id"]: (request["request_id"], unit)
        for request in source_requests
        for unit in request["units"]
    }
    failed_units: dict[str, list[dict]] = {}
    support_counts = Counter()
    for response in source_outputs:
        for result in response["units"]:
            _, unit = input_units[result["unit_id"]]
            failures = []
            for ordinal, statement in enumerate(result["statements"], 1):
                support = source_support(statement, unit)
                support_counts[support] += 1
                if support == "unsupported":
                    failures.append({
                        "statement_ordinal": ordinal,
                        "quote_sha256": hashlib.sha256(
                            statement["quote"].encode("utf-8")
                        ).hexdigest(),
                    })
            if failures:
                failed_units[result["unit_id"]] = failures
    if not failed_units:
        raise RuntimeError("no unsupported source spans require retry")

    instructions, schema, config = package_context(package)
    retry_note = (
        "This is the single permitted source-only retry. Reprocess every supplied unit "
        "independently from scratch under the unchanged extraction rules. Each quote must "
        "be a complete, verbatim, contiguous substring of that unit's source_text, preserving "
        "every non-whitespace character exactly. Prefer exact source whitespace. Do not repair, "
        "paraphrase, merge, bracket, abbreviate, or reuse a prior quotation. If a render is "
        "supplied, transcribe only text visibly present in that render. If no eligible supported "
        "statement exists, return no statements with status ok. Return only the schema object."
    )
    failed_ids = sorted(failed_units)
    groups = [
        failed_ids[index:index + MAX_UNITS_PER_REQUEST]
        for index in range(0, len(failed_ids), MAX_UNITS_PER_REQUEST)
    ]
    rows = []
    mapping = []
    for index, unit_ids in enumerate(groups, 1):
        retry_id = f"PRD-SOURCE-RETRY-{index:05d}"
        units = [input_units[unit_id][1] for unit_id in unit_ids]
        request = {"request_id": retry_id, "units": units}
        content = [{
            "type": "input_text",
            "text": retry_note + "\n" + json.dumps(
                request, ensure_ascii=False, separators=(",", ":")
            ),
        }]
        attached = set()
        for unit in units:
            render_file = unit.get("render_file")
            if render_file and render_file not in attached:
                content.extend([
                    {"type": "input_text", "text": f"Render for unit {unit['unit_id']}:"},
                    {
                        "type": "input_image",
                        "image_url": encoded_image(package / render_file),
                        "detail": "high",
                    },
                ])
                attached.add(render_file)
        rows.append({
            "custom_id": retry_id,
            "method": "POST",
            "url": "/v1/responses",
            "body": {
                "model": config["model"],
                "instructions": instructions,
                "input": [{"role": "user", "content": content}],
                "reasoning": {"effort": config["reasoning_effort"]},
                "text": {"format": {
                    "type": "json_schema",
                    "name": "cbdc_extraction_v10_2e_source_retry",
                    "strict": True,
                    "schema": schema,
                }},
                "max_output_tokens": config["max_output_tokens_per_request"],
                "prompt_cache_key": "cbdc-v10-2e-production-source-retry",
                "store": False,
            },
        })
        mapping.append({
            "retry_request_id": retry_id,
            "units": [
                {
                    "unit_id": unit_id,
                    "original_request_id": input_units[unit_id][0],
                    "retry_cause": failed_units[unit_id],
                }
                for unit_id in unit_ids
            ],
        })

    retry_dir.mkdir(parents=True)
    batch_path = retry_dir / "batch_input.jsonl"
    write_jsonl(batch_path, rows)
    manifest = {
        "schema": "openai-batch-v10.2e-source-only-retry-prepare",
        "created_utc": utc_now(),
        "role": "single_permitted_source_only_retry",
        "model": MODEL,
        "reasoning_effort": "medium",
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "requests": len(rows),
        "units": len(failed_ids),
        "max_units_per_request": MAX_UNITS_PER_REQUEST,
        "main_source_support": dict(sorted(support_counts.items())),
        "mapping": mapping,
        "hashes": {
            "main_provider_parsed": sha256(main_provider_path(run_dir)),
            "package_inputs": sha256(package / "inputs.jsonl"),
            "prompt": sha256(package / "PROMPT_CORE.md"),
            "codebook": sha256(package / "codebook.csv"),
            "schema": sha256(package / "output_schema.json"),
            "retry_batch_input": sha256(batch_path),
        },
    }
    write_json(retry_dir / "prepare_manifest.json", manifest)
    print(json.dumps({
        key: value for key, value in manifest.items() if key != "mapping"
    }, ensure_ascii=False, indent=2))


def submit(run_dir: Path) -> None:
    retry_dir = run_dir / "retry"
    state_path = retry_dir / "provider_state.json"
    if state_path.exists():
        raise FileExistsError("retry already submitted")
    batch_input = retry_dir / "batch_input.jsonl"
    uploaded = upload_batch_file(batch_input)
    write_json(retry_dir / "raw" / "input_file_create.json", uploaded)
    batch = api_request("POST", "/batches", {
        "input_file_id": uploaded["id"],
        "endpoint": "/v1/responses",
        "completion_window": "24h",
        "metadata": {
            "protocol": "cbdc-extraction-v10-2e",
            "split": "production-single-source-only-retry",
        },
    })
    write_json(retry_dir / "raw" / "batch_create.json", batch)
    state = {
        "schema": "openai-batch-v10.2e-source-only-retry-state",
        "submitted_utc": utc_now(),
        "batch_id": batch["id"],
        "input_file_id": uploaded["id"],
        "batch_input_sha256": sha256(batch_input),
        "status": batch["status"],
    }
    write_json(state_path, state)
    print(json.dumps(state, indent=2))


def status(run_dir: Path) -> dict:
    retry_dir = run_dir / "retry"
    state = read_json(retry_dir / "provider_state.json")
    batch = api_request("GET", f"/batches/{state['batch_id']}")
    state["status"] = batch["status"]
    state["last_checked_utc"] = utc_now()
    write_json(retry_dir / "provider_state.json", state)
    write_json(retry_dir / "raw" / "batch_status_latest.json", batch)
    summary = {
        "batch_id": batch["id"],
        "status": batch["status"],
        "request_counts": batch.get("request_counts"),
        "output_file_id": batch.get("output_file_id"),
        "error_file_id": batch.get("error_file_id"),
    }
    print(json.dumps(summary, indent=2))
    return batch


def collect(package: Path, run_dir: Path) -> None:
    retry_dir = run_dir / "retry"
    batch = status(run_dir)
    if batch["status"] not in TERMINAL:
        raise RuntimeError(f"retry batch is not terminal: {batch['status']}")
    if batch.get("output_file_id"):
        (retry_dir / "raw" / "batch_results_raw.jsonl").write_bytes(
            download_file(batch["output_file_id"])
        )
    if batch.get("error_file_id"):
        (retry_dir / "raw" / "batch_errors_raw.jsonl").write_bytes(
            download_file(batch["error_file_id"])
        )

    files = [
        retry_dir / "batch_input.jsonl",
        retry_dir / "prepare_manifest.json",
        retry_dir / "provider_state.json",
        *list((retry_dir / "raw").glob("*")),
    ]
    raw_manifest = {
        "schema": "openai-batch-v10.2e-source-only-retry-raw-seal",
        "sealed_utc": utc_now(),
        "files": [
            {
                "path": path.relative_to(retry_dir).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in sorted(set(files))
        ],
    }
    raw_manifest_path = retry_dir / "raw_archive_manifest_prevalidation.json"
    write_json(raw_manifest_path, raw_manifest)
    files.append(raw_manifest_path)
    archive_path = retry_dir / "sealed_provider_raw.zip"
    deterministic_zip(archive_path, files, retry_dir)

    prepared = read_json(retry_dir / "prepare_manifest.json")
    expected = {
        row["retry_request_id"]: [item["unit_id"] for item in row["units"]]
        for row in prepared["mapping"]
    }
    schema = read_json(package / "output_schema.json")
    parsed = []
    failures = []
    usage = Counter()
    models = Counter()
    raw_path = retry_dir / "raw" / "batch_results_raw.jsonl"
    if raw_path.is_file():
        for outer in read_jsonl(raw_path):
            custom_id = outer.get("custom_id", "")
            try:
                if outer.get("error"):
                    raise ValueError(str(outer["error"]))
                response = outer["response"]
                if response.get("status_code") != 200:
                    raise ValueError(f"HTTP {response.get('status_code')}")
                body = response["body"]
                if body.get("status") != "completed" or body.get("incomplete_details"):
                    raise ValueError("provider response incomplete")
                models[body.get("model", "unknown")] += 1
                for name, value in (body.get("usage") or {}).items():
                    if isinstance(value, int):
                        usage[name] += value
                value = json.loads(output_text(body))
                validate_subset(value, schema)
                if custom_id not in expected or value["request_id"] != custom_id:
                    raise ValueError("request_id/custom_id mismatch")
                actual = [unit["unit_id"] for unit in value["units"]]
                if actual != expected[custom_id]:
                    raise ValueError("retry unit order or coverage mismatch")
                parsed.append(value)
            except Exception as error:
                failures.append({"custom_id": custom_id, "error": str(error)})
    returned = {row["request_id"] for row in parsed}
    for request_id in sorted(set(expected) - returned):
        if not any(row["custom_id"] == request_id for row in failures):
            failures.append({"custom_id": request_id, "error": "missing provider result"})
    parsed.sort(key=lambda row: row["request_id"])
    parsed_path = retry_dir / "validated" / "retry_provider_parsed.jsonl"
    write_jsonl(parsed_path, parsed)
    write_json(retry_dir / "validated" / "provider_parse_failures.json", failures)
    manifest = {
        "schema": "openai-batch-v10.2e-source-only-retry-collected",
        "collected_utc": utc_now(),
        "batch_id": batch["id"],
        "batch_status": batch["status"],
        "request_counts": batch.get("request_counts"),
        "returned_models": dict(models),
        "usage": dict(usage),
        "parsed_requests": len(parsed),
        "parsed_units": sum(len(row["units"]) for row in parsed),
        "parsed_statements": sum(
            len(unit["statements"]) for row in parsed for unit in row["units"]
        ),
        "parse_failures": failures,
        "hashes": {
            "sealed_provider_raw_zip": sha256(archive_path),
            "retry_provider_parsed_jsonl": sha256(parsed_path),
        },
    }
    write_json(retry_dir / "run_manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def merge(package: Path, run_dir: Path) -> None:
    main = read_jsonl(main_provider_path(run_dir))
    retries = read_jsonl(run_dir / "retry" / "validated" / "retry_provider_parsed.jsonl")
    prepared = read_json(run_dir / "retry" / "prepare_manifest.json")
    expected_units = {
        item["unit_id"]
        for row in prepared["mapping"]
        for item in row["units"]
    }
    retry_units = {}
    for response in retries:
        for unit in response["units"]:
            if unit["unit_id"] in retry_units or unit["unit_id"] not in expected_units:
                raise ValueError(f"unexpected duplicate retry unit: {unit['unit_id']}")
            retry_units[unit["unit_id"]] = deepcopy(unit)

    merged = deepcopy(main)
    replaced = []
    for response in merged:
        for index, unit in enumerate(response["units"]):
            if unit["unit_id"] in retry_units:
                response["units"][index] = retry_units[unit["unit_id"]]
                replaced.append(unit["unit_id"])
    if set(replaced) != set(retry_units) or len(replaced) != len(retry_units):
        raise ValueError("retry units were not replaced exactly once")
    missing = sorted(expected_units - set(retry_units))
    output_path = run_dir / "retry" / "merged_provider_responses.jsonl"
    write_jsonl(output_path, merged)
    manifest = {
        "schema": "openai-batch-v10.2e-source-only-retry-merge",
        "created_utc": utc_now(),
        "replacement_rule": "successful retry unit replaces its complete main-run unit",
        "failed_retry_rule": "retain main-run unit; deterministic finalizer rejects unsupported spans",
        "expected_retry_units": len(expected_units),
        "replaced_retry_units": len(replaced),
        "missing_retry_units": missing,
        "requests": len(merged),
        "units": sum(len(row["units"]) for row in merged),
        "statements": sum(
            len(unit["statements"]) for row in merged for unit in row["units"]
        ),
        "hashes": {
            "package_inputs": sha256(package / "inputs.jsonl"),
            "main_provider_parsed": sha256(main_provider_path(run_dir)),
            "retry_provider_parsed": sha256(
                run_dir / "retry" / "validated" / "retry_provider_parsed.jsonl"
            ),
            "merged_provider_responses": sha256(output_path),
        },
    }
    write_json(run_dir / "retry" / "merge_manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "submit", "status", "collect", "merge"):
        command = subparsers.add_parser(name)
        command.add_argument("--run-dir", required=True, type=Path)
        if name in {"prepare", "collect", "merge"}:
            command.add_argument("--package", required=True, type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    if args.command == "prepare":
        prepare(args.package.resolve(), run_dir)
    elif args.command == "submit":
        submit(run_dir)
    elif args.command == "status":
        status(run_dir)
    elif args.command == "collect":
        collect(args.package.resolve(), run_dir)
    else:
        merge(args.package.resolve(), run_dir)


if __name__ == "__main__":
    main()
