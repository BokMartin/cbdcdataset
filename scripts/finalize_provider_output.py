import argparse
import copy
import csv
import hashlib
import json
import unicodedata
from datetime import datetime, timezone
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_span(value):
    value = unicodedata.normalize("NFKC", str(value)).replace("\u00ad", "")
    value = value.replace("-\n", "")
    return "".join(value.split())


def jsonl(path):
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line
    ]


def write_jsonl(path, rows):
    Path(path).write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--responses", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--provider-rejections", type=Path)
    args = parser.parse_args()

    packaged = jsonl(args.package / "inputs.jsonl")
    expected = {
        unit["unit_id"]: unit
        for request in packaged
        for unit in request["units"]
    }
    responses = jsonl(args.responses)
    final = copy.deepcopy(responses)
    audit = []
    quote_en_corrections = 0
    unsupported_rejections = 0
    render_review_required = 0
    statements_before = 0
    statements_after = 0

    for response in final:
        for unit_result in response["units"]:
            unit = expected[unit_result["unit_id"]]
            kept = []
            for ordinal, statement in enumerate(unit_result["statements"], 1):
                statements_before += 1
                if unit["language"] == "en" and statement["quote_en"] is not None:
                    statement["quote_en"] = None
                    quote_en_corrections += 1
                    quote_en_action = "set_null_from_frozen_metadata"
                else:
                    quote_en_action = "unchanged"

                quote = normalized_span(statement["quote"])
                source = normalized_span(unit["source_text"])
                if quote and quote in source:
                    span_status = "text_verified"
                    kept.append(statement)
                elif unit.get("render_file"):
                    span_status = "render_review_required"
                    render_review_required += 1
                    kept.append(statement)
                else:
                    span_status = "rejected_unsupported_after_permitted_retry"
                    unsupported_rejections += 1

                audit.append({
                    "request_id": response["request_id"],
                    "unit_id": unit_result["unit_id"],
                    "doc_id": unit["doc_id"],
                    "page": unit["page"],
                    "statement_ordinal_before_filter": ordinal,
                    "code1": statement["code1"],
                    "quote_en_action": quote_en_action,
                    "span_status": span_status,
                    "quote": statement["quote"],
                })
            unit_result["statements"] = kept
            statements_after += len(kept)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output, final)
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    with args.audit.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(audit[0]))
        writer.writeheader()
        writer.writerows(audit)

    provider_rejections = None
    if args.provider_rejections:
        with args.provider_rejections.open(encoding="utf-8-sig", newline="") as handle:
            provider_rejections = sum(1 for _ in csv.DictReader(handle))

    manifest = {
        "schema": "cbdc_extraction_v10_1_provider_finalization",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "operation": "deterministic_contract_enforcement_after_provider_retry",
        "semantic_or_classification_changes": 0,
        "counts": {
            "requests": len(final),
            "units": sum(len(response["units"]) for response in final),
            "statements_before": statements_before,
            "statements_after": statements_after,
            "quote_en_set_null": quote_en_corrections,
            "unsupported_rejected": unsupported_rejections,
            "render_review_required": render_review_required,
            "provider_reported_rejections_before_finalization": provider_rejections,
        },
        "hashes": {
            "package_inputs_sha256": sha256(args.package / "inputs.jsonl"),
            "sealed_provider_responses_sha256": sha256(args.responses),
            "finalized_responses_sha256": sha256(args.output),
            "audit_sha256": sha256(args.audit),
            "provider_rejections_sha256": (
                sha256(args.provider_rejections) if args.provider_rejections else None
            ),
        },
        "rules": {
            "english_quote_en": "set null from frozen input language metadata",
            "text_span": "same normalized substring rule as extraction_v10_1.py",
            "unsupported_after_retry": "reject and count",
            "render_only": "retain but require separate visual verification",
        },
    }
    args.manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
