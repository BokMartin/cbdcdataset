#!/usr/bin/env python3
"""Create separate blinded reviewer packages for the v10.2e validation sample."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def required_renders(payload: dict) -> list[str]:
    return sorted({
        str(row.get("render_file", "")).strip().replace("\\", "/")
        for section in ("candidates", "dual_empty_units", "contexts")
        for row in payload.get(section, [])
        if str(row.get("render_file", "")).strip()
    })


def deterministic_zip(root: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file in sorted(path for path in root.rglob("*") if path.is_file()):
            info = zipfile.ZipInfo(file.relative_to(root).as_posix(), date_time=(2026, 8, 25, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, file.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    temporary.replace(destination)


def reviewer_readme(reviewer: str, candidates: int, dual_empty: int, renders: int) -> str:
    return f"""# CBDC v10.2e — blind validation sample — {reviewer}

Open `VALIDATION_SAMPLE_v10_2e_{reviewer.upper()}.xlsx` and enter your initials in `Instructions!B3`.

Independently review all {candidates} rows on `Candidate Review` and all {dual_empty} rows on `Dual Empty Audit`. Use `Empty Supplements` only when `missed_claims=yes`. Only yellow cells are editable. Full context is in `Contexts`; {renders} required page renders are included under `renders/`.

Do not compare decisions with the other reviewer before both completed workbooks are returned and locked. `QC Summary` must show zero pending, incomplete, and needs-context rows. Return the XLSX without renaming sheets or columns.

This probability sample estimates candidate validity and coding agreement. It does not estimate full-production recall; recall is reported from the separately frozen calibration.
"""


def build(reviewer: str, workbook_dir: Path, data_dir: Path, source_package: Path, output_dir: Path) -> dict:
    lower = reviewer.lower()
    upper = reviewer.upper()
    payload_path = data_dir / f"payload_{lower}.json"
    workbook_path = workbook_dir / f"VALIDATION_SAMPLE_v10_2e_{upper}.xlsx"
    payload = load_json(payload_path)
    renders = required_renders(payload)
    if not workbook_path.is_file():
        raise FileNotFoundError(workbook_path)

    with tempfile.TemporaryDirectory(prefix=f"cbdc_v10_2e_sample_{lower}_") as temporary:
        root = Path(temporary)
        shutil.copy2(workbook_path, root / workbook_path.name)
        for relative in renders:
            source = source_package / relative
            if not source.is_file():
                raise FileNotFoundError(source)
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        (root / "README_FOR_REVIEWER.md").write_text(
            reviewer_readme(reviewer, len(payload["candidates"]), len(payload["dual_empty_units"]), len(renders)),
            encoding="utf-8",
            newline="\n",
        )
        files = sorted(path for path in root.rglob("*") if path.is_file())
        manifest = {
            "schema": "cbdc-v10.2e-blind-sampled-validation-package-v1",
            "reviewer": reviewer,
            "candidate_rows": len(payload["candidates"]),
            "dual_empty_rows": len(payload["dual_empty_units"]),
            "render_files": len(renders),
            "blinding": payload["blinding"],
            "payload_sha256": sha256(payload_path),
            "files": [
                {
                    "path": file.relative_to(root).as_posix(),
                    "bytes": file.stat().st_size,
                    "sha256": sha256(file),
                }
                for file in files
            ],
        }
        (root / "BLIND_PACKAGE_MANIFEST.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        archive = output_dir / f"VALIDATION_SAMPLE_v10_2e_{upper}_BLIND.zip"
        deterministic_zip(root, archive)

    external = {
        **manifest,
        "archive": {"path": archive.name, "bytes": archive.stat().st_size, "sha256": sha256(archive)},
    }
    archive.with_suffix(".manifest.json").write_text(
        json.dumps(external, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return external


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workbook-dir", required=True, type=Path)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--package-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifests = [
        build(reviewer, args.workbook_dir, args.data_dir, args.package_dir, args.output_dir)
        for reviewer in ("Martin", "Dominik")
    ]
    print(json.dumps({
        "packages": [
            {"reviewer": item["reviewer"], **item["archive"]}
            for item in manifests
        ]
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
