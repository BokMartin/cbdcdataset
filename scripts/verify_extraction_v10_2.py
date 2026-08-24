#!/usr/bin/env python3
"""Verify the blinded v10.2 input package and its deterministic ZIP."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import zipfile
from pathlib import Path

def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def verify(package: Path, archive_path: Path) -> dict:
    manifest = json.loads((package / "package_manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "extraction_v10_2_input_package"
    assert manifest["reserve_status"] == "sealed"
    assert manifest["requests"] == 13 and manifest["units"] == 78 and manifest["render_pages"] == 9

    expected_files = {"package_manifest.json"}
    for entry in manifest["files"]:
        path = package / entry["file"]
        assert path.is_file(), path
        assert path.stat().st_size == entry["bytes"], path
        assert digest_file(path) == entry["sha256"], path
        expected_files.add(entry["file"])

    actual_files = {p.relative_to(package).as_posix() for p in package.rglob("*") if p.is_file()}
    assert actual_files == expected_files, sorted(actual_files ^ expected_files)
    assert not any(part in {"human_gold", "calibration_reference", "model_outputs", "reserve"} for f in actual_files for part in Path(f).parts)

    with zipfile.ZipFile(archive_path) as archive:
        members = set(archive.namelist())
        assert members == actual_files, sorted(members ^ actual_files)
        for name in members:
            assert not name.startswith(("/", "\\")) and ".." not in Path(name).parts
            assert digest_bytes(archive.read(name)) == digest_file(package / name), name

    schema = json.loads((package / "output_schema.json").read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object" and schema["additionalProperties"] is False
    assert set(schema["required"]) == {"request_id", "units"}
    strength = schema["properties"]["units"]["items"]["properties"]["statements"]["items"]["properties"]["strength"]
    assert strength == {"enum": [1, 2, 3]}
    schema_codes = set(schema["properties"]["units"]["items"]["properties"]["statements"]["items"]["properties"]["code1"]["enum"])

    with (package / "codebook.csv").open("r", encoding="utf-8", newline="") as handle:
        codes = [row["code"] for row in csv.DictReader(handle)]
    assert len(codes) == len(set(codes)) == 35
    assert set(codes) == schema_codes

    requests = []
    units = []
    for line in (package / "inputs.jsonl").read_text(encoding="utf-8").splitlines():
        request = json.loads(line)
        requests.append(request)
        units.extend(request["units"])
    assert len(requests) == 13 and len({r["request_id"] for r in requests}) == 13
    assert len(units) == len({u["unit_id"] for u in units}) == 78
    assert all(u.get("project_owner") and u.get("authority_note") for u in units)
    assert next(u for u in units if u["unit_id"] == "CAL-058-U01")["language"] == "no"

    with (package / "source_authority.csv").open("r", encoding="utf-8", newline="") as handle:
        authority = list(csv.DictReader(handle))
    assert len(authority) == 78 and {r["unit_id"] for r in authority} == {u["unit_id"] for u in units}

    return {
        "package_sha256": digest_file(archive_path),
        "package_bytes": archive_path.stat().st_size,
        "files": len(actual_files),
        "requests": len(requests),
        "units": len(units),
        "renders": manifest["render_pages"],
        "codes": len(codes),
        "schema": "draft 2020-12 structure checked",
        "reserve": "sealed",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--zip", dest="archive_path", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.package.resolve(), args.archive_path.resolve()), indent=2))


if __name__ == "__main__":
    main()
