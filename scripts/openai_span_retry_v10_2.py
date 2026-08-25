#!/usr/bin/env python3
"""Run the single source-only retry and finalize the OpenAI v10.2 output."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from openai_batch_v10_2 import (
    TERMINAL,
    api_request,
    deterministic_zip,
    download_file,
    encoded_image,
    output_text,
    upload_batch_file,
    validate_subset,
)


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
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def normalized(text: str) -> str:
    return re.sub(r"\s+", "", text)


def normalized_with_map(text: str) -> tuple[str, list[int]]:
    characters = []
    offsets = []
    for offset, character in enumerate(text):
        if not character.isspace():
            characters.append(character)
            offsets.append(offset)
    return "".join(characters), offsets


def occurrences(haystack: str, needle: str) -> list[int]:
    found = []
    offset = 0
    while needle:
        offset = haystack.find(needle, offset)
        if offset < 0:
            break
        found.append(offset)
        offset += 1
    return found


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


def package_context(package: Path) -> tuple[str, dict]:
    prompt = (package / "PROMPT_CORE.md").read_text(encoding="utf-8").strip()
    codebook = (package / "codebook.csv").read_text(encoding="utf-8").strip()
    authority = (package / "source_authority.csv").read_text(encoding="utf-8").strip()
    instructions = f"{prompt}\n\nCODEBOOK CSV\n{codebook}\n\nSOURCE AUTHORITY CSV\n{authority}"
    return instructions, read_json(package / "output_schema.json")


def prepare(package: Path, run_dir: Path) -> None:
    retry_dir = run_dir / "retry"
    if retry_dir.exists() and any(retry_dir.iterdir()):
        raise FileExistsError("retry directory is not empty")

    source_outputs = read_jsonl(
        run_dir / "validated" / "openai_extractions_v10_2_provider_parsed.jsonl"
    )
    source_requests = read_jsonl(package / "inputs.jsonl")
    input_units = {
        unit["unit_id"]: (request["request_id"], unit)
        for request in source_requests
        for unit in request["units"]
    }
    failed_units: dict[str, list[dict]] = {}
    for response in source_outputs:
        for result in response["units"]:
            _, unit = input_units[result["unit_id"]]
            failures = []
            for ordinal, statement in enumerate(result["statements"], 1):
                support = source_support(statement, unit)
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
        raise RuntimeError("no unsupported source spans require a retry")

    instructions, schema = package_context(package)
    retry_note = (
        "This is the single permitted source-only retry for one failed unit. "
        "Reprocess the supplied unit from scratch. Every quote must be one complete, "
        "verbatim, contiguous substring of source_text, preserving every character and "
        "all whitespace exactly. Do not repair, paraphrase, merge, bracket, abbreviate, "
        "or copy any prior quotation. If no eligible exact quotation exists, return no "
        "statement and use status ok. Return only the required JSON object."
    )
    rows = []
    mapping = []
    for unit_id in sorted(failed_units):
        original_request_id, unit = input_units[unit_id]
        retry_id = f"{original_request_id}-SPANRETRY-{unit_id}"
        request = {"request_id": retry_id, "units": [unit]}
        content = [{
            "type": "input_text",
            "text": retry_note + "\n" + json.dumps(
                request, ensure_ascii=False, separators=(",", ":")
            ),
        }]
        if unit.get("render_file"):
            render_path = package / unit["render_file"]
            content.extend([
                {"type": "input_text", "text": f"Render for unit {unit_id}:"},
                {"type": "input_image", "image_url": encoded_image(render_path), "detail": "high"},
            ])
        rows.append({
            "custom_id": retry_id,
            "method": "POST",
            "url": "/v1/responses",
            "body": {
                "model": "gpt-5.6-terra",
                "instructions": instructions,
                "input": [{"role": "user", "content": content}],
                "reasoning": {"effort": "medium"},
                "text": {"format": {
                    "type": "json_schema",
                    "name": "cbdc_extraction_v10_2_span_retry",
                    "strict": True,
                    "schema": schema,
                }},
                "max_output_tokens": 12000,
                "prompt_cache_key": "cbdc-v10-2-calibration",
                "store": False,
            },
        })
        mapping.append({
            "retry_request_id": retry_id,
            "original_request_id": original_request_id,
            "unit_id": unit_id,
            "retry_cause": failed_units[unit_id],
        })

    retry_dir.mkdir(parents=True)
    batch_path = retry_dir / "batch_input.jsonl"
    write_jsonl(batch_path, rows)
    manifest = {
        "schema": "openai-batch-v10.2-source-only-retry-prepare",
        "created_utc": utc_now(),
        "role": "single_permitted_source_only_retry",
        "requests": len(rows),
        "units": len(mapping),
        "mapping": mapping,
        "hashes": {
            "main_provider_parsed": sha256(
                run_dir / "validated" / "openai_extractions_v10_2_provider_parsed.jsonl"
            ),
            "package_inputs": sha256(package / "inputs.jsonl"),
            "prompt": sha256(package / "PROMPT_CORE.md"),
            "codebook": sha256(package / "codebook.csv"),
            "authority": sha256(package / "source_authority.csv"),
            "schema": sha256(package / "output_schema.json"),
            "retry_batch_input": sha256(batch_path),
        },
    }
    write_json(retry_dir / "prepare_manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def submit(run_dir: Path) -> None:
    retry_dir = run_dir / "retry"
    state_path = retry_dir / "provider_state.json"
    if state_path.exists():
        raise FileExistsError("retry provider state already exists; refusing duplicate submission")
    batch_input = retry_dir / "batch_input.jsonl"
    uploaded = upload_batch_file(batch_input)
    write_json(retry_dir / "raw" / "input_file_create.json", uploaded)
    batch = api_request("POST", "/batches", {
        "input_file_id": uploaded["id"],
        "endpoint": "/v1/responses",
        "completion_window": "24h",
        "metadata": {
            "protocol": "cbdc-extraction-v10-2",
            "split": "calibration-78-source-only-retry",
        },
    })
    write_json(retry_dir / "raw" / "batch_create.json", batch)
    state = {
        "schema": "openai-batch-v10.2-source-only-retry-state",
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
    state_path = retry_dir / "provider_state.json"
    state = read_json(state_path)
    batch = api_request("GET", f"/batches/{state['batch_id']}")
    state["status"] = batch["status"]
    state["last_checked_utc"] = utc_now()
    write_json(state_path, state)
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
        "schema": "openai-batch-v10.2-source-only-retry-raw-seal",
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
    write_json(retry_dir / "raw_archive_manifest_prevalidation.json", raw_manifest)
    files.append(retry_dir / "raw_archive_manifest_prevalidation.json")
    archive_path = retry_dir / "sealed_provider_raw.zip"
    deterministic_zip(archive_path, files, retry_dir)

    prepared = read_json(retry_dir / "prepare_manifest.json")
    expected = {row["retry_request_id"]: row for row in prepared["mapping"]}
    schema = read_json(package / "output_schema.json")
    parsed = []
    failures = []
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
                value = json.loads(output_text(response["body"]))
                validate_subset(value, schema)
                if custom_id not in expected or value["request_id"] != custom_id:
                    raise ValueError("request_id/custom_id mismatch")
                actual = [unit["unit_id"] for unit in value["units"]]
                if actual != [expected[custom_id]["unit_id"]]:
                    raise ValueError("retry unit coverage mismatch")
                parsed.append(value)
            except Exception as error:
                failures.append({"custom_id": custom_id, "error": str(error)})
    parsed.sort(key=lambda row: row["request_id"])
    write_jsonl(retry_dir / "validated" / "retry_provider_parsed.jsonl", parsed)
    write_json(retry_dir / "validated" / "provider_parse_failures.json", failures)
    manifest = {
        "schema": "openai-batch-v10.2-source-only-retry-collected",
        "collected_utc": utc_now(),
        "batch_id": batch["id"],
        "batch_status": batch["status"],
        "request_counts": batch.get("request_counts"),
        "usage": batch.get("usage"),
        "parsed_requests": len(parsed),
        "parsed_units": sum(len(row["units"]) for row in parsed),
        "parsed_statements": sum(
            len(unit["statements"]) for row in parsed for unit in row["units"]
        ),
        "parse_failures": failures,
        "hashes": {
            "sealed_provider_raw_zip": sha256(archive_path),
            "retry_provider_parsed_jsonl": sha256(
                retry_dir / "validated" / "retry_provider_parsed.jsonl"
            ),
        },
    }
    write_json(retry_dir / "run_manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def finalize(package: Path, run_dir: Path) -> None:
    main_path = run_dir / "validated" / "openai_extractions_v10_2_provider_parsed.jsonl"
    retry_path = run_dir / "retry" / "validated" / "retry_provider_parsed.jsonl"
    main = read_jsonl(main_path)
    retries = read_jsonl(retry_path)
    retry_manifest = read_json(run_dir / "retry" / "prepare_manifest.json")
    mapping = {row["retry_request_id"]: row for row in retry_manifest["mapping"]}
    if set(mapping) != {row["request_id"] for row in retries}:
        raise ValueError("retry output coverage differs from prepared retry mapping")

    source_requests = read_jsonl(package / "inputs.jsonl")
    source_units = {
        unit["unit_id"]: unit
        for request in source_requests
        for unit in request["units"]
    }
    retry_units = {}
    for response in retries:
        row = mapping[response["request_id"]]
        retry_units[row["unit_id"]] = deepcopy(response["units"][0])

    final = deepcopy(main)
    replaced = []
    for response in final:
        for index, unit in enumerate(response["units"]):
            if unit["unit_id"] in retry_units:
                response["units"][index] = retry_units[unit["unit_id"]]
                replaced.append(unit["unit_id"])
    if set(replaced) != set(retry_units) or len(replaced) != len(retry_units):
        raise ValueError("retry units were not replaced exactly once")

    status_changes = []
    quote_changes = []
    ambiguous = []
    render_review = []
    rejected = []
    support_counts = Counter()
    for response in final:
        response["request_id"] = next(
            request["request_id"]
            for request in source_requests
            if any(
                source_unit["unit_id"] == response["units"][0]["unit_id"]
                for source_unit in request["units"]
            )
        )
        for unit in response["units"]:
            source_unit = source_units[unit["unit_id"]]
            source_text = source_unit.get("source_text", "")
            if unit["status"] == "structural_blank" and source_text.strip():
                status_changes.append({
                    "unit_id": unit["unit_id"],
                    "from": "structural_blank",
                    "to": "ok",
                    "reason": "non-empty source processed with no eligible statement",
                })
                unit["status"] = "ok"

            kept = []
            normalized_source, offsets = normalized_with_map(source_text)
            for ordinal, statement in enumerate(unit["statements"], 1):
                label = f"{unit['unit_id']} statement {ordinal}"
                quote = statement["quote"]
                if quote in source_text:
                    support_counts["exact_text"] += 1
                    kept.append(statement)
                    continue
                normalized_quote = normalized(quote)
                starts = occurrences(normalized_source, normalized_quote)
                if len(starts) == 1:
                    start = offsets[starts[0]]
                    end = offsets[starts[0] + len(normalized_quote) - 1] + 1
                    exact_quote = source_text[start:end]
                    if normalized(exact_quote) != normalized_quote:
                        raise RuntimeError(f"offset reconstruction failed for {label}")
                    quote_changes.append({
                        "label": label,
                        "old_quote_sha256": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
                        "new_quote_sha256": hashlib.sha256(exact_quote.encode("utf-8")).hexdigest(),
                        "source_start": start,
                        "source_end": end,
                        "reason": "restore exact source whitespace only",
                    })
                    statement["quote"] = exact_quote
                    support_counts["whitespace_restored"] += 1
                    kept.append(statement)
                elif len(starts) > 1:
                    ambiguous.append({
                        "label": label,
                        "normalized_occurrences": len(starts),
                        "quote_sha256": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
                    })
                    support_counts["normalized_ambiguous"] += 1
                    kept.append(statement)
                elif (
                    statement.get("source_mode") in {"render", "text_and_render"}
                    and source_unit.get("render_file")
                ):
                    render_review.append({
                        "label": label,
                        "render_file": source_unit["render_file"],
                        "quote": quote,
                    })
                    support_counts["render_review_required"] += 1
                    kept.append(statement)
                else:
                    rejected.append({
                        "request_id": response["request_id"],
                        "unit_id": unit["unit_id"],
                        "block_id": statement.get("block_id", ""),
                        "code1": statement.get("code1", ""),
                        "quote": quote,
                        "reason": "unsupported_after_single_source_only_retry",
                    })
                    support_counts["rejected_unsupported"] += 1
            unit["statements"] = kept
            if not kept and source_text.strip() and unit["status"] != "skip_language":
                unit["status"] = "ok"

    final.sort(key=lambda row: row["request_id"])
    final_dir = run_dir / "final"
    output_path = final_dir / "openai_extractions_v10_2_source_canonical.jsonl"
    write_jsonl(output_path, final)
    log = {
        "method": "source-only deterministic finalization; no reference or other-model output accessed",
        "retry_units_replaced": sorted(replaced),
        "status_changes": status_changes,
        "quote_changes": quote_changes,
        "normalized_ambiguous": ambiguous,
        "render_review_required": render_review,
        "rejected": [
            {key: value for key, value in row.items() if key != "quote"} for row in rejected
        ],
    }
    write_json(final_dir / "source_only_transform_log.json", log)
    rejected_path = final_dir / "rejected_spans.csv"
    rejected_path.parent.mkdir(parents=True, exist_ok=True)
    with rejected_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "request_id", "unit_id", "block_id", "code1", "quote", "reason"
        ], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rejected)

    statement_count = sum(
        len(unit["statements"]) for row in final for unit in row["units"]
    )
    manifest = {
        "schema": "openai-batch-v10.2-final-source-canonical",
        "created_utc": utc_now(),
        "requests": len(final),
        "units": sum(len(row["units"]) for row in final),
        "statements_accepted": statement_count,
        "empty_units": sum(
            not unit["statements"] for row in final for unit in row["units"]
        ),
        "retry_units_replaced": len(replaced),
        "source_support": dict(sorted(support_counts.items())),
        "status_changes": len(status_changes),
        "quotes_restored_to_exact_source": len(quote_changes),
        "normalized_ambiguous": len(ambiguous),
        "render_review_required": len(render_review),
        "rejected_spans_after_retry": len(rejected),
        "hashes": {
            "main_provider_parsed": sha256(main_path),
            "retry_provider_parsed": sha256(retry_path),
            "package_inputs": sha256(package / "inputs.jsonl"),
            "final_source_canonical": sha256(output_path),
            "transform_log": sha256(final_dir / "source_only_transform_log.json"),
            "rejected_spans": sha256(rejected_path),
        },
    }
    write_json(final_dir / "finalization_manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "submit", "status", "collect", "finalize"):
        command = subparsers.add_parser(name)
        command.add_argument("--run-dir", required=True, type=Path)
        if name in {"prepare", "collect", "finalize"}:
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
    elif args.command == "finalize":
        finalize(args.package.resolve(), run_dir)


if __name__ == "__main__":
    main()
