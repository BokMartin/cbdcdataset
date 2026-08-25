#!/usr/bin/env python3
"""Prepare unblinded AI candidate-master payloads for v10.2e."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


DELIMITER = " || "


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, value, *, pretty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2 if pretty else None, separators=None if pretty else (",", ":"))
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def split_ids(value: str) -> list[str]:
    return [item for item in str(value).split(";") if item]


def unique_join(rows: list[dict], key: str) -> str:
    values = []
    seen = set()
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        text = str(value)
        if text not in seen:
            seen.add(text)
            values.append(text)
    return DELIMITER.join(values)


def flatten_provider(label: str, responses: list[dict]) -> dict[str, dict]:
    statements = {}
    for response in responses:
        for unit in response["units"]:
            for ordinal, statement in enumerate(unit["statements"], 1):
                statement_id = f"{label}:{unit['unit_id']}:S{ordinal:03d}"
                if statement_id in statements:
                    raise ValueError(f"duplicate statement: {statement_id}")
                statements[statement_id] = {
                    "provider": label,
                    "statement_id": statement_id,
                    "unit_id": unit["unit_id"],
                    **statement,
                }
    return statements


def merge_candidates(payloads: list[dict]) -> dict[str, dict]:
    candidates = {}
    for payload in payloads:
        for row in payload["candidates"]:
            candidate_id = row["candidate_id"]
            if candidate_id in candidates and candidates[candidate_id] != row:
                raise ValueError(f"candidate payload mismatch: {candidate_id}")
            candidates[candidate_id] = row
    return candidates


def provider_columns(statements: list[dict], prefix: str) -> dict:
    return {
        f"{prefix}_statement_count": len(statements),
        f"{prefix}_statement_ids": ";".join(row["statement_id"] for row in statements),
        f"{prefix}_quotes": unique_join(statements, "quote"),
        f"{prefix}_translations": unique_join(statements, "quote_en"),
        f"{prefix}_codes": unique_join(statements, "code1"),
        f"{prefix}_odr": unique_join(statements, "odr"),
        f"{prefix}_privacy_direction": unique_join(statements, "privacy_direction"),
        f"{prefix}_privacy_relation": unique_join(statements, "privacy_relation"),
        f"{prefix}_strength": unique_join(statements, "strength"),
        f"{prefix}_source_mode": unique_join(statements, "source_mode"),
        f"{prefix}_block_ids": unique_join(statements, "block_id"),
    }


def candidate_row(mapping: dict, display: dict, statements: dict[str, dict]) -> tuple[dict, list[dict]]:
    openai = [statements[item] for item in split_ids(mapping["openai_statement_ids"])]
    claude = [statements[item] for item in split_ids(mapping["claude_statement_ids"])]
    span_hash = hashlib.sha256(display["candidate_span"].encode("utf-8")).hexdigest()
    if span_hash != mapping["candidate_span_sha256"]:
        raise ValueError(f"candidate span hash mismatch: {mapping['candidate_id']}")
    row = {
        "candidate_id": mapping["candidate_id"],
        "origin_type": mapping["origin_type"],
        "doc_id": mapping["doc_id"],
        "page": int(mapping["page"]),
        "language": mapping["language"],
        "project_owner": display["project_owner"],
        "authority_note": display["authority_note"],
        "context_unit_id": mapping["context_unit_id"],
        "alternate_context_unit_id": mapping["alternate_context_unit_id"],
        "candidate_span": display["candidate_span"],
        "candidate_translation": display["candidate_translation"],
        "alternate_span": display["alternate_span"],
        "alternate_translation": display["alternate_translation"],
        "source_excerpt": display["source_excerpt"],
        "source_mode": display["source_mode"],
        "render_file": display["render_file"],
        **provider_columns(openai, "openai"),
        **provider_columns(claude, "claude"),
        "ai_code_set_exact_match": bool(openai and claude and {x["code1"] for x in openai} == {x["code1"] for x in claude}),
        "ai_odr_set_exact_match": bool(openai and claude and {x["odr"] for x in openai} == {x["odr"] for x in claude}),
        "match_score": float(mapping["match_score"]) if mapping["match_score"] else None,
        "match_method": mapping["match_method"],
        "candidate_span_sha256": span_hash,
    }
    detail = []
    for statement in [*openai, *claude]:
        detail.append({
            "candidate_id": mapping["candidate_id"],
            "provider": statement["provider"],
            "statement_id": statement["statement_id"],
            "unit_id": statement["unit_id"],
            "doc_id": mapping["doc_id"],
            "page": int(mapping["page"]),
            "language": mapping["language"],
            "block_id": statement.get("block_id", ""),
            "quote": statement.get("quote", ""),
            "quote_en": statement.get("quote_en") or "",
            "code1": statement.get("code1", ""),
            "odr": statement.get("odr", ""),
            "privacy_direction": statement.get("privacy_direction", ""),
            "privacy_relation": statement.get("privacy_relation", ""),
            "strength": statement.get("strength"),
            "source_mode": statement.get("source_mode", ""),
        })
    return row, detail


def sample_payload(reviewer: str, sample_mapping: list[dict], full_rows: dict[str, dict], provider_rows: dict[str, list[dict]], dual_empty: list[dict], codebook: list[dict]) -> dict:
    candidates = []
    statements = []
    for mapping in sample_mapping:
        candidate_id = mapping["candidate_id"]
        row = {
            "sample_case_id": mapping["sample_case_id"],
            "sample_stratum": mapping["sample_stratum"],
            "stratum_population": int(mapping["stratum_population"]),
            "stratum_sample": int(mapping["stratum_sample"]),
            "inclusion_probability": float(mapping["inclusion_probability"]),
            "survey_weight": float(mapping["survey_weight"]),
            "selection_rank_within_stratum": int(mapping["selection_rank_within_stratum"]),
            "selection_hash": mapping["selection_hash"],
            **full_rows[candidate_id],
        }
        candidates.append(row)
        for statement in provider_rows[candidate_id]:
            statements.append({"sample_case_id": mapping["sample_case_id"], **statement})
    return {
        "schema": "cbdc-v10.2e-ai-candidate-master-v1",
        "scope": "sample",
        "reviewer": reviewer,
        "sealed_until": "both independent human-review workbooks are returned and hash-locked",
        "candidates": candidates,
        "provider_statements": statements,
        "dual_empty_sample": dual_empty,
        "codebook": codebook,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", required=True, type=Path)
    parser.add_argument("--sample-mapping", required=True, type=Path)
    parser.add_argument("--payload-martin", required=True, type=Path)
    parser.add_argument("--payload-dominik", required=True, type=Path)
    parser.add_argument("--openai", required=True, type=Path)
    parser.add_argument("--claude", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

    mapping = read_csv(args.mapping)
    sample_mapping = read_csv(args.sample_mapping)
    martin = read_json(args.payload_martin)
    dominik = read_json(args.payload_dominik)
    candidates = merge_candidates([martin, dominik])
    if set(candidates) != {row["candidate_id"] for row in mapping}:
        raise ValueError("mapping and blind candidate union differ")
    statements = {
        **flatten_provider("openai", read_jsonl(args.openai)),
        **flatten_provider("claude", read_jsonl(args.claude)),
    }

    full_candidates = []
    full_provider_rows = []
    provider_by_candidate = {}
    full_by_id = {}
    for mapping_row in mapping:
        row, detail = candidate_row(mapping_row, candidates[mapping_row["candidate_id"]], statements)
        full_candidates.append(row)
        full_provider_rows.extend(detail)
        provider_by_candidate[row["candidate_id"]] = detail
        full_by_id[row["candidate_id"]] = row

    if len(full_candidates) != 6949 or len({row["candidate_id"] for row in full_candidates}) != 6949:
        raise ValueError("unexpected candidate population")
    sample_ids = [row["candidate_id"] for row in sample_mapping]
    if len(sample_ids) != 365 or len(set(sample_ids)) != 365:
        raise ValueError("unexpected sample size")
    if not set(sample_ids).issubset(full_by_id):
        raise ValueError("sample candidate missing from full master")
    if martin["dual_empty_units"] != dominik["dual_empty_units"]:
        raise ValueError("dual-empty samples differ")

    codebook = martin["codebook"]
    common = {
        "schema": "cbdc-v10.2e-ai-candidate-master-v1",
        "scope": "full",
        "reviewer": "not_applicable",
        "sealed_until": "both independent human-review workbooks are returned and hash-locked",
        "candidates": full_candidates,
        "provider_statements": full_provider_rows,
        "dual_empty_sample": martin["dual_empty_units"],
        "codebook": codebook,
    }
    outputs = {
        "master_full.json": common,
        "master_martin.json": sample_payload("Martin", sample_mapping, full_by_id, provider_by_candidate, martin["dual_empty_units"], codebook),
        "master_dominik.json": sample_payload("Dominik", sample_mapping, full_by_id, provider_by_candidate, martin["dual_empty_units"], codebook),
    }
    for name, payload in outputs.items():
        write_json(args.out_dir / name, payload)

    manifest = {
        "schema": "cbdc-v10.2e-ai-master-freeze-v1",
        "status": "sealed; do not disclose to reviewers before both workbooks are hash-locked",
        "counts": {
            "full_candidates": len(full_candidates),
            "sample_candidates_each": len(sample_mapping),
            "provider_statement_rows_full": len(full_provider_rows),
            "dual_empty_sample_each": len(martin["dual_empty_units"]),
            "origin_type": dict(sorted(Counter(row["origin_type"] for row in full_candidates).items())),
        },
        "input_hashes": {
            "mapping": sha256(args.mapping),
            "sample_mapping": sha256(args.sample_mapping),
            "payload_martin": sha256(args.payload_martin),
            "payload_dominik": sha256(args.payload_dominik),
            "openai_canonical": sha256(args.openai),
            "claude_canonical": sha256(args.claude),
        },
        "payload_hashes": {name: sha256(args.out_dir / name) for name in outputs},
    }
    write_json(args.out_dir / "AI_MASTER_FREEZE_MANIFEST.json", manifest, pretty=True)
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
