#!/usr/bin/env python3
"""Verify the sealed Claude v10.2e provider archive without model comparison."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath

from openai_batch_production_v10_2e import validate_subset


# The sealed provider output labels this visually inspected all-white render as
# source_unavailable. It is not one of the four max-token failures and carries no
# statements. Preserve the provider record and account for the label deviation
# explicitly instead of silently rewriting it to structural_blank.
AUDITED_BLANK_RENDER_EXCEPTIONS = {
    "PRD-0018-P0134-U01": {
        "render_sha256": "6af5ae493dc5fb2edcfc7172d79c4b26da0c0972e93fa8bcae443a06a23225f3",
        "note": "all-white render; provider used source_unavailable instead of structural_blank",
    }
}
AUDITED_BLOCK_ID_DEVIATIONS = {
    ("PRD-0003-P0003-U01", "AE_UAE_003-P0003-B01", "AM_UAE_003-P0003-B01"): 3,
}


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


def verify_archive(archive_path: Path, sealed_dir: Path) -> dict:
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("duplicate ZIP members")
        for name in names:
            member = PurePosixPath(name)
            if member.is_absolute() or ".." in member.parts or "\\" in name:
                raise ValueError(f"unsafe ZIP member: {name}")
        files = {name for name in names if not name.endswith("/")}
        extracted = {
            path.relative_to(sealed_dir).as_posix()
            for path in sealed_dir.rglob("*")
            if path.is_file()
        }
        if files != extracted:
            raise ValueError(f"archive/extracted mismatch: {sorted(files ^ extracted)}")
        for name in files:
            if hashlib.sha256(archive.read(name)).hexdigest() != sha256(sealed_dir / name):
                raise ValueError(f"archive member mismatch: {name}")
        return {
            "members": len(files),
            "uncompressed_bytes": sum(
                entry.file_size for entry in archive.infolist() if not entry.is_dir()
            ),
        }


def verify_package(package: Path, package_zip: Path, source_hashes: dict) -> dict:
    expected = {
        "package_zip": sha256(package_zip),
        "inputs.jsonl": sha256(package / "inputs.jsonl"),
        "PROMPT_CORE.md": sha256(package / "PROMPT_CORE.md"),
        "codebook.csv": sha256(package / "codebook.csv"),
        "output_schema.json": sha256(package / "output_schema.json"),
        "source_authority.csv": sha256(package / "source_authority.csv"),
        "run_config.production.json": sha256(package / "run_config.production.json"),
    }
    for name, digest in expected.items():
        if source_hashes.get(name) != digest:
            raise ValueError(f"Claude source hash mismatch: {name}")

    package_manifest = read_json(package / "package_manifest.json")
    if package_manifest.get("reserve_status") != "sealed_not_present":
        raise ValueError("reserve_status is not sealed_not_present")
    for entry in package_manifest["files"]:
        path = package / entry["file"]
        if (
            not path.is_file()
            or path.stat().st_size != entry["bytes"]
            or sha256(path) != entry["sha256"]
        ):
            raise ValueError(f"input package mismatch: {entry['file']}")
    return expected


def verify_raw(sealed_dir: Path, manifest: dict) -> dict:
    batches = manifest["batches"]
    line_counts = {}
    for batch in batches:
        path = sealed_dir / batch["raw_file"]
        if sha256(path) != batch["raw_sha256"]:
            raise ValueError(f"raw provider hash mismatch: {path.name}")
        lines = sum(1 for line in path.open("rb") if line.strip())
        if lines != batch["requests"]:
            raise ValueError(f"raw line count mismatch: {path.name}")
        line_counts[batch["role"]] = lines

    sha_files = {
        "main_run": sealed_dir / "raw" / "raw_main_sha.txt",
        "single_permitted_source_only_retry": sealed_dir / "raw" / "raw_retry_sha.txt",
    }
    for batch in batches:
        recorded = sha_files[batch["role"]].read_text(encoding="utf-8").split()[0]
        if recorded != batch["raw_sha256"]:
            raise ValueError(f"raw SHA sidecar mismatch: {batch['role']}")
    return line_counts


def verify_final(package: Path, sealed_dir: Path, manifest: dict) -> dict:
    output_path = sealed_dir / manifest["final_output"]["file"]
    if sha256(output_path) != manifest["final_output"]["sha256"]:
        raise ValueError("final output hash mismatch")

    schema = read_json(package / "output_schema.json")
    expected_requests = read_jsonl(package / "inputs.jsonl")
    actual_requests = read_jsonl(output_path)
    if len(actual_requests) != len(expected_requests):
        raise ValueError("final request count mismatch")

    expected_request_ids = [row["request_id"] for row in expected_requests]
    actual_request_ids = [row["request_id"] for row in actual_requests]
    if actual_request_ids != expected_request_ids:
        raise ValueError("final request order or coverage mismatch")

    expected_units = {
        unit["unit_id"]: unit
        for request in expected_requests
        for unit in request["units"]
    }
    seen_units = set()
    support = Counter()
    status = Counter()
    statements = 0
    empty_units = 0
    english_quote_en_nonnull = 0
    unsupported_labels = []
    block_id_deviations = Counter()

    for expected_request, actual_request in zip(expected_requests, actual_requests):
        validate_subset(actual_request, schema)
        wanted = [unit["unit_id"] for unit in expected_request["units"]]
        actual = [unit["unit_id"] for unit in actual_request["units"]]
        if actual != wanted:
            raise ValueError(f"unit order or coverage mismatch: {actual_request['request_id']}")
        for unit_result in actual_request["units"]:
            unit_id = unit_result["unit_id"]
            if unit_id in seen_units:
                raise ValueError(f"duplicate unit_id: {unit_id}")
            seen_units.add(unit_id)
            source_unit = expected_units[unit_id]
            source_text = source_unit.get("source_text", "")
            status[unit_result["status"]] += 1
            empty_units += not unit_result["statements"]
            if unit_result["status"] != "ok" and unit_result["statements"]:
                raise ValueError(f"non-ok unit contains statements: {unit_id}")
            for ordinal, statement in enumerate(unit_result["statements"], 1):
                statements += 1
                if source_unit["language"] == "en" and statement["quote_en"] is not None:
                    english_quote_en_nonnull += 1
                if not statement["quote"].strip():
                    raise ValueError(f"empty quote: {unit_id}:{ordinal}")
                if statement["strength"] not in {1, 2, 3}:
                    raise ValueError(f"strength outside 1..3: {unit_id}:{ordinal}")
                if statement["block_id"] != source_unit["block_id"]:
                    block_id_deviations[
                        (unit_id, source_unit["block_id"], statement["block_id"])
                    ] += 1
                expected_modes = {
                    "text": {"text"},
                    "render": {"render"},
                    "text_and_render": {"text", "render", "text_and_render"},
                }[source_unit["source_mode"]]
                if statement["source_mode"] not in expected_modes:
                    raise ValueError(f"source_mode mismatch: {unit_id}:{ordinal}")
                quote = statement["quote"]
                if quote and quote in source_text:
                    support["exact_text"] += 1
                elif quote and normalized(quote) in normalized(source_text):
                    support["whitespace_normalized_text"] += 1
                elif (
                    source_unit.get("render_file")
                    and statement["source_mode"] in {"render", "text_and_render"}
                ):
                    support["render_review_required"] += 1
                else:
                    support["unsupported"] += 1
                    unsupported_labels.append(f"{unit_id}:{ordinal}")

    if seen_units != set(expected_units):
        raise ValueError("global unit coverage mismatch")
    if support["unsupported"]:
        raise ValueError(f"unsupported final spans: {unsupported_labels[:20]}")
    if dict(block_id_deviations) != AUDITED_BLOCK_ID_DEVIATIONS:
        raise ValueError(f"unexpected block_id deviations: {dict(block_id_deviations)}")

    coverage = read_json(sealed_dir / "coverage_report.json")
    source_unavailable = sorted(
        unit["unit_id"]
        for response in actual_requests
        for unit in response["units"]
        if unit["status"] == "source_unavailable"
    )
    declared_unresolved = sorted(coverage["units_unresolved_truncated_after_permitted_retry"])
    sidecar_unresolved = sorted(read_json(sealed_dir / "units_without_usable_retry.json"))
    if declared_unresolved != sidecar_unresolved:
        raise ValueError("unresolved-unit declarations differ")
    if not set(declared_unresolved).issubset(source_unavailable):
        raise ValueError("declared unresolved units are not source_unavailable in final output")
    nontruncated_source_unavailable = sorted(set(source_unavailable) - set(declared_unresolved))
    if set(nontruncated_source_unavailable) != set(AUDITED_BLANK_RENDER_EXCEPTIONS):
        raise ValueError(
            "unexpected nontruncated source_unavailable units: "
            f"{nontruncated_source_unavailable}"
        )
    for unit_id in nontruncated_source_unavailable:
        source_unit = expected_units[unit_id]
        exception = AUDITED_BLANK_RENDER_EXCEPTIONS[unit_id]
        render_path = package / source_unit["render_file"]
        if (
            source_unit["source_mode"] != "render"
            or source_unit.get("source_text")
            or not render_path.is_file()
            or sha256(render_path) != exception["render_sha256"]
        ):
            raise ValueError(f"blank-render exception no longer matches source: {unit_id}")
    if any(
        unit["statements"]
        for response in actual_requests
        for unit in response["units"]
        if unit["unit_id"] in source_unavailable
    ):
        raise ValueError("source_unavailable units contain statements")

    retry_units = read_json(sealed_dir / "retry_units.json")
    if len(retry_units) != coverage["retry"]["units_retried"] or len(retry_units) != len(set(retry_units)):
        raise ValueError("retry-unit list mismatch")
    with (sealed_dir / "rejected_spans.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        rejected = sum(1 for _ in csv.DictReader(handle))
    if rejected != coverage["rejections"]["statements_rejected_span_unsupported_after_retry"]:
        raise ValueError("rejected-span count mismatch")
    if rejected != manifest["counts"]["statements_rejected_after_retry"]:
        raise ValueError("manifest rejected-span count mismatch")
    if coverage["units_with_valid_extraction"] != len(seen_units) - len(declared_unresolved):
        raise ValueError("coverage valid-unit count mismatch")

    counts = manifest["counts"]
    expected_counts = {
        "requests": len(actual_requests),
        "units": len(seen_units),
        "statements_accepted": statements,
        "empty_units": empty_units,
        "units_unresolved_truncated": len(declared_unresolved),
    }
    for name, value in expected_counts.items():
        if counts.get(name) != value:
            raise ValueError(f"manifest count mismatch: {name}")

    return {
        **expected_counts,
        "status_counts": dict(sorted(status.items())),
        "source_support": dict(sorted(support.items())),
        "english_quote_en_nonnull": english_quote_en_nonnull,
        "block_id_deviations": [
            {
                "unit_id": unit_id,
                "expected_block_id": expected_block_id,
                "provider_block_id": provider_block_id,
                "statements": count,
                "canonical_action": "replace with frozen unit block_id",
            }
            for (unit_id, expected_block_id, provider_block_id), count
            in sorted(block_id_deviations.items())
        ],
        "retry_units": len(retry_units),
        "rejected_spans_after_retry": rejected,
        "unresolved_unit_ids": declared_unresolved,
        "source_unavailable_unit_ids": source_unavailable,
        "nontruncated_source_unavailable": {
            unit_id: AUDITED_BLANK_RENDER_EXCEPTIONS[unit_id]
            for unit_id in nontruncated_source_unavailable
        },
        "final_output_sha256": sha256(output_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sealed-dir", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--package-zip", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    archive_path = args.archive.resolve()
    sealed_dir = args.sealed_dir.resolve()
    package = args.package.resolve()
    package_zip = args.package_zip.resolve()
    manifest = read_json(sealed_dir / "claude_run_manifest_v10_2e.json")
    if manifest["protocol_id"] != "cbdc_extraction_v10_2e_exploratory_assisted_production":
        raise ValueError("wrong protocol_id")
    if manifest["model_requested"] != "claude-sonnet-5" or manifest["model_returned"] != "claude-sonnet-5":
        raise ValueError("unexpected Claude model")

    result = {
        "valid": True,
        "archive_sha256": sha256(archive_path),
        "archive_bytes": archive_path.stat().st_size,
        "archive": verify_archive(archive_path, sealed_dir),
        "source_hashes": verify_package(package, package_zip, manifest["source_hashes"]),
        "raw_line_counts": verify_raw(sealed_dir, manifest),
        "final": verify_final(package, sealed_dir, manifest),
        "model_requested": manifest["model_requested"],
        "model_returned": manifest["model_returned"],
        "usage_total": manifest["usage_total"],
        "estimated_cost_usd_at_batch_rates": manifest["estimated_cost_usd_at_batch_rates"],
        "deviations": manifest["deviations"],
        "blinding_note": manifest["blinding_note"],
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
