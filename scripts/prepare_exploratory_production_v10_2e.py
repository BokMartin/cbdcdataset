#!/usr/bin/env python3
"""Build the frozen v10.2e exploratory full-corpus extraction package."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import importlib.metadata
import json
import math
import platform
import shutil
import zipfile
from pathlib import Path

import PIL
import pypdf
import pypdfium2
from PIL import Image
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "validation" / "extraction_v10_2_exploratory"
BASE_SPEC = ROOT / "validation" / "extraction_v10_2"
FIXED_ZIP_TIME = (2026, 8, 25, 0, 0, 0)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def estimated_tokens(text: str, language: str) -> int:
    chars_per_token = 2.0 if language in {"zh", "ja", "ko"} else 4.0
    return max(1, math.ceil(len(text) / chars_per_token))


def chunk_text(text: str, language: str, target_tokens: int, overlap_tokens: int):
    if not text:
        return [(0, 0, "")]
    ratio = 2 if language in {"zh", "ja", "ko"} else 4
    target = target_tokens * ratio
    overlap = overlap_tokens * ratio
    chunks = []
    start = 0
    while start < len(text):
        tentative = min(len(text), start + target)
        end = tentative
        if tentative < len(text):
            floor = start + int(target * 0.80)
            end = max(text.rfind("\n", floor, tentative), text.rfind(" ", floor, tentative))
            if end <= start:
                end = tentative
        chunks.append((start, end, text[start:end]))
        if end >= len(text):
            break
        next_start = max(start + 1, end - overlap)
        while next_start > start and next_start < len(text) and not text[next_start - 1].isspace():
            next_start -= 1
        start = next_start if next_start > start else end
    return chunks


def jurisdiction(doc_id: str) -> str:
    return doc_id.split("_", 1)[0]


def authority_rows(documents: list[dict]) -> list[dict]:
    owners = read_json(SPEC / "owner_by_jurisdiction.json")
    production_overrides = read_json(SPEC / "document_authority_overrides.json")
    calibration_rules = read_json(BASE_SPEC / "authority_overrides.json")["document_defaults"]
    rows = []
    for document in documents:
        doc_id = document["doc_id"]
        rule = production_overrides.get(doc_id) or calibration_rules.get(doc_id)
        if rule:
            owner = rule["project_owner"]
            note = rule["authority_note"]
        else:
            jur = jurisdiction(doc_id)
            if jur not in owners:
                raise KeyError(f"No owner rule for {doc_id}")
            owner = owners[jur]
            if document["source_type"] == "pseudo_official":
                note = (
                    "Research or joint-project source: retain only executed own-project findings or concrete "
                    "CBDC conclusions explicitly attributed to the named authority. Exclude author assumptions, "
                    "literature, external examples, and unadopted proposals."
                )
            elif document["scope"] == "framework":
                note = (
                    "Framework source: retain only a concrete CBDC decision, requirement, prohibition, or position "
                    "of the named authority. Exclude generic framework text, literature, and foreign examples."
                )
            else:
                note = (
                    "Retain the named authority's own CBDC decisions, explicit proposals, requirements, features, "
                    "and executed findings. Exclude generic context, literature, foreign projects, and stakeholder "
                    "views not explicitly adopted by the authority."
                )
        rows.append({
            "doc_id": doc_id,
            "project_owner": owner,
            "authority_note": note,
            "authority_rule": (
                "production_override" if doc_id in production_overrides
                else "calibration_rule" if doc_id in calibration_rules
                else "jurisdiction_default"
            ),
        })
    if len(rows) != len(documents) or len({row["doc_id"] for row in rows}) != len(rows):
        raise ValueError("Authority coverage is incomplete or duplicated")
    return rows


def render_page(pdf: pypdfium2.PdfDocument, page_index: int, scale: float) -> bytes:
    bitmap = pdf[page_index].render(scale=scale)
    image = bitmap.to_pil().convert("L")
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=85, optimize=True, progressive=False)
    return output.getvalue()


def deterministic_zip(source: Path, target: Path) -> None:
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(item for item in source.rglob("*") if item.is_file()):
            info = zipfile.ZipInfo(path.relative_to(source).as_posix(), date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def build(corpus_zip: Path, output_dir: Path, output_zip: Path) -> dict:
    if output_dir.exists():
        raise FileExistsError(output_dir)
    output_dir.mkdir(parents=True)
    (output_dir / "renders").mkdir()

    config = read_json(SPEC / "run_config.production.json")
    documents = read_csv(ROOT / "data" / "documents.csv")
    old_hashes = {row["fname"]: row for row in read_csv(ROOT / "validation" / "doc_hashes.csv")}
    page_rows = read_csv(ROOT / "validation" / "page_manifest.csv")
    pages = {(row["doc_id"], int(row["page"])): row for row in page_rows}
    if len(documents) != 113 or len(pages) != 3963:
        raise ValueError("Expected 113 documents and 3,963 unique pages")

    authority = authority_rows(documents)
    authority_by_doc = {row["doc_id"]: row for row in authority}
    write_csv(
        output_dir / "source_authority.csv",
        ["doc_id", "project_owner", "authority_note", "authority_rule"],
        authority,
    )

    units = []
    input_manifest = []
    corpus_manifest = []
    render_pages = 0
    with zipfile.ZipFile(corpus_zip) as archive:
        members = {item.filename: item for item in archive.infolist() if not item.is_dir()}
        package_manifest_entry = members.get("MANIFEST.csv")
        if package_manifest_entry is None:
            raise FileNotFoundError("Corpus MANIFEST.csv")
        archive_manifest = list(
            csv.DictReader(io.StringIO(archive.read(package_manifest_entry).decode("utf-8-sig")))
        )
        archive_by_filename = {row["fname"]: row for row in archive_manifest}
        if len(archive_by_filename) != len(archive_manifest):
            raise ValueError("Duplicate filename in corpus MANIFEST.csv")
        for doc_ordinal, document in enumerate(documents, 1):
            doc_id = document["doc_id"]
            source = archive_by_filename.get(document["path"])
            if not source or source["folder"] == "reference":
                raise FileNotFoundError(f"Included corpus document missing: {doc_id}")
            member_name = f"{source['folder']}/{source['fname']}"
            member = members.get(member_name)
            if member is None:
                raise FileNotFoundError(member_name)
            pdf_bytes = archive.read(member)
            pdf_hash = sha256_bytes(pdf_bytes)
            frozen = old_hashes.get(document["path"])
            if not frozen or pdf_hash != frozen["sha256"] or len(pdf_bytes) != int(frozen["bytes"]):
                raise ValueError(f"Frozen PDF mismatch: {doc_id}")
            reader = PdfReader(io.BytesIO(pdf_bytes))
            expected_pages = int(document["pages"])
            if len(reader.pages) != expected_pages:
                raise ValueError(f"Page-count mismatch: {doc_id}")
            pdfium = pypdfium2.PdfDocument(pdf_bytes)
            corpus_manifest.append({
                "doc_order": doc_ordinal,
                "doc_id": doc_id,
                "source_manifest_doc_id": source["doc_id"],
                "filename": document["path"],
                "archive_member": member_name,
                "sha256": pdf_hash,
                "bytes": len(pdf_bytes),
                "pages": expected_pages,
                "source_manifest_pages": int(source["pages"]),
                "source_manifest_page_count_matches": str(int(source["pages"]) == expected_pages).lower(),
                "source_type": document["source_type"],
                "prior_extraction_status": document["extraction_status"],
                "scope": document["scope"],
                "language": document["language"],
                "included": "true",
            })
            try:
                for page_number, page in enumerate(reader.pages, 1):
                    frozen_page = pages.get((doc_id, page_number))
                    if frozen_page is None:
                        raise KeyError(f"Missing frozen page policy: {doc_id}:{page_number}")
                    text = (page.extract_text() or "").strip()
                    needs_render = frozen_page["ocr_needed"].strip().lower() == "true"
                    render_file = ""
                    render_hash = ""
                    if needs_render:
                        render_name = f"PRD-{doc_ordinal:04d}-P{page_number:04d}.jpg"
                        render_data = render_page(pdfium, page_number - 1, config["input"]["render_scale"])
                        render_path = output_dir / "renders" / render_name
                        render_path.write_bytes(render_data)
                        render_file = f"renders/{render_name}"
                        render_hash = sha256_bytes(render_data)
                        render_pages += 1
                    source_mode = "text_and_render" if render_file and text else "render" if render_file else "text"
                    chunks = chunk_text(
                        text,
                        document["language"],
                        config["input"]["target_text_tokens_per_unit"],
                        config["input"]["overlap_text_tokens"],
                    )
                    for chunk_number, (start, end, chunk) in enumerate(chunks, 1):
                        unit_id = f"PRD-{doc_ordinal:04d}-P{page_number:04d}-U{chunk_number:02d}"
                        block_id = f"{doc_id}-P{page_number:04d}-B{chunk_number:02d}"
                        unit = {
                            "unit_id": unit_id,
                            "block_id": block_id,
                            "doc_id": doc_id,
                            "page": page_number,
                            "language": document["language"],
                            "project_owner": authority_by_doc[doc_id]["project_owner"],
                            "authority_note": authority_by_doc[doc_id]["authority_note"],
                            "source_mode": source_mode,
                            "chunk_start": start,
                            "chunk_end": end,
                            "source_text": chunk,
                            "render_file": render_file or None,
                        }
                        units.append(unit)
                        input_manifest.append({
                            "unit_order": len(units),
                            "unit_id": unit_id,
                            "block_id": block_id,
                            "doc_id": doc_id,
                            "page": page_number,
                            "chunk": chunk_number,
                            "language": document["language"],
                            "source_mode": source_mode,
                            "chunk_start": start,
                            "chunk_end": end,
                            "characters": len(chunk),
                            "estimated_source_tokens": estimated_tokens(chunk, document["language"]),
                            "source_text_sha256": sha256_bytes(chunk.encode("utf-8")),
                            "pdf_sha256": pdf_hash,
                            "render_file": render_file,
                            "render_sha256": render_hash,
                            "render_policy": "frozen_page_manifest_ocr_needed" if needs_render else "none",
                        })
            finally:
                pdfium.close()

    if render_pages != 345:
        raise ValueError(f"Expected 345 render pages, got {render_pages}")

    requests = []
    current = []
    current_tokens = 0
    max_units = config["input"]["max_units_per_request"]
    max_tokens = config["input"]["max_source_tokens_per_request"]
    for unit in units:
        tokens = estimated_tokens(unit["source_text"], unit["language"])
        if current and (len(current) >= max_units or current_tokens + tokens > max_tokens):
            requests.append(current)
            current = []
            current_tokens = 0
        current.append(unit)
        current_tokens += tokens
    if current:
        requests.append(current)

    inputs_path = output_dir / "inputs.jsonl"
    with inputs_path.open("w", encoding="utf-8", newline="\n") as handle:
        for request_number, request_units in enumerate(requests, 1):
            handle.write(canonical_json({
                "request_id": f"PRD-R{request_number:05d}",
                "units": request_units,
            }) + "\n")

    write_csv(output_dir / "corpus_manifest.csv", list(corpus_manifest[0]), corpus_manifest)
    write_csv(output_dir / "input_manifest.csv", list(input_manifest[0]), input_manifest)
    shutil.copyfile(BASE_SPEC / "PROMPT_CORE.md", output_dir / "PROMPT_CORE.md")
    shutil.copyfile(BASE_SPEC / "output_schema.json", output_dir / "output_schema.json")
    shutil.copyfile(ROOT / "data" / "codebook.csv", output_dir / "codebook.csv")
    for name in ["PROTOCOL_AMENDMENT.md", "run_config.production.json", "TASK_CLAUDE.md", "TASK_CODEX.md"]:
        shutil.copyfile(SPEC / name, output_dir / name)

    package_files = []
    for path in sorted(item for item in output_dir.rglob("*") if item.is_file()):
        package_files.append({
            "file": path.relative_to(output_dir).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        })
    package_manifest = {
        "schema": "cbdc_extraction_v10_2e_exploratory_input_package",
        "status": "frozen_for_independent_openai_and_claude_candidate_generation",
        "claim": config["claim"],
        "calibration_gate_passed": False,
        "reserve_status": "sealed_not_present",
        "source_corpus": {
            "archive_filename": corpus_zip.name,
            "archive_bytes": corpus_zip.stat().st_size,
            "archive_sha256": sha256(corpus_zip),
            "reference_only_documents_excluded": 1,
        },
        "counts": {
            "documents": len(corpus_manifest),
            "pages": sum(int(row["pages"]) for row in corpus_manifest),
            "units": len(units),
            "requests": len(requests),
            "render_pages": render_pages,
        },
        "software": {
            "python": platform.python_version(),
            "pypdf": pypdf.__version__,
            "pypdfium2": importlib.metadata.version("pypdfium2"),
            "pillow": PIL.__version__,
        },
        "files": package_files,
    }
    write_json(output_dir / "package_manifest.json", package_manifest)
    deterministic_zip(output_dir, output_zip)
    result = {
        "output_dir": str(output_dir),
        "output_zip": str(output_zip),
        "output_zip_bytes": output_zip.stat().st_size,
        "output_zip_sha256": sha256(output_zip),
        "package_manifest_sha256": sha256(output_dir / "package_manifest.json"),
        **package_manifest["counts"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output-zip", type=Path, required=True)
    args = parser.parse_args()
    build(args.corpus.resolve(), args.output_dir.resolve(), args.output_zip.resolve())


if __name__ == "__main__":
    main()
