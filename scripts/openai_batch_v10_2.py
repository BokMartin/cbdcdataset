#!/usr/bin/env python3
"""Prepare, submit, monitor, and collect the frozen OpenAI v10.2 Batch run."""

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
from datetime import datetime, timezone
from pathlib import Path


API_ROOT = "https://api.openai.com/v1"
TERMINAL = {"completed", "failed", "expired", "cancelled"}


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
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


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


def prepare(package: Path, output_dir: Path) -> None:
    config = read_json(package / "run_config.json")
    provider = config["models"]["openai"]
    if provider != {
        "model": "gpt-5.6-terra",
        "endpoint": "/v1/responses",
        "processing": "batch",
        "reasoning_effort": "medium",
        "structured_outputs": True,
        "temperature": None,
    }:
        raise ValueError("run_config OpenAI settings differ from the frozen protocol")

    schema = read_json(package / "output_schema.json")
    prompt = (package / "PROMPT_CORE.md").read_text(encoding="utf-8").strip()
    codebook = (package / "codebook.csv").read_text(encoding="utf-8").strip()
    authority = (package / "source_authority.csv").read_text(encoding="utf-8").strip()
    instructions = f"{prompt}\n\nCODEBOOK CSV\n{codebook}\n\nSOURCE AUTHORITY CSV\n{authority}"
    requests = read_jsonl(package / "inputs.jsonl")
    if len(requests) != 13 or sum(len(row["units"]) for row in requests) != 78:
        raise ValueError("expected 13 requests and 78 units")

    batch_rows = []
    for request in requests:
        content = [{
            "type": "input_text",
            "text": "Process this request object and return the required JSON object.\n" + json.dumps(
                request, ensure_ascii=False, separators=(",", ":")
            ),
        }]
        for unit in request["units"]:
            if unit.get("render_file"):
                render_path = package / unit["render_file"]
                content.append({"type": "input_text", "text": f"Render for unit {unit['unit_id']}:"})
                content.append({"type": "input_image", "image_url": encoded_image(render_path), "detail": "high"})
        batch_rows.append({
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
                    "name": "cbdc_extraction_v10_2",
                    "strict": True,
                    "schema": schema,
                }},
                "max_output_tokens": 32000,
                "prompt_cache_key": "cbdc-v10-2-calibration",
                "store": False,
            },
        })

    output_dir.mkdir(parents=True, exist_ok=True)
    batch_path = output_dir / "batch_input.jsonl"
    write_jsonl(batch_path, batch_rows)
    manifest = {
        "schema": "openai-batch-v10.2-prepare",
        "created_utc": utc_now(),
        "package": str(package.resolve()),
        "model": provider["model"],
        "endpoint": provider["endpoint"],
        "processing": provider["processing"],
        "reasoning_effort": provider["reasoning_effort"],
        "temperature": None,
        "structured_outputs": True,
        "schema_unmodified": True,
        "requests": len(batch_rows),
        "units": sum(len(row["units"]) for row in requests),
        "render_pages": sum(bool(unit.get("render_file")) for row in requests for unit in row["units"]),
        "hashes": {
            "package_manifest": sha256(package / "package_manifest.json"),
            "inputs": sha256(package / "inputs.jsonl"),
            "prompt": sha256(package / "PROMPT_CORE.md"),
            "codebook": sha256(package / "codebook.csv"),
            "authority": sha256(package / "source_authority.csv"),
            "schema": sha256(package / "output_schema.json"),
            "batch_input": sha256(batch_path),
        },
    }
    write_json(output_dir / "prepare_manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is missing")
    return key


