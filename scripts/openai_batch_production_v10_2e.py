#!/usr/bin/env python3
"""Prepare, submit, monitor, and collect the OpenAI v10.2e production batch."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import secrets
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


API_ROOT = "https://api.openai.com/v1"
TERMINAL = {"completed", "failed", "expired", "cancelled"}
MAX_SHARD_BYTES = 150 * 1024 * 1024


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
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def verify_package(package: Path) -> dict:
    manifest = read_json(package / "package_manifest.json")
    if manifest.get("schema") != "cbdc_extraction_v10_2e_exploratory_input_package":
        raise ValueError("Wrong package schema")
    if manifest.get("reserve_status") != "sealed_not_present":
        raise ValueError("Reserve status is not sealed_not_present")
    for entry in manifest["files"]:
        path = package / entry["file"]
        if not path.is_file() or path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
            raise ValueError(f"Package mismatch: {entry['file']}")
    return manifest


def validate_subset(value, schema: dict, location: str = "$") -> None:
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{location}: value outside enum")
    kind = schema.get("type")
    if isinstance(kind, list):
        for candidate in kind:
            try:
                validate_subset(value, {**schema, "type": candidate}, location)
                return
            except (TypeError, ValueError):
                pass
        raise TypeError(f"{location}: value does not match {kind}")
    if kind == "object":
        if not isinstance(value, dict):
            raise TypeError(f"{location}: expected object")
        for field in schema.get("required", []):
            if field not in value:
                raise ValueError(f"{location}: missing {field}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(properties)
            if extra:
                raise ValueError(f"{location}: extra fields {sorted(extra)}")
        for field, child in value.items():
            if field in properties:
                validate_subset(child, properties[field], f"{location}.{field}")
    elif kind == "array":
        if not isinstance(value, list):
            raise TypeError(f"{location}: expected array")
        for index, child in enumerate(value):
            validate_subset(child, schema.get("items", {}), f"{location}[{index}]")
    elif kind == "string" and not isinstance(value, str):
        raise TypeError(f"{location}: expected string")
    elif kind == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        raise TypeError(f"{location}: expected integer")
    elif kind == "null" and value is not None:
        raise TypeError(f"{location}: expected null")


def encoded_image(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def output_text(body: dict) -> str:
    pieces = []
    for item in body.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                pieces.append(content.get("text", ""))
    if not pieces:
        raise ValueError("response contains no output_text")
    return "".join(pieces)


def prepare(package: Path, output_dir: Path) -> None:
    package_manifest = verify_package(package)
    config = read_json(package / "run_config.production.json")
    provider = config["models"]["openai"]
    expected = {
        "model": "gpt-5.6-terra",
        "endpoint": "/v1/responses",
        "processing": "batch",
        "reasoning_effort": "medium",
        "structured_outputs": True,
        "temperature": None,
        "max_output_tokens_per_request": 32000,
    }
    if provider != expected:
        raise ValueError("OpenAI settings differ from frozen production config")
    schema = read_json(package / "output_schema.json")
    prompt = (package / "PROMPT_CORE.md").read_text(encoding="utf-8").strip()
    codebook = (package / "codebook.csv").read_text(encoding="utf-8").strip()
    instructions = f"{prompt}\n\nCODEBOOK CSV\n{codebook}"
    requests = read_jsonl(package / "inputs.jsonl")
    expected_counts = package_manifest["counts"]
    if len(requests) != expected_counts["requests"]:
        raise ValueError("Request count differs from package manifest")
    if sum(len(row["units"]) for row in requests) != expected_counts["units"]:
        raise ValueError("Unit count differs from package manifest")

    serialized = []
    for request in requests:
        content = [{
            "type": "input_text",
            "text": "Process this request object and return the required JSON object.\n" + json.dumps(
                request, ensure_ascii=False, separators=(",", ":")
            ),
        }]
        attached = set()
        for unit in request["units"]:
            render_file = unit.get("render_file")
            if render_file and render_file not in attached:
                content.append({"type": "input_text", "text": f"Render for unit {unit['unit_id']}:"})
                content.append({
                    "type": "input_image",
                    "image_url": encoded_image(package / render_file),
                    "detail": "high",
                })
                attached.add(render_file)
        row = {
            "custom_id": request["request_id"],
            "method": "POST",
            "url": "/v1/responses",
            "body": {
                "model": provider["model"],
                "instructions": instructions,
                "input": [{"role": "user", "content": content}],
                "reasoning": {"effort": provider["reasoning_effort"]},
                "text": {"format": {
                    "type": "json_schema",
                    "name": "cbdc_extraction_v10_2e",
                    "strict": True,
                    "schema": schema,
                }},
                "max_output_tokens": provider["max_output_tokens_per_request"],
                "prompt_cache_key": "cbdc-v10-2e-production",
                "store": False,
            },
        }
        serialized.append(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")

    output_dir.mkdir(parents=True, exist_ok=False)
    shard_rows = []
    shard_bytes = 0
    shards = []
    for row in serialized:
        if shard_rows and shard_bytes + len(row) > MAX_SHARD_BYTES:
            shards.append(shard_rows)
            shard_rows = []
            shard_bytes = 0
        shard_rows.append(row)
        shard_bytes += len(row)
    if shard_rows:
        shards.append(shard_rows)

    shard_manifest = []
    for index, rows in enumerate(shards, 1):
        path = output_dir / f"batch_input_{index:03d}.jsonl"
        path.write_bytes(b"".join(rows))
        shard_manifest.append({
            "shard": index,
            "file": path.name,
            "requests": len(rows),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        })
    manifest = {
        "schema": "openai-batch-v10.2e-prepare",
        "created_utc": utc_now(),
        "package": str(package.resolve()),
        "package_manifest_sha256": sha256(package / "package_manifest.json"),
        "model": provider["model"],
        "reasoning_effort": provider["reasoning_effort"],
        "temperature": None,
        "structured_outputs": True,
        "schema_unmodified": True,
        "requests": len(requests),
        "units": sum(len(row["units"]) for row in requests),
        "render_pages": expected_counts["render_pages"],
        "shards": shard_manifest,
        "hashes": {
            "inputs": sha256(package / "inputs.jsonl"),
            "prompt": sha256(package / "PROMPT_CORE.md"),
            "codebook": sha256(package / "codebook.csv"),
            "schema": sha256(package / "output_schema.json"),
        },
    }
    write_json(output_dir / "prepare_manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is missing from this process environment")
    return key


def api_request(method: str, path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        API_ROOT + path,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API {error.code}: {detail}") from error


def upload_batch_file(path: Path) -> dict:
    boundary = "----codex" + secrets.token_hex(16)
    body = b"".join([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\nbatch\r\n".encode(),
        (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            "Content-Type: application/jsonl\r\n\r\n"
        ).encode(),
        path.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    request = urllib.request.Request(
        API_ROOT + "/files",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI upload {error.code}: {detail}") from error


def submit(output_dir: Path) -> None:
    prepared = read_json(output_dir / "prepare_manifest.json")
    state_path = output_dir / "provider_state.json"
    if state_path.exists():
        raise FileExistsError(state_path)
    jobs = []
    for shard in prepared["shards"]:
        path = output_dir / shard["file"]
        uploaded = upload_batch_file(path)
        batch = api_request("POST", "/batches", {
            "input_file_id": uploaded["id"],
            "endpoint": "/v1/responses",
            "completion_window": "24h",
            "metadata": {
                "protocol": "cbdc-extraction-v10-2e",
                "split": "exploratory-full-corpus",
                "shard": str(shard["shard"]),
            },
        })
        write_json(output_dir / "raw" / f"shard_{shard['shard']:03d}_input_file_create.json", uploaded)
        write_json(output_dir / "raw" / f"shard_{shard['shard']:03d}_batch_create.json", batch)
        jobs.append({
            "shard": shard["shard"],
            "batch_id": batch["id"],
            "input_file_id": uploaded["id"],
            "batch_input_sha256": shard["sha256"],
            "status": batch["status"],
        })
    state = {"schema": "openai-batch-v10.2e-state", "submitted_utc": utc_now(), "jobs": jobs}
    write_json(state_path, state)
    print(json.dumps(state, indent=2))


def status(output_dir: Path) -> dict:
    state_path = output_dir / "provider_state.json"
    state = read_json(state_path)
    all_terminal = True
    summary = []
    for job in state["jobs"]:
        batch = api_request("GET", f"/batches/{job['batch_id']}")
        job["status"] = batch["status"]
        job["last_checked_utc"] = utc_now()
        write_json(output_dir / "raw" / f"shard_{job['shard']:03d}_batch_status_latest.json", batch)
        all_terminal = all_terminal and batch["status"] in TERMINAL
        summary.append({
            "shard": job["shard"],
            "batch_id": batch["id"],
            "status": batch["status"],
            "request_counts": batch.get("request_counts"),
            "output_file_id": batch.get("output_file_id"),
            "error_file_id": batch.get("error_file_id"),
        })
    state["all_terminal"] = all_terminal
    write_json(state_path, state)
    result = {"all_terminal": all_terminal, "jobs": summary}
    print(json.dumps(result, indent=2))
    return result


def download_file(file_id: str) -> bytes:
    request = urllib.request.Request(
        API_ROOT + f"/files/{file_id}/content",
        method="GET",
        headers={"Authorization": f"Bearer {api_key()}"},
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return response.read()


def deterministic_zip(path: Path, files: list[Path], root: Path) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source in sorted(set(files), key=lambda item: item.relative_to(root).as_posix()):
            info = zipfile.ZipInfo(source.relative_to(root).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, source.read_bytes())


def collect(output_dir: Path, package: Path) -> None:
    summary = status(output_dir)
    if not summary["all_terminal"]:
        raise RuntimeError("At least one batch shard is not terminal")
    state = read_json(output_dir / "provider_state.json")
    output_files = []
    for job_summary in summary["jobs"]:
        shard = job_summary["shard"]
        if job_summary.get("output_file_id"):
            path = output_dir / "raw" / f"shard_{shard:03d}_results_raw.jsonl"
            path.write_bytes(download_file(job_summary["output_file_id"]))
            output_files.append(path)
        if job_summary.get("error_file_id"):
            path = output_dir / "raw" / f"shard_{shard:03d}_errors_raw.jsonl"
            path.write_bytes(download_file(job_summary["error_file_id"]))

    prevalidation_files = [
        output_dir / "prepare_manifest.json",
        output_dir / "provider_state.json",
        *list(output_dir.glob("batch_input_*.jsonl")),
        *list((output_dir / "raw").glob("*")),
    ]
    raw_manifest = {
        "schema": "openai-batch-v10.2e-raw-seal",
        "sealed_utc": utc_now(),
        "files": [
            {
                "path": path.relative_to(output_dir).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in sorted(set(prevalidation_files))
        ],
    }
    raw_manifest_path = output_dir / "raw_archive_manifest_prevalidation.json"
    write_json(raw_manifest_path, raw_manifest)
    prevalidation_files.append(raw_manifest_path)
    archive_path = output_dir / "sealed_provider_raw.zip"
    deterministic_zip(archive_path, prevalidation_files, output_dir)

    expected = {row["request_id"]: row for row in read_jsonl(package / "inputs.jsonl")}
    schema = read_json(package / "output_schema.json")
    parsed = []
    failures = []
    usage = Counter()
    returned_models = Counter()
    seen_custom_ids = set()
    for raw_path in output_files:
        for outer in read_jsonl(raw_path):
            custom_id = outer.get("custom_id", "")
            try:
                if custom_id in seen_custom_ids:
                    raise ValueError("duplicate custom_id")
                seen_custom_ids.add(custom_id)
                if outer.get("error"):
                    raise ValueError(str(outer["error"]))
                response = outer["response"]
                if response.get("status_code") != 200:
                    raise ValueError(f"HTTP {response.get('status_code')}")
                body = response["body"]
                returned_models[body.get("model", "unknown")] += 1
                for name, value in (body.get("usage") or {}).items():
                    if isinstance(value, int):
                        usage[name] += value
                value = json.loads(output_text(body))
                validate_subset(value, schema)
                if value["request_id"] != custom_id or custom_id not in expected:
                    raise ValueError("request_id/custom_id mismatch")
                wanted = [unit["unit_id"] for unit in expected[custom_id]["units"]]
                actual = [unit["unit_id"] for unit in value["units"]]
                if len(actual) != len(set(actual)) or set(actual) != set(wanted):
                    raise ValueError("unit coverage mismatch")
                parsed.append(value)
            except Exception as error:
                failures.append({"custom_id": custom_id, "error": str(error)})
    missing_requests = sorted(set(expected) - {row["request_id"] for row in parsed})
    for request_id in missing_requests:
        if not any(row["custom_id"] == request_id for row in failures):
            failures.append({"custom_id": request_id, "error": "missing provider result"})
    parsed.sort(key=lambda row: row["request_id"])
    parsed_path = output_dir / "validated" / "openai_extractions_v10_2e_provider_parsed.jsonl"
    write_jsonl(parsed_path, parsed)
    write_json(output_dir / "validated" / "provider_parse_failures.json", failures)
    manifest = {
        "schema": "openai-batch-v10.2e-collected",
        "collected_utc": utc_now(),
        "jobs": state["jobs"],
        "returned_models": dict(returned_models),
        "usage": dict(usage),
        "parsed_requests": len(parsed),
        "parsed_units": sum(len(row["units"]) for row in parsed),
        "parsed_statements": sum(len(unit["statements"]) for row in parsed for unit in row["units"]),
        "parse_failures": failures,
        "hashes": {
            "sealed_provider_raw_zip": sha256(archive_path),
            "provider_parsed_jsonl": sha256(parsed_path),
        },
    }
    write_json(output_dir / "run_manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "submit", "status", "collect"):
        command = subparsers.add_parser(name)
        command.add_argument("--out-dir", type=Path, required=True)
        if name in {"prepare", "collect"}:
            command.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.package.resolve(), args.out_dir.resolve())
    elif args.command == "submit":
        submit(args.out_dir.resolve())
    elif args.command == "status":
        status(args.out_dir.resolve())
    else:
        collect(args.out_dir.resolve(), args.package.resolve())


if __name__ == "__main__":
    main()
