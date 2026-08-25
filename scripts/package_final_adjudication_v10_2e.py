#!/usr/bin/env python3
"""Create separate blinded reviewer packages for v10.2e adjudication."""

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
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def render_paths(payload: dict) -> list[str]:
    paths: set[str] = set()
    for section in ("candidates", "dual_empty_units", "contexts"):
        for record in payload.get(section, []):
            value = str(record.get("render_file", "")).strip().replace("\\", "/")
            if value:
                paths.add(value)
    return sorted(paths)


def deterministic_zip(root: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file in sorted(path for path in root.rglob("*") if path.is_file()):
            relative = file.relative_to(root).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(2026, 8, 25, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, file.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    tmp.replace(destination)


def readme(reviewer: str, candidate_count: int, empty_count: int, render_count: int) -> str:
    return f"""# CBDC v10.2e — blind final adjudication — {reviewer}

Open `FINAL_ADJUDICATION_v10_2e_{reviewer.upper()}.xlsx` and enter your initials in `Instructions!B3`.

Review:

1. all {candidate_count} rows on `Candidate Review`;
2. all {empty_count} rows on `Dual Empty Audit`;
3. `Empty Supplements` only when `missed_claims=yes`.

Only yellow cells are editable. Use the frozen `Codebook` and full text on `Contexts`. Page images, when needed, are under `renders/` ({render_count} files in this package). Do not compare your workbook with the other reviewer's workbook before both are complete.

Before returning the workbook, `QC Summary` must show zero pending, incomplete, and needs-context rows. Return the completed XLSX unchanged; do not rename sheets or columns.
"""


def build_one(
    reviewer: str,
    workbook_dir: Path,
    data_dir: Path,
    package_dir: Path,
    output_dir: Path,
) -> dict:
    lower = reviewer.lower()
    upper = reviewer.upper()
    payload_path = data_dir / f"payload_{lower}.json"
    workbook_path = workbook_dir / f"FINAL_ADJUDICATION_v10_2e_{upper}.xlsx"
    payload = json_load(payload_path)
    renders = render_paths(payload)

    if not workbook_path.is_file():
        raise FileNotFoundError(workbook_path)

    with tempfile.TemporaryDirectory(prefix=f"cbdc_v10_2e_{lower}_") as tmp_name:
        root = Path(tmp_name)
        shutil.copy2(workbook_path, root / workbook_path.name)
        render_root = root / "renders"
        for relative in renders:
            source = package_dir / relative
            if not source.is_file():
                raise FileNotFoundError(source)
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

        readme_path = root / "README_FOR_REVIEWER.md"
        readme_path.write_text(
            readme(reviewer, len(payload["candidates"]), len(payload["dual_empty_units"]), len(renders)),
            encoding="utf-8",
            newline="\n",
        )
        files = [path for path in root.rglob("*") if path.is_file()]
        manifest = {
            "schema": "cbdc-v10.2e-blind-reviewer-package-v1",
            "reviewer": reviewer,
            "candidate_rows": len(payload["candidates"]),
            "dual_empty_rows": len(payload["dual_empty_units"]),
            "render_files": len(renders),
            "blinding": payload["blinding"],
            "payload_sha256": sha256(payload_path),
            "files": [
                {
                    "path": path.relative_to(root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
                for path in sorted(files)
            ],
        }
        manifest_path = root / "BLIND_PACKAGE_MANIFEST.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

        output = output_dir / f"FINAL_ADJUDICATION_v10_2e_{upper}_BLIND.zip"
        deterministic_zip(root, output)

    external_manifest = {
        **manifest,
        "archive": {
            "path": output.name,
            "bytes": output.stat().st_size,
            "sha256": sha256(output),
        },
    }
    external_path = output.with_suffix(".manifest.json")
    external_path.write_text(json.dumps(external_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return external_manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workbook-dir", required=True, type=Path)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--package-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    manifests = [
        build_one(name, args.workbook_dir, args.data_dir, args.package_dir, args.output_dir)
        for name in ("Martin", "Dominik")
    ]
    print(json.dumps({
        "packages": [
            {
                "reviewer": item["reviewer"],
                "candidate_rows": item["candidate_rows"],
                "dual_empty_rows": item["dual_empty_rows"],
                "render_files": item["render_files"],
                **item["archive"],
            }
            for item in manifests
        ]
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
