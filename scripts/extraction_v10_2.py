#!/usr/bin/env python3
"""Build the blinded v10.2 calibration package from the sealed v10.1 inputs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "validation" / "extraction_v10_2"
FIXED_ZIP_TIME = (2026, 8, 24, 0, 0, 0)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def verify_base_package(base: Path) -> dict:
    manifest_path = base / "package_manifest.json"
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("schema") != "extraction_v10_1_input_package":
        raise ValueError("Base package is not the sealed v10.1 input package")
    for entry in manifest.get("files", []):
        path = base / entry["file"]
        if not path.is_file():
            raise FileNotFoundError(path)
        if sha256(path) != entry["sha256"] or path.stat().st_size != entry["bytes"]:
            raise ValueError(f"Base-package hash/size mismatch: {path}")
    return manifest


def load_authority(unit_id: str, doc_id: str, rules: dict) -> dict:
    unit_rule = rules["unit_overrides"].get(unit_id)
    doc_rule = rules["document_defaults"].get(doc_id)
    rule = unit_rule or doc_rule
    if not rule:
        raise KeyError(f"No authority rule for {unit_id} / {doc_id}")
    return {
        "project_owner": rule["project_owner"],
        "authority_note": rule["authority_note"],
    }


def build_codebook(output: Path) -> int:
    source = ROOT / "data" / "codebook.csv"
    overrides = load_json(SPEC / "codebook_overrides.json")
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    seen = set()
    for row in rows:
        patch = overrides.get(row["code"])
        if patch:
            row.update(patch)
            seen.add(row["code"])
    missing = sorted(set(overrides) - seen)
    if missing:
        raise KeyError(f"Codebook overrides not found: {missing}")
    if len(rows) != 35 or len({row['code'] for row in rows}) != 35:
        raise ValueError("Expected 35 unique codes")
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def deterministic_zip(source_dir: Path, output_zip: Path) -> None:
    if output_zip.exists():
        raise FileExistsError(output_zip)
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(p for p in source_dir.rglob("*") if p.is_file()):
            relative = path.relative_to(source_dir).as_posix()
            info = zipfile.ZipInfo(relative, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def build(base: Path, output_dir: Path, output_zip: Path) -> dict:
    if output_dir.exists():
        raise FileExistsError(output_dir)
    base_manifest = verify_base_package(base)
    output_dir.mkdir(parents=True)

    rules = load_json(SPEC / "authority_overrides.json")
    requests = []
    units = []
    with (base / "inputs.jsonl").open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            request = json.loads(line)
            for unit in request["units"]:
                authority = load_authority(unit["unit_id"], unit["doc_id"], rules)
                unit.update(authority)
                if unit["unit_id"] == "CAL-058-U01":
                    unit["language"] = "no"
                units.append(unit)
            requests.append(request)

    if len(requests) != 13 or len(units) != 78:
        raise ValueError(f"Expected 13 requests / 78 units, got {len(requests)} / {len(units)}")
    with (output_dir / "inputs.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for request in requests:
            handle.write(canonical_json(request) + "\n")

    with (base / "input_manifest.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        manifest_rows = list(reader)
        manifest_fields = list(reader.fieldnames or [])
    by_unit = {unit["unit_id"]: unit for unit in units}
    for row in manifest_rows:
        unit = by_unit[row["unit_id"]]
        row["language"] = unit["language"]
        row["project_owner"] = unit["project_owner"]
        row["authority_note"] = unit["authority_note"]
    manifest_fields += ["project_owner", "authority_note"]
    write_csv(output_dir / "input_manifest.csv", manifest_fields, manifest_rows)

    authority_rows = [
        {
            "unit_id": unit["unit_id"],
            "doc_id": unit["doc_id"],
            "page": unit["page"],
            "language": unit["language"],
            "project_owner": unit["project_owner"],
            "authority_note": unit["authority_note"],
        }
        for unit in units
    ]
    write_csv(
        output_dir / "source_authority.csv",
        ["unit_id", "doc_id", "page", "language", "project_owner", "authority_note"],
        authority_rows,
    )

    for name in [
        "PROMPT_CORE.md",
        "PROTOCOL.md",
        "TASK_CLAUDE.md",
        "TASK_CODEX.md",
        "output_schema.json",
        "run_config.json",
        "authority_overrides.json",
        "codebook_overrides.json",
    ]:
        shutil.copyfile(SPEC / name, output_dir / name)
    build_codebook(output_dir / "codebook.csv")

    render_dir = base / "renders"
    if render_dir.is_dir():
        shutil.copytree(render_dir, output_dir / "renders")

    # Verify unchanged source and render hashes recorded in the original manifest.
    for row in manifest_rows:
        if row.get("render_file"):
            render = output_dir / row["render_file"]
            if not render.is_file() or sha256(render) != row["render_sha256"]:
                raise ValueError(f"Render mismatch: {row['unit_id']}")
        if row["text_sha256"] != hashlib.sha256(by_unit[row["unit_id"]]["source_text"].encode("utf-8")).hexdigest():
            raise ValueError(f"Source text changed: {row['unit_id']}")

    files = []
    for path in sorted(p for p in output_dir.rglob("*") if p.is_file()):
        files.append({
            "file": path.relative_to(output_dir).as_posix(),
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        })
    package_manifest = {
        "schema": "extraction_v10_2_input_package",
        "phase": "final_calibration_candidate",
        "reserve_status": "sealed",
        "pages": 78,
        "units": 78,
        "requests": 13,
        "render_pages": sum(1 for row in manifest_rows if row.get("render_file")),
        "derived_from": {
            "schema": base_manifest["schema"],
            "package_manifest_sha256": sha256(base / "package_manifest.json"),
            "source_text_changed": False,
            "renders_changed": False,
        },
        "prospective_changes": [
            "authority metadata added",
            "CAL-058-U01 language en->no",
            "cause-mapped scope/classification prompt",
            "provider-symmetric strength enum",
        ],
        "files": files,
    }
    (output_dir / "package_manifest.json").write_text(
        json.dumps(package_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    deterministic_zip(output_dir, output_zip)
    return {
        "output_dir": str(output_dir),
        "output_zip": str(output_zip),
        "zip_sha256": sha256(output_zip),
        "zip_bytes": output_zip.stat().st_size,
        "requests": len(requests),
        "units": len(units),
        "renders": package_manifest["render_pages"],
        "codes": 35,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-package", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output-zip", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build(args.base_package.resolve(), args.output_dir.resolve(), args.output_zip.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
