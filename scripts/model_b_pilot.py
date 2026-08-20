import argparse
import csv
import hashlib
import io
import json
import shutil
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "validation" / "model_b_pilot"
SAMPLE = ROOT / "validation" / "sample.csv"
DOC_HASHES = ROOT / "validation" / "doc_hashes.csv"
PROMPT = SPEC / "prompt_v9.txt"
PROTOCOL = SPEC / "protocol.json"
SCHEMA = SPEC / "output_schema.json"
TASK = SPEC / "BLIND_TASK.md"
EXCLUDED_STRATUM = "reserve_sealed"
EXPECTED_PAGES = 78
EXPECTED_DOCUMENTS = 42
MIN_CHARS = 250
MAX_CHARS = 9000
RESPONSE_FIELDS = {
    "quote",
    "quote_en",
    "code1",
    "odr",
    "privacy_direction",
    "privacy_relation",
    "strength",
}


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def package_files(output):
    return [
        output / "BLIND_TASK.md",
        output / "protocol.json",
        output / "output_schema.json",
        output / "input_manifest.csv",
        *sorted((output / "prompts").glob("B*.txt")),
    ]


def prepare(corpus, output):
    sample = [r for r in read_csv(SAMPLE) if r["stratum"] != EXCLUDED_STRATUM]
    if len(sample) != EXPECTED_PAGES:
        raise ValueError(f"Expected {EXPECTED_PAGES} pages, found {len(sample)}")
    if len({(r["doc_id"], r["page"]) for r in sample}) != len(sample):
        raise ValueError("Duplicate (doc_id, page) in pilot sample")
    if len({r["fname"] for r in sample}) != EXPECTED_DOCUMENTS:
        raise ValueError("Unexpected number of source documents")

    hash_rows = {r["fname"]: r for r in read_csv(DOC_HASHES)}
    template = PROMPT.read_text(encoding="utf-8")
    if not template.endswith("\n"):
        raise ValueError("Prompt must end with a newline")

    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing package: {output}")
    (output / "prompts").mkdir(parents=True)
    for source in (TASK, PROTOCOL, SCHEMA):
        shutil.copyfile(source, output / source.name)

    with zipfile.ZipFile(corpus) as archive:
        members = defaultdict(list)
        for name in archive.namelist():
            if name.lower().endswith(".pdf"):
                members[Path(name).name].append(name)

        pdfs = {}
        pdf_hashes = {}
        for fname in sorted({r["fname"] for r in sample}):
            if fname not in hash_rows:
                raise ValueError(f"Missing frozen hash for {fname}")
            if len(members[fname]) != 1:
                raise ValueError(f"Expected one archive member for {fname}, found {members[fname]}")
            data = archive.read(members[fname][0])
            actual = sha256_bytes(data)
            expected = hash_rows[fname]["sha256"]
            if actual != expected:
                raise ValueError(f"PDF hash mismatch for {fname}: {actual} != {expected}")
            pdf_hashes[fname] = actual
            pdfs[fname] = PdfReader(io.BytesIO(data))

        rows = []
        for index, source in enumerate(sample, 1):
            input_id = f"B{index:03d}"
            page = int(source["page"])
            reader = pdfs[source["fname"]]
            if page < 1 or page > len(reader.pages):
                raise ValueError(f"Page out of range: {source['doc_id']} p.{page}")
            text = (reader.pages[page - 1].extract_text() or "").strip()
            full_text_hash = sha256_bytes(text.encode("utf-8"))
            status = "ready" if len(text) >= MIN_CHARS else "skipped_lt250"
            prompt_chars = min(len(text), MAX_CHARS) if status == "ready" else 0
            prompt_hash = ""
            prompt_name = ""
            if status == "ready":
                prompt_text = (
                    template.replace("<<DOC_ID>>", source["doc_id"])
                    .replace("<<PAGE>>", str(page))
                    + text[:MAX_CHARS]
                )
                prompt_name = f"prompts/{input_id}.txt"
                prompt_path = output / prompt_name
                prompt_path.write_text(prompt_text, encoding="utf-8", newline="\n")
                prompt_hash = sha256_file(prompt_path)
            rows.append(
                {
                    "input_id": input_id,
                    "status": status,
                    "doc_id": source["doc_id"],
                    "page": page,
                    "stratum": source["stratum"],
                    "language": source["language"],
                    "source_pdf_sha256": pdf_hashes[source["fname"]],
                    "extracted_chars": len(text),
                    "full_text_sha256": full_text_hash,
                    "prompt_chars_from_page": prompt_chars,
                    "prompt_file": prompt_name,
                    "prompt_sha256": prompt_hash,
                }
            )

    audit_fields = [
        "input_id",
        "status",
        "doc_id",
        "page",
        "stratum",
        "language",
        "source_pdf_sha256",
        "extracted_chars",
        "full_text_sha256",
        "prompt_chars_from_page",
        "prompt_file",
        "prompt_sha256",
    ]
    write_csv(output / "audit_manifest.csv", rows, audit_fields)
    blind_fields = ["input_id", "status", "prompt_file", "prompt_sha256"]
    write_csv(
        output / "input_manifest.csv",
        [{field: row[field] for field in blind_fields} for row in rows],
        blind_fields,
    )

    counts = Counter(r["status"] for r in rows)
    inventory = []
    for path in package_files(output):
        inventory.append(
            {
                "path": path.relative_to(output).as_posix(),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    package_manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_corpus": corpus.name,
        "source_corpus_sha256": sha256_file(corpus),
        "page_count": len(rows),
        "document_count": len({r["doc_id"] for r in rows}),
        "ready_count": counts["ready"],
        "skipped_lt250_count": counts["skipped_lt250"],
        "files": inventory,
    }
    manifest_path = output / "package_manifest.json"
    manifest_path.write_text(
        json.dumps(package_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    archive_path = output.with_suffix(".zip")
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in [*package_files(output), manifest_path]:
            archive.write(path, path.relative_to(output).as_posix())
    print(
        json.dumps(
            {
                "package": str(output),
                "archive": str(archive_path),
                "archive_sha256": sha256_file(archive_path),
                "pages": len(rows),
                "ready": counts["ready"],
                "skipped_lt250": counts["skipped_lt250"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def validate(output):
    manifest_path = output / "package_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = read_csv(output / "input_manifest.csv")
    errors = []
    if len(rows) != EXPECTED_PAGES:
        errors.append(f"manifest rows: {len(rows)}")
    if set(rows[0]) != {"input_id", "status", "prompt_file", "prompt_sha256"}:
        errors.append("blind manifest exposes unexpected fields")
    if Counter(r["status"] for r in rows) != Counter({"ready": 70, "skipped_lt250": 8}):
        errors.append(f"unexpected statuses: {Counter(r['status'] for r in rows)}")
    if manifest.get("document_count") != EXPECTED_DOCUMENTS:
        errors.append(f"unexpected source document count: {manifest.get('document_count')}")
    expected_ids = [f"B{i:03d}" for i in range(1, EXPECTED_PAGES + 1)]
    if [r["input_id"] for r in rows] != expected_ids:
        errors.append("input IDs are not complete and ordered")
    for item in manifest["files"]:
        path = output / item["path"]
        if not path.is_file() or sha256_file(path) != item["sha256"]:
            errors.append(f"file hash mismatch: {item['path']}")
    for row in rows:
        prompt_file = row["prompt_file"]
        if row["status"] == "ready":
            path = output / prompt_file
            if not path.is_file() or sha256_file(path) != row["prompt_sha256"]:
                errors.append(f"prompt mismatch: {row['input_id']}")
        elif prompt_file or row["prompt_sha256"]:
            errors.append(f"skipped row has prompt content: {row['input_id']}")
    forbidden_names = {"responses.jsonl", "run_metadata.json"}
    present = {p.name for p in output.rglob("*") if p.is_file()}
    if forbidden_names & present:
        errors.append("package contains model output files")
    if errors:
        raise ValueError("; ".join(errors))
    print(
        json.dumps(
            {
                "valid": True,
                "page_count": len(rows),
                "ready_count": 70,
                "skipped_lt250_count": 8,
                "package_manifest_sha256": sha256_file(manifest_path),
            },
            indent=2,
        )
    )


def validate_responses(output):
    manifest_rows = read_csv(output / "input_manifest.csv")
    response_path = output / "responses.jsonl"
    metadata_path = output / "run_metadata.json"
    if not response_path.is_file() or not metadata_path.is_file():
        raise ValueError("responses.jsonl and run_metadata.json are required")
    responses = []
    with response_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                try:
                    responses.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSON on response line {line_number}: {exc}") from exc
    if len(responses) != len(manifest_rows):
        raise ValueError(f"Expected {len(manifest_rows)} responses, found {len(responses)}")

    allowed_codes = set(json.loads(SCHEMA.read_text(encoding="utf-8"))["items"]["properties"]["code1"]["enum"])
    expected_odr = {"decision", "proposal"}
    expected_direction = {"increases", "decreases", "conditional", "neutral"}
    expected_relation = {
        "from_state",
        "from_intermediary",
        "from_counterparty",
        "not_applicable",
    }
    statement_count = 0
    quote_word_limit_violations = 0
    for source, record in zip(manifest_rows, responses):
        if set(record) != {"input_id", "status", "response"}:
            raise ValueError(f"Unexpected record fields for {source['input_id']}")
        if record["input_id"] != source["input_id"]:
            raise ValueError(f"Out-of-order response at {source['input_id']}")
        expected_status = "ok" if source["status"] == "ready" else source["status"]
        if record["status"] != expected_status:
            raise ValueError(f"Status mismatch for {source['input_id']}")
        if source["status"] == "skipped_lt250":
            if record["response"] is not None:
                raise ValueError(f"Skipped input has a response: {source['input_id']}")
            continue
        if not isinstance(record["response"], list):
            raise ValueError(f"Response is not an array: {source['input_id']}")
        for item_number, item in enumerate(record["response"], 1):
            label = f"{source['input_id']} item {item_number}"
            if not isinstance(item, dict) or set(item) != RESPONSE_FIELDS:
                raise ValueError(f"Invalid fields: {label}")
            if not isinstance(item["quote"], str) or not item["quote"].strip():
                raise ValueError(f"Empty quote: {label}")
            if len(item["quote"].split()) > 45:
                quote_word_limit_violations += 1
            if not isinstance(item["quote_en"], str) or not item["quote_en"].strip():
                raise ValueError(f"Empty quote_en: {label}")
            if item["code1"] not in allowed_codes:
                raise ValueError(f"Invalid code1: {label}")
            if item["odr"] not in expected_odr:
                raise ValueError(f"Invalid odr: {label}")
            if item["privacy_direction"] not in expected_direction:
                raise ValueError(f"Invalid privacy_direction: {label}")
            if item["privacy_relation"] not in expected_relation:
                raise ValueError(f"Invalid privacy_relation: {label}")
            if type(item["strength"]) is not int or item["strength"] not in {1, 2, 3}:
                raise ValueError(f"Invalid strength: {label}")
            statement_count += 1

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    required_metadata = set(json.loads(PROTOCOL.read_text(encoding="utf-8"))["run_metadata_required"])
    missing = sorted(field for field in required_metadata if not metadata.get(field))
    if missing:
        raise ValueError(f"Missing run metadata: {', '.join(missing)}")
    print(
        json.dumps(
            {
                "valid": True,
                "response_records": len(responses),
                "ready_records": sum(r["status"] == "ready" for r in manifest_rows),
                "skipped_records": sum(r["status"] == "skipped_lt250" for r in manifest_rows),
                "extracted_statements": statement_count,
                "quote_word_limit_violations": quote_word_limit_violations,
                "responses_sha256": sha256_file(response_path),
                "run_metadata_sha256": sha256_file(metadata_path),
            },
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--corpus", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True)
    check = sub.add_parser("validate")
    check.add_argument("--package", type=Path, required=True)
    responses = sub.add_parser("validate-responses")
    responses.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare(args.corpus.resolve(), args.output.resolve())
        elif args.command == "validate":
            validate(args.package.resolve())
        else:
            validate_responses(args.package.resolve())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
