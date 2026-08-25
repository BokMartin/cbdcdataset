#!/usr/bin/env python3
"""Verify the frozen v10.2e exploratory production input package."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def estimated_tokens(text: str, language: str) -> int:
    return max(1, math.ceil(len(text) / (2.0 if language in {"zh", "ja", "ko"} else 4.0)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    package = args.package.resolve()
    manifest = json.loads((package / "package_manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "cbdc_extraction_v10_2e_exploratory_input_package"
    assert manifest["reserve_status"] == "sealed_not_present"
    for entry in manifest["files"]:
        path = package / entry["file"]
        assert path.is_file(), entry["file"]
        assert path.stat().st_size == entry["bytes"], entry["file"]
        assert sha256(path) == entry["sha256"], entry["file"]

    requests = read_jsonl(package / "inputs.jsonl")
    request_ids = [request["request_id"] for request in requests]
    units = [unit for request in requests for unit in request["units"]]
    unit_ids = [unit["unit_id"] for unit in units]
    assert len(request_ids) == len(set(request_ids)) == 661
    assert len(unit_ids) == len(set(unit_ids)) == 3963
    assert max(len(request["units"]) for request in requests) <= 6
    request_tokens = [
        sum(estimated_tokens(unit["source_text"], unit["language"]) for unit in request["units"])
        for request in requests
    ]
    assert max(request_tokens) <= 42000
    assert all(unit.get("project_owner") and unit.get("authority_note") for unit in units)
    assert all(unit.get("block_id") and unit.get("source_mode") in {"text", "render", "text_and_render"} for unit in units)
    assert sum(bool(unit.get("render_file")) for unit in units) == 345
    assert sum(not unit.get("source_text") for unit in units) == 74
    assert not any("RES-" in unit["unit_id"] or "reserve_sealed" in unit["unit_id"] for unit in units)

    with (package / "corpus_manifest.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        corpus = list(csv.DictReader(handle))
    with (package / "source_authority.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        authority = list(csv.DictReader(handle))
    with (package / "codebook.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        codes = list(csv.DictReader(handle))
    assert len(corpus) == len({row["doc_id"] for row in corpus}) == 113
    assert sum(int(row["pages"]) for row in corpus) == 3963
    assert len(authority) == len({row["doc_id"] for row in authority}) == 113
    assert len(codes) == len({row["code"] for row in codes}) == 35

    result = {
        "valid": True,
        "package_manifest_sha256": sha256(package / "package_manifest.json"),
        "documents": len(corpus),
        "pages": sum(int(row["pages"]) for row in corpus),
        "requests": len(requests),
        "units": len(units),
        "render_units": sum(bool(unit.get("render_file")) for unit in units),
        "empty_text_render_units": sum(not unit.get("source_text") and bool(unit.get("render_file")) for unit in units),
        "max_units_per_request": max(len(request["units"]) for request in requests),
        "max_estimated_source_tokens_per_request": max(request_tokens),
        "estimated_source_tokens": sum(request_tokens),
        "reserve_present": False,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