def api_request(method: str, path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        API_ROOT + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API {error.code}: {detail}") from error


def upload_batch_file(path: Path) -> dict:
    boundary = "----codex" + secrets.token_hex(16)
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\nbatch\r\n".encode(),
        (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            "Content-Type: application/jsonl\r\n\r\n"
        ).encode(),
        path.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    request = urllib.request.Request(
        API_ROOT + "/files",
        data=b"".join(parts),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI upload {error.code}: {detail}") from error


def submit(output_dir: Path) -> None:
    batch_input = output_dir / "batch_input.jsonl"
    if not batch_input.is_file():
        raise FileNotFoundError("run prepare first")
    uploaded = upload_batch_file(batch_input)
    write_json(output_dir / "raw" / "input_file_create.json", uploaded)
    batch = api_request("POST", "/batches", {
        "input_file_id": uploaded["id"],
        "endpoint": "/v1/responses",
        "completion_window": "24h",
        "metadata": {"protocol": "cbdc-extraction-v10-2", "split": "calibration-78"},
    })
    write_json(output_dir / "raw" / "batch_create.json", batch)
    state = {
        "schema": "openai-batch-v10.2-state",
        "submitted_utc": utc_now(),
        "batch_id": batch["id"],
        "input_file_id": uploaded["id"],
        "batch_input_sha256": sha256(batch_input),
        "status": batch["status"],
    }
    write_json(output_dir / "provider_state.json", state)
    print(json.dumps(state, indent=2))


def status(output_dir: Path) -> dict:
    state_path = output_dir / "provider_state.json"
    state = read_json(state_path)
    batch = api_request("GET", f"/batches/{state['batch_id']}")
    state["status"] = batch["status"]
    state["last_checked_utc"] = utc_now()
    write_json(state_path, state)
    write_json(output_dir / "raw" / "batch_status_latest.json", batch)
    print(json.dumps({
        "batch_id": batch["id"],
        "status": batch["status"],
        "request_counts": batch.get("request_counts"),
        "output_file_id": batch.get("output_file_id"),
        "error_file_id": batch.get("error_file_id"),
    }, indent=2))
    return batch


def download_file(file_id: str) -> bytes:
    request = urllib.request.Request(
        API_ROOT + f"/files/{file_id}/content",
        method="GET",
        headers={"Authorization": f"Bearer {api_key()}"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return response.read()


def deterministic_zip(path: Path, files: list[Path], root: Path) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
            info = zipfile.ZipInfo(source.relative_to(root).as_posix())
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, source.read_bytes())


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


def collect(output_dir: Path, package: Path) -> None:
    batch = status(output_dir)
    if batch["status"] not in TERMINAL:
        raise RuntimeError(f"batch is not terminal: {batch['status']}")
    if batch.get("output_file_id"):
        (output_dir / "raw" / "batch_results_raw.jsonl").write_bytes(
            download_file(batch["output_file_id"])
        )
    if batch.get("error_file_id"):
        (output_dir / "raw" / "batch_errors_raw.jsonl").write_bytes(
            download_file(batch["error_file_id"])
        )

    prevalidation_files = [
        output_dir / "batch_input.jsonl",
        output_dir / "prepare_manifest.json",
        output_dir / "provider_state.json",
        *list((output_dir / "raw").glob("*")),
    ]
    raw_manifest = {
        "schema": "openai-batch-v10.2-raw-seal",
        "sealed_utc": utc_now(),
        "files": [
            {"path": str(path.relative_to(output_dir)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in sorted(set(prevalidation_files))
        ],
    }
    write_json(output_dir / "raw_archive_manifest_prevalidation.json", raw_manifest)
    prevalidation_files.append(output_dir / "raw_archive_manifest_prevalidation.json")
    archive_path = output_dir / "sealed_provider_raw.zip"
    deterministic_zip(archive_path, prevalidation_files, output_dir)

    expected = {row["request_id"]: row for row in read_jsonl(package / "inputs.jsonl")}
    schema = read_json(package / "output_schema.json")
    parsed = []
    failures = []
    raw_path = output_dir / "raw" / "batch_results_raw.jsonl"
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
                if value["request_id"] != custom_id or custom_id not in expected:
                    raise ValueError("request_id/custom_id mismatch")
                wanted = [unit["unit_id"] for unit in expected[custom_id]["units"]]
                actual = [unit["unit_id"] for unit in value["units"]]
                if len(actual) != len(set(actual)) or set(actual) != set(wanted):
                    raise ValueError("unit coverage mismatch")
                parsed.append(value)
            except Exception as error:
                failures.append({"custom_id": custom_id, "error": str(error)})
    parsed.sort(key=lambda row: row["request_id"])
    write_jsonl(output_dir / "validated" / "openai_extractions_v10_2_provider_parsed.jsonl", parsed)
    write_json(output_dir / "validated" / "provider_parse_failures.json", failures)
    manifest = {
        "schema": "openai-batch-v10.2-collected",
        "collected_utc": utc_now(),
        "batch_id": batch["id"],
        "batch_status": batch["status"],
        "returned_model": batch.get("model"),
        "request_counts": batch.get("request_counts"),
        "usage": batch.get("usage"),
        "parsed_requests": len(parsed),
        "parsed_units": sum(len(row["units"]) for row in parsed),
        "parsed_statements": sum(len(unit["statements"]) for row in parsed for unit in row["units"]),
        "parse_failures": failures,
        "hashes": {
            "sealed_provider_raw_zip": sha256(archive_path),
            "provider_parsed_jsonl": sha256(output_dir / "validated" / "openai_extractions_v10_2_provider_parsed.jsonl"),
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
    elif args.command == "collect":
        collect(args.out_dir.resolve(), args.package.resolve())


if __name__ == "__main__":
    main()
