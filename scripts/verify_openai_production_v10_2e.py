#!/usr/bin/env python3
"""Verify the sealed OpenAI v10.2e main run, retry, merge, and final output."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath

from openai_batch_production_v10_2e import validate_subset, verify_package


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def normalized(text: str) -> str:
    return re.sub(r"\s+", "", text)


def source_support(statement: dict, unit: dict) -> str:
    quote = statement.get("quote", "")
    source = unit.get("source_text", "")
    if quote and quote in source:
        return "exact_text"
    if quote and normalized(quote) in normalized(source):
        return "whitespace_normalized_text"
    if unit.get("render_file") and statement.get("source_mode") in {
        "render",
        "text_and_render",
    }:
        return "render_review_required"
    return "unsupported"


def verify_seal(archive: Path, manifest_path: Path) -> dict:
    manifest = read_json(manifest_path)
    expected = {entry["path"]: entry for entry in manifest["files"]}
    manifest_name = manifest_path.name
    with zipfile.ZipFile(archive) as handle:
        names = handle.namelist()
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate ZIP members: {archive}")
        for name in names:
            member = PurePosixPath(name)
            if member.is_absolute() or ".." in member.parts or "\\" in name:
                raise ValueError(f"unsafe ZIP member: {name}")
        files = {name for name in names if not name.endswith("/")}
        if files != set(expected) | {manifest_name}:
            raise ValueError(f"sealed archive member mismatch: {archive}")
        if handle.read(manifest_name) != manifest_path.read_bytes():
            raise ValueError(f"sealed manifest mismatch: {archive}")
        for name, entry in expected.items():
            value = handle.read(name)
            if len(value) != entry["bytes"]:
                raise ValueError(f"sealed member size mismatch: {name}")
            if hashlib.sha256(value).hexdigest() != entry["sha256"]:
                raise ValueError(f"sealed member hash mismatch: {name}")
    return {
        "sha256": sha256(archive),
        "members": len(expected) + 1,
        "sealed_schema": manifest["schema"],
    }


def verify_main(run_dir: Path, package: Path) -> tuple[list[dict], dict]:
    main_dir = run_dir / "main"
    manifest = read_json(main_dir / "run_manifest.json")
    archive = main_dir / "sealed_provider_raw.zip"
    parsed_path = main_dir / "openai_extractions_v10_2e_provider_parsed.jsonl"
    seal = verify_seal(
        archive, main_dir / "raw_archive_manifest_prevalidation.json"
    )
    if seal["sha256"] != manifest["hashes"]["sealed_provider_raw_zip"]:
        raise ValueError("main sealed archive hash mismatch")
    if sha256(parsed_path) != manifest["hashes"]["provider_parsed_jsonl"]:
        raise ValueError("main parsed output hash mismatch")
    if manifest["returned_models"] != {"gpt-5.6-terra": 661}:
        raise ValueError("unexpected main returned model or request count")
    if manifest["parse_failures"]:
        raise ValueError("main run contains parse failures")

    parsed = read_jsonl(parsed_path)
    packaged = read_jsonl(package / "inputs.jsonl")
    if [row["request_id"] for row in parsed] != [
        row["request_id"] for row in packaged
    ]:
        raise ValueError("main request order or coverage mismatch")
    if len(parsed) != manifest["parsed_requests"]:
        raise ValueError("main parsed request count mismatch")
    if sum(len(row["units"]) for row in parsed) != manifest["parsed_units"]:
        raise ValueError("main parsed unit count mismatch")
    if sum(
        len(unit["statements"]) for row in parsed for unit in row["units"]
    ) != manifest["parsed_statements"]:
        raise ValueError("main parsed statement count mismatch")
    return parsed, {"seal": seal, "manifest": manifest}


def verify_retry_targets(
    main: list[dict], package: Path, prepare: dict
) -> tuple[set[str], Counter]:
    source_units = {
        unit["unit_id"]: unit
        for request in read_jsonl(package / "inputs.jsonl")
        for unit in request["units"]
    }
    failed: dict[str, list[dict]] = {}
    support = Counter()
    for response in main:
        for result in response["units"]:
            failures = []
            source = source_units[result["unit_id"]]
            for ordinal, statement in enumerate(result["statements"], 1):
                label = source_support(statement, source)
                support[label] += 1
                if label == "unsupported":
                    failures.append(
                        {
                            "statement_ordinal": ordinal,
                            "quote_sha256": hashlib.sha256(
                                statement["quote"].encode("utf-8")
                            ).hexdigest(),
                        }
                    )
            if failures:
                failed[result["unit_id"]] = failures

    declared = {}
    request_ids = []
    for mapping in prepare["mapping"]:
        request_ids.append(mapping["retry_request_id"])
        for unit in mapping["units"]:
            if unit["unit_id"] in declared:
                raise ValueError(f"duplicate declared retry unit: {unit['unit_id']}")
            declared[unit["unit_id"]] = unit["retry_cause"]
    if len(request_ids) != len(set(request_ids)):
        raise ValueError("duplicate retry request_id")
    if declared != failed:
        raise ValueError("retry target set or cause differs from main unsupported spans")
    if prepare["requests"] != len(request_ids) or prepare["units"] != len(declared):
        raise ValueError("retry prepare counts mismatch")
    if prepare["main_source_support"] != dict(sorted(support.items())):
        raise ValueError("main source-support counts mismatch")
    return set(declared), support


def verify_retry(
    run_dir: Path, package: Path, main: list[dict]
) -> tuple[list[dict], set[str], dict]:
    retry_dir = run_dir / "retry"
    prepare = read_json(retry_dir / "prepare_manifest.json")
    expected_units, main_support = verify_retry_targets(main, package, prepare)
    if prepare["hashes"]["package_inputs"] != sha256(package / "inputs.jsonl"):
        raise ValueError("retry package input hash mismatch")
    for name, file_name in {
        "prompt": "PROMPT_CORE.md",
        "codebook": "codebook.csv",
        "schema": "output_schema.json",
    }.items():
        if prepare["hashes"][name] != sha256(package / file_name):
            raise ValueError(f"retry frozen {name} hash mismatch")
    if prepare["hashes"]["main_provider_parsed"] != sha256(
        run_dir / "main" / "openai_extractions_v10_2e_provider_parsed.jsonl"
    ):
        raise ValueError("retry main parsed hash mismatch")

    archive = retry_dir / "sealed_provider_raw.zip"
    manifest = read_json(retry_dir / "run_manifest.json")
    parsed_path = retry_dir / "retry_provider_parsed.jsonl"
    seal = verify_seal(
        archive, retry_dir / "raw_archive_manifest_prevalidation.json"
    )
    if seal["sha256"] != manifest["hashes"]["sealed_provider_raw_zip"]:
        raise ValueError("retry sealed archive hash mismatch")
    if sha256(parsed_path) != manifest["hashes"]["retry_provider_parsed_jsonl"]:
        raise ValueError("retry parsed output hash mismatch")
    if manifest["batch_status"] != "completed":
        raise ValueError("retry batch did not complete")
    if set(manifest["returned_models"]) != {"gpt-5.6-terra"}:
        raise ValueError("unexpected retry returned model")

    parsed = read_jsonl(parsed_path)
    returned_units = {
        unit["unit_id"] for response in parsed for unit in response["units"]
    }
    if not returned_units.issubset(expected_units):
        raise ValueError("retry returned an unrequested unit")
    if len(returned_units) != sum(len(row["units"]) for row in parsed):
        raise ValueError("retry output contains duplicate units")
    if len(parsed) != manifest["parsed_requests"]:
        raise ValueError("retry parsed request count mismatch")
    if len(returned_units) != manifest["parsed_units"]:
        raise ValueError("retry parsed unit count mismatch")
    return parsed, expected_units, {
        "seal": seal,
        "manifest": manifest,
        "expected_units": len(expected_units),
        "returned_units": len(returned_units),
        "main_source_support": dict(sorted(main_support.items())),
    }


def verify_merge(
    run_dir: Path,
    package: Path,
    main: list[dict],
    retry: list[dict],
    expected_retry_units: set[str],
) -> tuple[list[dict], dict]:
    retry_dir = run_dir / "retry"
    merged_path = retry_dir / "merged_provider_responses.jsonl"
    manifest = read_json(retry_dir / "merge_manifest.json")
    merged = read_jsonl(merged_path)
    if manifest["hashes"]["merged_provider_responses"] != sha256(merged_path):
        raise ValueError("merged output hash mismatch")
    if manifest["hashes"]["package_inputs"] != sha256(package / "inputs.jsonl"):
        raise ValueError("merge package hash mismatch")

    retry_units = {
        unit["unit_id"]: unit for response in retry for unit in response["units"]
    }
    main_units = {
        unit["unit_id"]: unit for response in main for unit in response["units"]
    }
    merged_units = {
        unit["unit_id"]: unit for response in merged for unit in response["units"]
    }
    if len(merged_units) != sum(len(row["units"]) for row in merged):
        raise ValueError("merged output contains duplicate units")
    if set(main_units) != set(merged_units):
        raise ValueError("merged global unit coverage mismatch")
    for unit_id, value in merged_units.items():
        wanted = retry_units.get(unit_id, main_units[unit_id])
        if value != wanted:
            raise ValueError(f"merge replacement mismatch: {unit_id}")
    if sorted(expected_retry_units - set(retry_units)) != manifest["missing_retry_units"]:
        raise ValueError("merge missing-retry declaration mismatch")
    if manifest["expected_retry_units"] != len(expected_retry_units):
        raise ValueError("merge expected retry count mismatch")
    if manifest["replaced_retry_units"] != len(retry_units):
        raise ValueError("merge replacement count mismatch")
    return merged, manifest


def verify_final(run_dir: Path, package: Path, merged: list[dict]) -> dict:
    final_dir = run_dir / "final"
    output_path = final_dir / "openai_extractions_v10_2e_canonical.jsonl"
    audit_path = final_dir / "source_verification_audit.csv"
    manifest = read_json(final_dir / "finalization_manifest.json")
    if manifest["semantic_or_classification_changes"] != 0:
        raise ValueError("finalization reports semantic or classification changes")
    expected_hashes = {
        "package_inputs_sha256": sha256(package / "inputs.jsonl"),
        "sealed_provider_responses_sha256": sha256(
            run_dir / "retry" / "merged_provider_responses.jsonl"
        ),
        "finalized_responses_sha256": sha256(output_path),
        "audit_sha256": sha256(audit_path),
    }
    for name, value in expected_hashes.items():
        if manifest["hashes"].get(name) != value:
            raise ValueError(f"finalization hash mismatch: {name}")

    final = read_jsonl(output_path)
    packaged = read_jsonl(package / "inputs.jsonl")
    schema = read_json(package / "output_schema.json")
    if [row["request_id"] for row in final] != [
        row["request_id"] for row in packaged
    ]:
        raise ValueError("final request order or coverage mismatch")
    if [row["request_id"] for row in merged] != [
        row["request_id"] for row in final
    ]:
        raise ValueError("merge/final request mismatch")
    source_units = {
        unit["unit_id"]: unit for row in packaged for unit in row["units"]
    }
    status = Counter()
    support = Counter()
    statements = 0
    seen = set()
    for expected_request, response in zip(packaged, final):
        validate_subset(response, schema)
        if [unit["unit_id"] for unit in response["units"]] != [
            unit["unit_id"] for unit in expected_request["units"]
        ]:
            raise ValueError(f"final unit order mismatch: {response['request_id']}")
        for result in response["units"]:
            unit_id = result["unit_id"]
            if unit_id in seen:
                raise ValueError(f"duplicate final unit: {unit_id}")
            seen.add(unit_id)
            unit = source_units[unit_id]
            status[result["status"]] += 1
            if result["status"] != "ok" and result["statements"]:
                raise ValueError(f"non-ok final unit contains statements: {unit_id}")
            for ordinal, statement in enumerate(result["statements"], 1):
                statements += 1
                if statement["block_id"] != unit["block_id"]:
                    raise ValueError(f"final block_id mismatch: {unit_id}:{ordinal}")
                if unit["language"] == "en" and statement["quote_en"] is not None:
                    raise ValueError(f"English final quote_en is not null: {unit_id}:{ordinal}")
                label = source_support(statement, unit)
                support[label] += 1
                if label == "unsupported":
                    raise ValueError(f"unsupported final span: {unit_id}:{ordinal}")
    if seen != set(source_units):
        raise ValueError("final global unit coverage mismatch")

    with audit_path.open("r", encoding="utf-8-sig", newline="") as handle:
        audit_rows = list(csv.DictReader(handle))
    counts = manifest["counts"]
    expected_counts = {
        "requests": len(final),
        "units": len(seen),
        "statements_after": statements,
    }
    for name, value in expected_counts.items():
        if counts.get(name) != value:
            raise ValueError(f"finalization count mismatch: {name}")
    if len(audit_rows) != counts["statements_before"]:
        raise ValueError("finalization audit row count mismatch")
    audit_status = Counter(row["span_status"] for row in audit_rows)
    audit_checks = {
        "whitespace_restored": counts["whitespace_restored_to_exact_source"],
        "normalized_ambiguous": counts["normalized_ambiguous_retained"],
        "rejected_unsupported_after_permitted_retry": counts["unsupported_rejected"],
        "render_review_required": counts["render_review_required"],
    }
    for label, value in audit_checks.items():
        if audit_status[label] != value:
            raise ValueError(f"audit/finalization count mismatch: {label}")
    return {
        "hash": sha256(output_path),
        "requests": len(final),
        "units": len(seen),
        "statements": statements,
        "unit_status": dict(sorted(status.items())),
        "source_support": dict(sorted(support.items())),
        "finalization_counts": counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    package = args.package.resolve()
    verify_package(package)

    main_rows, main_report = verify_main(run_dir, package)
    retry_rows, expected_retry_units, retry_report = verify_retry(
        run_dir, package, main_rows
    )
    merged_rows, merge_report = verify_merge(
        run_dir, package, main_rows, retry_rows, expected_retry_units
    )
    result = {
        "valid": True,
        "main": main_report,
        "retry": retry_report,
        "merge": merge_report,
        "final": verify_final(run_dir, package, merged_rows),
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
