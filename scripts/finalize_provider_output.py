import argparse
import copy
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_span(value):
    return "".join(str(value).split())


def normalized_with_map(value):
    characters = []
    offsets = []
    for offset, character in enumerate(str(value)):
        if not character.isspace():
            characters.append(character)
            offsets.append(offset)
    return "".join(characters), offsets


def occurrences(haystack, needle):
    found = []
    offset = 0
    while needle:
        offset = haystack.find(needle, offset)
        if offset < 0:
            break
        found.append(offset)
        offset += 1
    return found


def jsonl(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


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
    block_id_corrections = 0
    unsupported_rejections = 0
    render_review_required = 0
    whitespace_restored = 0
    normalized_ambiguous = 0
    statements_before = 0
    statements_after = 0

    for response in final:
        for unit_result in response["units"]:
            unit = expected[unit_result["unit_id"]]
            kept = []
            for ordinal, statement in enumerate(unit_result["statements"], 1):
                statements_before += 1
                provider_block_id = statement["block_id"]
                if provider_block_id != unit["block_id"]:
                    statement["block_id"] = unit["block_id"]
                    block_id_corrections += 1
                    block_id_action = "set_from_frozen_unit_metadata"
                else:
                    block_id_action = "unchanged"
                if unit["language"] == "en" and statement["quote_en"] is not None:
                    statement["quote_en"] = None
                    quote_en_corrections += 1
                    quote_en_action = "set_null_from_frozen_metadata"
                else:
                    quote_en_action = "unchanged"

                provider_quote = statement["quote"]
                source_text = unit["source_text"]
                source_start = -1
                source_end = -1
                match_count = 0
                if provider_quote and provider_quote in source_text:
                    span_status = "text_verified"
                    match_method = "exact"
                    exact_starts = occurrences(source_text, provider_quote)
                    match_count = len(exact_starts)
                    source_start = exact_starts[0]
                    source_end = source_start + len(provider_quote)
                    kept.append(statement)
                elif provider_quote:
                    normalized_quote = normalized_span(provider_quote)
                    normalized_source, offsets = normalized_with_map(source_text)
                    starts = occurrences(normalized_source, normalized_quote)
                    match_count = len(starts)
                    if len(starts) == 1:
                        start = offsets[starts[0]]
                        end = offsets[starts[0] + len(normalized_quote) - 1] + 1
                        statement["quote"] = source_text[start:end]
                        span_status = "whitespace_restored"
                        match_method = "whitespace_stripped_unique"
                        source_start = start
                        source_end = end
                        whitespace_restored += 1
                        kept.append(statement)
                    elif len(starts) > 1:
                        span_status = "normalized_ambiguous"
                        match_method = "whitespace_stripped_ambiguous"
                        normalized_ambiguous += 1
                        kept.append(statement)
                    elif unit.get("render_file"):
                        span_status = "render_review_required"
                        match_method = "render_pending"
                        render_review_required += 1
                        kept.append(statement)
                    else:
                        span_status = "rejected_unsupported_after_permitted_retry"
                        match_method = "unsupported"
                        unsupported_rejections += 1
                elif unit.get("render_file"):
                    span_status = "render_review_required"
                    match_method = "render_pending"
                    render_review_required += 1
                    kept.append(statement)
                else:
                    span_status = "rejected_unsupported_after_permitted_retry"
                    match_method = "unsupported"
                    unsupported_rejections += 1

                audit.append({
                    "request_id": response["request_id"],
                    "unit_id": unit_result["unit_id"],
                    "doc_id": unit["doc_id"],
                    "page": unit["page"],
                    "statement_ordinal_before_filter": ordinal,
                    "code1": statement["code1"],
                    "provider_block_id": provider_block_id,
                    "final_block_id": statement["block_id"],
                    "block_id_action": block_id_action,
                    "quote_en_action": quote_en_action,
                    "span_status": span_status,
                    "match_method": match_method,
                    "match_count": match_count,
                    "source_start": source_start,
                    "source_end": source_end,
                    "provider_quote_sha256": hashlib.sha256(
                        provider_quote.encode("utf-8")
                    ).hexdigest(),
                    "final_quote_sha256": hashlib.sha256(
                        statement["quote"].encode("utf-8")
                    ).hexdigest(),
                })
            unit_result["statements"] = kept
            statements_after += len(kept)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output, final)
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    with args.audit.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(audit[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(audit)

    provider_rejections = None
    if args.provider_rejections:
        with args.provider_rejections.open(encoding="utf-8-sig", newline="") as handle:
            provider_rejections = sum(1 for _ in csv.DictReader(handle))

    manifest = {
        "schema": "cbdc_extraction_provider_finalization_v2",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "operation": "deterministic_contract_enforcement_after_provider_retry",
        "semantic_or_classification_changes": 0,
        "counts": {
            "requests": len(final),
            "units": sum(len(response["units"]) for response in final),
            "statements_before": statements_before,
            "statements_after": statements_after,
            "quote_en_set_null": quote_en_corrections,
            "block_id_set_from_frozen_unit": block_id_corrections,
            "whitespace_restored_to_exact_source": whitespace_restored,
            "normalized_ambiguous_retained": normalized_ambiguous,
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
            "block_id": "set from frozen unit metadata when provider value differs",
            "text_span": "exact source substring, else whitespace-stripped containment only",
            "unique_whitespace_match": "restore exact source substring with offset map",
            "ambiguous_whitespace_match": "retain provider quote and flag; do not choose an offset",
            "unsupported_after_retry": "reject and count",
            "render_only": "retain but require separate visual verification",
        },
    }
    with args.manifest.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
