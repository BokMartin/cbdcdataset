#!/usr/bin/env python3
"""Seal provider-prefilled reviewer-format workbooks outside Git."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path


FILES = [
    "VALIDATION_SAMPLE_v10_2e_OPENAI_PREFILLED_SEALED.xlsx",
    "VALIDATION_SAMPLE_v10_2e_CLAUDE_PREFILLED_SEALED.xlsx",
    "AI_REVIEWER_WORKBOOK_MANIFEST.json",
    "AI_REVIEWER_WORKBOOK_INDEPENDENT_VERIFICATION.json",
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
    parser.add_argument("--workbook-dir", required=True, type=Path)
    parser.add_argument("--seal-dir", required=True, type=Path)
    args = parser.parse_args()
    args.seal_dir.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        if not (args.workbook_dir / name).is_file():
            raise FileNotFoundError(args.workbook_dir / name)
    manifest = json.loads((args.workbook_dir / "AI_REVIEWER_WORKBOOK_MANIFEST.json").read_text(encoding="utf-8"))
    verification = json.loads((args.workbook_dir / "AI_REVIEWER_WORKBOOK_INDEPENDENT_VERIFICATION.json").read_text(encoding="utf-8"))
    if not verification.get("passed"):
        raise ValueError("independent verification did not pass")

    warning = """# Sealed provider workbooks

Do not open before both independent human workbooks are returned and hash-locked.

These workbooks mirror the human-review layout, but `keep` means the provider emitted the candidate and `exclude/not_extracted_by_provider` means it did not. Neither value is a human judgment of substantive validity. Provider confidence was not reported. In dual-empty rows, `no` records zero emitted candidates and does not assert that the source contains no eligible claim.
"""
    with tempfile.TemporaryDirectory(prefix="cbdc_v10_2e_ai_reviewer_") as temporary:
        root = Path(temporary)
        for name in FILES:
            (root / name).write_bytes((args.workbook_dir / name).read_bytes())
        (root / "DO_NOT_OPEN_BEFORE_LOCK.md").write_text(warning, encoding="utf-8", newline="\n")
        archive = args.workbook_dir / "AI_REVIEWER_FORMAT_v10_2e_SEALED.zip"
        deterministic_zip(root, archive)

    seal = {
        "schema": "cbdc-v10.2e-ai-reviewer-format-public-seal-v1",
        "status": "plaintext withheld until both blind human-review workbooks are returned and hash-locked",
        "verification_passed": True,
        "semantics": manifest["semantics"],
        "disagreement_counts": manifest["disagreement"],
        "files": [
            {"name": name, "bytes": (args.workbook_dir / name).stat().st_size, "sha256": sha256(args.workbook_dir / name)}
            for name in FILES
        ],
        "archive": {"name": archive.name, "bytes": archive.stat().st_size, "sha256": sha256(archive)},
    }
    (args.seal_dir / "AI_REVIEWER_FORMAT_SEAL_MANIFEST.json").write_text(
        json.dumps(seal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(seal, ensure_ascii=False))


if __name__ == "__main__":
    main()
