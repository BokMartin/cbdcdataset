#!/usr/bin/env python3
"""Seal unblinded AI masters outside Git and publish only their hash manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path


FILES = [
    "AI_CANDIDATE_MASTER_v10_2e_FULL_SEALED.xlsx",
    "AI_CANDIDATE_MASTER_v10_2e_MARTIN_SAMPLE_SEALED.xlsx",
    "AI_CANDIDATE_MASTER_v10_2e_DOMINIK_SAMPLE_SEALED.xlsx",
    "AI_MASTER_WORKBOOK_MANIFEST.json",
    "AI_MASTER_INDEPENDENT_VERIFICATION.json",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def deterministic_zip(root: Path, destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file in sorted(path for path in root.iterdir() if path.is_file()):
            info = zipfile.ZipInfo(file.name, date_time=(2026, 8, 25, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, file.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    temporary.replace(destination)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-dir", required=True, type=Path)
    parser.add_argument("--seal-dir", required=True, type=Path)
    args = parser.parse_args()
    args.seal_dir.mkdir(parents=True, exist_ok=True)

    workbook_manifest = json.loads((args.master_dir / "AI_MASTER_WORKBOOK_MANIFEST.json").read_text(encoding="utf-8"))
    verification = json.loads((args.master_dir / "AI_MASTER_INDEPENDENT_VERIFICATION.json").read_text(encoding="utf-8"))
    if not verification.get("passed"):
        raise ValueError("independent workbook verification did not pass")
    for name in FILES:
        if not (args.master_dir / name).is_file():
            raise FileNotFoundError(args.master_dir / name)

    warning = """# Sealed AI candidate masters

Do not open these files or their previews until both independent human-review workbooks have been returned and hash-locked. The Martin and Dominik sample masters are identical except for the reviewer label and are answer keys, not reviewer inputs.

After the lock, join `sample_case_id` to the blind workbooks, calculate pre-consensus human agreement and human-to-provider agreement, and adjudicate disagreements only. The candidate sample estimates validity and coding agreement; it does not estimate full-production recall.
"""
    with tempfile.TemporaryDirectory(prefix="cbdc_v10_2e_ai_masters_") as temporary:
        root = Path(temporary)
        for name in FILES:
            (root / name).write_bytes((args.master_dir / name).read_bytes())
        (root / "DO_NOT_OPEN_BEFORE_LOCK.md").write_text(warning, encoding="utf-8", newline="\n")
        archive = args.master_dir / "AI_MASTERS_v10_2e_SEALED.zip"
        deterministic_zip(root, archive)

    seal = {
        "schema": "cbdc-v10.2e-ai-master-public-seal-v1",
        "status": "plaintext withheld until both blind human-review workbooks are returned and hash-locked",
        "verification_passed": True,
        "counts": {
            "full_candidates": workbook_manifest["workbooks"][0]["candidates"],
            "full_provider_statements": workbook_manifest["workbooks"][0]["provider_statements"],
            "sample_candidates_each": workbook_manifest["workbooks"][1]["candidates"],
            "sample_provider_statements_each": workbook_manifest["workbooks"][1]["provider_statements"],
            "dual_empty_units_each": workbook_manifest["workbooks"][1]["dual_empty"],
        },
        "files": [
            {"name": name, "bytes": (args.master_dir / name).stat().st_size, "sha256": sha256(args.master_dir / name)}
            for name in FILES
        ],
        "archive": {"name": archive.name, "bytes": archive.stat().st_size, "sha256": sha256(archive)},
    }
    (args.seal_dir / "AI_MASTER_SEAL_MANIFEST.json").write_text(
        json.dumps(seal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(seal, ensure_ascii=False))


if __name__ == "__main__":
    main()
