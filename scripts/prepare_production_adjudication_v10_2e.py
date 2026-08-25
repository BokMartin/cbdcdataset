#!/usr/bin/env python3
"""Prepare blinded two-author adjudication payloads for v10.2e production."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from evaluate_extraction_v10_1 import one_to_one_pairs, span_overlap


SEED = 20260825
MATCH_THRESHOLD = 0.80
OVERLAP_FRACTION = 0.20
DUAL_EMPTY_FRACTION = 0.10
SUPPLEMENT_SLOTS = 5


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(*values) -> str:
    return hashlib.sha256("|".join(map(str, values)).encode("utf-8")).hexdigest()


def normalized(text: str) -> str:
    return re.sub(r"\s+", "", str(text).casefold())


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def flatten(label: str, responses: list[dict], units: dict[str, dict]) -> tuple[list[dict], dict]:
    statements = []
    results = {}
    for response in responses:
        for result in response["units"]:
            unit_id = result["unit_id"]
            if unit_id in results:
                raise ValueError(f"duplicate unit result: {label}:{unit_id}")
            results[unit_id] = result
            unit = units[unit_id]
            for ordinal, statement in enumerate(result["statements"], 1):
                statements.append(
                    {
                        "statement_id": f"{label}:{unit_id}:S{ordinal:03d}",
                        "model": label,
                        "unit_id": unit_id,
                        "doc_id": unit["doc_id"],
                        "page": int(unit["page"]),
                        "language": unit["language"],
                        **statement,
                    }
                )
    if set(results) != set(units):
        raise ValueError(f"global unit coverage mismatch: {label}")
    return statements, results


def representative(rows: list[dict], units: dict[str, dict]) -> dict:
    def support_rank(row: dict) -> int:
        source = units[row["unit_id"]].get("source_text", "")
        if row["quote"] and row["quote"] in source:
            return 0
        if row["quote"] and normalized(row["quote"]) in normalized(source):
            return 1
        if units[row["unit_id"]].get("render_file"):
            return 2
        return 3

    return min(
        rows,
        key=lambda row: (
            support_rank(row),
            -len(normalized(row["quote"])),
            stable_hash(row["quote"], row.get("quote_en") or ""),
            row["statement_id"],
        ),
    )


def deduplicate_within_model(rows: list[dict], units: dict[str, dict]) -> tuple[list[dict], int]:
    groups = defaultdict(list)
    for row in rows:
        groups[(row["doc_id"], int(row["page"]), normalized(row["quote"]))].append(row)
    collapsed = []
    removed = 0
    for key in sorted(groups):
        members = groups[key]
        rep = dict(representative(members, units))
        rep["member_statement_ids"] = sorted(row["statement_id"] for row in members)
        rep["member_unit_ids"] = sorted({row["unit_id"] for row in members})
        rep["member_codes"] = sorted({row["code1"] for row in members})
        rep["member_odr"] = sorted({row["odr"] for row in members})
        collapsed.append(rep)
        removed += len(members) - 1
    return collapsed, removed


def pair_models(openai: list[dict], claude: list[dict]) -> list[dict]:
    a_by_page = defaultdict(list)
    b_by_page = defaultdict(list)
    for index, row in enumerate(openai):
        a_by_page[(row["doc_id"], int(row["page"]))].append(index)
    for index, row in enumerate(claude):
        b_by_page[(row["doc_id"], int(row["page"]))].append(index)
    pairs = []
    for page in sorted(set(a_by_page) | set(b_by_page)):
        left = a_by_page[page]
        right = b_by_page[page]
        edges = []
        for local_left, left_index in enumerate(left):
            for local_right, right_index in enumerate(right):
                score, method = span_overlap(openai[left_index], claude[right_index])
                if score >= MATCH_THRESHOLD:
                    edges.append((local_left, local_right, score, {"method": method}))
        for local_left, local_right, score, metadata in one_to_one_pairs(
            len(left), len(right), edges
        ):
            pairs.append(
                {
                    "openai_index": left[local_left],
                    "claude_index": right[local_right],
                    "score": round(float(score), 6),
                    "method": metadata["method"],
                }
            )
    return pairs


def source_excerpt(unit: dict, quote: str, radius: int = 550) -> str:
    source = unit.get("source_text", "")
    if not source:
        return ""
    start = source.find(quote) if quote else -1
    end = start + len(quote) if start >= 0 else -1
    if start < 0 and quote:
        compact_source = normalized(source)
        compact_quote = normalized(quote)
        compact_start = compact_source.find(compact_quote)
        if compact_start >= 0:
            offsets = [index for index, char in enumerate(source) if not char.isspace()]
            start = offsets[compact_start]
            end = offsets[compact_start + len(compact_quote) - 1] + 1
    if start < 0:
        return source[: radius * 2] + (" …" if len(source) > radius * 2 else "")
    left = max(0, start - radius)
    right = min(len(source), end + radius)
    return ("… " if left else "") + source[left:right] + (" …" if right < len(source) else "")


def make_candidate(
    openai_group: dict | None,
    claude_group: dict | None,
    pair: dict | None,
    units: dict[str, dict],
    authorities: dict[str, dict],
) -> dict:
    groups = [group for group in (openai_group, claude_group) if group is not None]
    display = representative(groups, units)
    alternate = next(
        (
            group for group in groups
            if group["statement_id"] != display["statement_id"]
            and normalized(group["quote"]) != normalized(display["quote"])
        ),
        None,
    )
    unit = units[display["unit_id"]]
    authority = authorities[unit["doc_id"]]
    origin = "both" if len(groups) == 2 else groups[0]["model"] + "_only"
    return {
        "candidate_id": "",
        "allocation_stratum": f"{unit['language']}|{origin}",
        "origin_type": origin,
        "doc_id": unit["doc_id"],
        "page": int(unit["page"]),
        "language": unit["language"],
        "project_owner": authority["project_owner"],
        "authority_note": authority["authority_note"],
        "context_unit_id": display["unit_id"],
        "alternate_context_unit_id": alternate["unit_id"] if alternate else "",
        "source_mode": unit["source_mode"],
        "render_file": unit.get("render_file") or "",
        "candidate_span": display["quote"],
        "candidate_translation": display.get("quote_en") or "",
        "alternate_span": alternate["quote"] if alternate else "",
        "alternate_translation": alternate.get("quote_en") or "" if alternate else "",
        "source_excerpt": source_excerpt(unit, display["quote"]),
        "match_score": pair["score"] if pair else "",
        "match_method": pair["method"] if pair else "",
        "openai_statement_ids": openai_group["member_statement_ids"] if openai_group else [],
        "claude_statement_ids": claude_group["member_statement_ids"] if claude_group else [],
        "openai_codes": openai_group["member_codes"] if openai_group else [],
        "claude_codes": claude_group["member_codes"] if claude_group else [],
        "openai_odr": openai_group["member_odr"] if openai_group else [],
        "claude_odr": claude_group["member_odr"] if claude_group else [],
    }


def proportional_allocations(counts: dict[str, int], target: int) -> dict[str, int]:
    total = sum(counts.values())
    if not total or target <= 0:
        return {key: 0 for key in counts}
    quotas = {key: target * count / total for key, count in counts.items()}
    allocation = {
        key: min(counts[key], max(1, math.floor(quotas[key]))) for key in counts
    }
    while sum(allocation.values()) > target:
        candidates = [key for key in allocation if allocation[key] > 1]
        if not candidates:
            break
        key = min(
            candidates,
            key=lambda value: (
                quotas[value] - math.floor(quotas[value]),
                stable_hash(SEED, "reduce", value),
            ),
        )
        allocation[key] -= 1
    while sum(allocation.values()) < target:
        candidates = [key for key in allocation if allocation[key] < counts[key]]
        if not candidates:
            break
        key = max(
            candidates,
            key=lambda value: (
                quotas[value] - allocation[value],
                stable_hash(SEED, "add", value),
            ),
        )
        allocation[key] += 1
    if sum(allocation.values()) != target:
        raise ValueError("stratified allocation did not reach exact target")
    return allocation


def select_stratified(rows: list[dict], fraction: float, stratum_field: str, purpose: str) -> set[str]:
    target = int(len(rows) * fraction + 0.5)
    grouped = defaultdict(list)
    for row in rows:
        grouped[str(row[stratum_field])].append(row)
    allocations = proportional_allocations(
        {stratum: len(values) for stratum, values in grouped.items()}, target
    )
    selected = set()
    id_field = "candidate_id" if purpose == "overlap" else "unit_id"
    for stratum, values in grouped.items():
        ranked = sorted(
            values,
            key=lambda row: stable_hash(SEED, purpose, stratum, row[id_field]),
        )
        selected.update(row[id_field] for row in ranked[: allocations[stratum]])
    if len(selected) != target:
        raise ValueError(f"{purpose} sample size mismatch")
    return selected


def reviewer_rows(candidates: list[dict], overlap: set[str]) -> tuple[dict[str, list[dict]], dict[str, str]]:
    assigned = {"Martin": [], "Dominik": []}
    allocation = {}
    grouped = defaultdict(list)
    for row in candidates:
        if row["candidate_id"] in overlap:
            assigned["Martin"].append(row)
            assigned["Dominik"].append(row)
            allocation[row["candidate_id"]] = "both"
        else:
            grouped[row["allocation_stratum"]].append(row)
    for stratum, values in sorted(grouped.items()):
        ranked = sorted(
            values,
            key=lambda row: stable_hash(SEED, "single", stratum, row["candidate_id"]),
        )
        first = "Martin" if int(stable_hash(SEED, "start", stratum), 16) % 2 == 0 else "Dominik"
        second = "Dominik" if first == "Martin" else "Martin"
        for index, row in enumerate(ranked):
            reviewer = first if index % 2 == 0 else second
            assigned[reviewer].append(row)
            allocation[row["candidate_id"]] = reviewer
    for reviewer in assigned:
        assigned[reviewer].sort(
            key=lambda row: stable_hash(SEED, "workbook", reviewer, row["candidate_id"])
        )
    return assigned, allocation


def blind_candidate(row: dict) -> dict:
    return {
        key: row[key]
        for key in (
            "candidate_id", "candidate_span", "candidate_translation", "alternate_span",
            "alternate_translation", "source_excerpt", "context_unit_id",
            "alternate_context_unit_id", "doc_id", "page", "language", "project_owner",
            "authority_note", "source_mode", "render_file",
        )
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--openai", type=Path, required=True)
    parser.add_argument("--claude", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    package = args.package.resolve()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    source_requests = read_jsonl(package / "inputs.jsonl")
    units = {
        unit["unit_id"]: unit for request in source_requests for unit in request["units"]
    }
    authorities = {
        row["doc_id"]: row
        for row in csv.DictReader((package / "source_authority.csv").open(encoding="utf-8-sig"))
    }
    codebook = list(csv.DictReader((package / "codebook.csv").open(encoding="utf-8-sig")))

    openai_raw, openai_results = flatten("openai", read_jsonl(args.openai), units)
    claude_raw, claude_results = flatten("claude", read_jsonl(args.claude), units)
    openai, openai_collapsed = deduplicate_within_model(openai_raw, units)
    claude, claude_collapsed = deduplicate_within_model(claude_raw, units)
    pairs = pair_models(openai, claude)
    paired_openai = {pair["openai_index"] for pair in pairs}
    paired_claude = {pair["claude_index"] for pair in pairs}
    candidates = [
        make_candidate(openai[pair["openai_index"]], claude[pair["claude_index"]], pair, units, authorities)
        for pair in pairs
    ]
    candidates.extend(
        make_candidate(row, None, None, units, authorities)
        for index, row in enumerate(openai) if index not in paired_openai
    )
    candidates.extend(
        make_candidate(None, row, None, units, authorities)
        for index, row in enumerate(claude) if index not in paired_claude
    )
    candidates.sort(
        key=lambda row: (
            row["doc_id"], row["page"], row["context_unit_id"],
            stable_hash(row["candidate_span"], row["alternate_span"], row["origin_type"]),
        )
    )
    for index, row in enumerate(candidates, 1):
        row["candidate_id"] = f"PC-{index:05d}"

    overlap = select_stratified(candidates, OVERLAP_FRACTION, "allocation_stratum", "overlap")
    reviewer_candidates, allocation = reviewer_rows(candidates, overlap)

    dual_empty = []
    for unit_id, unit in units.items():
        left = openai_results[unit_id]
        right = claude_results[unit_id]
        if (
            left["status"] == "ok" and right["status"] == "ok"
            and not left["statements"] and not right["statements"]
            and unit.get("source_text", "").strip()
        ):
            authority = authorities[unit["doc_id"]]
            dual_empty.append(
                {
                    "empty_case_id": "",
                    "unit_id": unit_id,
                    "doc_id": unit["doc_id"],
                    "page": int(unit["page"]),
                    "language": unit["language"],
                    "project_owner": authority["project_owner"],
                    "authority_note": authority["authority_note"],
                    "source_mode": unit["source_mode"],
                    "source_text": unit["source_text"],
                    "render_file": unit.get("render_file") or "",
                }
            )
    empty_selected_ids = select_stratified(dual_empty, DUAL_EMPTY_FRACTION, "language", "dual_empty")
    dual_empty = [row for row in dual_empty if row["unit_id"] in empty_selected_ids]
    dual_empty.sort(key=lambda row: stable_hash(SEED, "dual_empty_workbook", row["unit_id"]))
    for index, row in enumerate(dual_empty, 1):
        row["empty_case_id"] = f"DE-{index:04d}"

    lists = {
        "inclusion_decision": ["keep", "exclude", "needs_context"],
        "exclusion_reason": [
            "foreign_or_cited_research", "generic_context", "future_research_or_open_question",
            "stakeholder_or_consultant_not_adopted", "glossary_heading_or_list",
            "incomplete_fragment_or_ocr", "non_cbdc_or_off_scope", "duplicate_candidate", "other",
        ],
        "odr": ["decision", "proposal", "finding"],
        "privacy_direction": ["increases", "decreases", "conditional", "neutral"],
        "privacy_relation": ["from_state", "from_intermediary", "from_counterparty", "not_applicable"],
        "strength": [1, 2, 3],
        "confidence": ["high", "medium", "low"],
        "missed_claims": ["yes", "no", "unclear"],
    }
    shared_empty = dual_empty
    render_files = sorted(
        {
            row["render_file"] for row in candidates + dual_empty if row.get("render_file")
        }
    )
    for reviewer in ("Martin", "Dominik"):
        assigned_candidates = reviewer_candidates[reviewer]
        context_ids = {
            value for row in assigned_candidates
            for value in (row["context_unit_id"], row["alternate_context_unit_id"])
            if value
        } | {row["unit_id"] for row in shared_empty}
        contexts = [
            {
                "context_unit_id": unit_id,
                "doc_id": units[unit_id]["doc_id"],
                "page": int(units[unit_id]["page"]),
                "language": units[unit_id]["language"],
                "source_mode": units[unit_id]["source_mode"],
                "source_text": units[unit_id]["source_text"],
                "render_file": units[unit_id].get("render_file") or "",
            }
            for unit_id in sorted(context_ids)
        ]
        payload = {
            "schema": "cbdc-v10.2e-blind-production-adjudication-workbook-v1",
            "reviewer": reviewer,
            "blinding": "model identity, origin, model code, and overlap membership absent",
            "candidates": [blind_candidate(row) for row in assigned_candidates],
            "dual_empty_units": shared_empty,
            "supplement_slots_per_unit": SUPPLEMENT_SLOTS,
            "contexts": contexts,
            "codebook": codebook,
            "lists": lists,
        }
        write_json(out_dir / f"payload_{reviewer.casefold()}.json", payload)

    mapping_rows = []
    for row in candidates:
        mapping_rows.append(
            {
                "candidate_id": row["candidate_id"],
                "allocation": allocation[row["candidate_id"]],
                "overlap": row["candidate_id"] in overlap,
                "allocation_stratum": row["allocation_stratum"],
                "origin_type": row["origin_type"],
                "doc_id": row["doc_id"],
                "page": row["page"],
                "language": row["language"],
                "context_unit_id": row["context_unit_id"],
                "alternate_context_unit_id": row["alternate_context_unit_id"],
                "openai_statement_ids": ";".join(row["openai_statement_ids"]),
                "claude_statement_ids": ";".join(row["claude_statement_ids"]),
                "openai_codes": ";".join(row["openai_codes"]),
                "claude_codes": ";".join(row["claude_codes"]),
                "openai_odr": ";".join(row["openai_odr"]),
                "claude_odr": ";".join(row["claude_odr"]),
                "match_score": row["match_score"],
                "match_method": row["match_method"],
                "candidate_span_sha256": hashlib.sha256(row["candidate_span"].encode("utf-8")).hexdigest(),
            }
        )
    write_csv(out_dir / "candidate_machine_mapping.csv", mapping_rows)
    write_json(out_dir / "render_files.json", render_files)
    language_empty = Counter(row["language"] for row in dual_empty)
    manifest = {
        "schema": "cbdc-v10.2e-production-human-review-freeze-v1",
        "rules": {
            "intra_model_dedup": "same doc_id, page, and whitespace-stripped casefolded source span; model codes preserved as a set",
            "cross_model_matching": "maximum-cardinality maximum-score one-to-one at overlap >= 0.80",
            "overlap": "exact 20% proportional stratification by language and origin type; minimum one per nonempty stratum when feasible",
            "single_assignment": "deterministic hash-ranked alternation within allocation stratum",
            "dual_empty_eligibility": "both final unit statuses ok, both contain zero statements, nonempty source_text",
            "dual_empty_sample": "exact 10% proportional stratification by language; independently reviewed by both authors",
            "blinding": "provider identity, provider codes, origin type, allocation, and overlap membership excluded from workbooks",
        },
        "seed": SEED,
        "counts": {
            "units": len(units),
            "openai_statements_canonical": len(openai_raw),
            "claude_statements_canonical": len(claude_raw),
            "openai_same_span_collapsed": openai_collapsed,
            "claude_same_span_collapsed": claude_collapsed,
            "openai_candidates_after_same_span_dedup": len(openai),
            "claude_candidates_after_same_span_dedup": len(claude),
            "cross_model_pairs": len(pairs),
            "deduplicated_union_candidates": len(candidates),
            "independent_overlap_candidates": len(overlap),
            "overlap_fraction": len(overlap) / len(candidates),
            "martin_candidate_rows": len(reviewer_candidates["Martin"]),
            "dominik_candidate_rows": len(reviewer_candidates["Dominik"]),
            "dual_empty_eligible_units": sum(
                1 for unit_id, unit in units.items()
                if openai_results[unit_id]["status"] == "ok"
                and claude_results[unit_id]["status"] == "ok"
                and not openai_results[unit_id]["statements"]
                and not claude_results[unit_id]["statements"]
                and unit.get("source_text", "").strip()
            ),
            "dual_empty_sample_units": len(dual_empty),
            "dual_empty_sample_by_language": dict(sorted(language_empty.items())),
            "render_files_needed": len(render_files),
        },
        "hashes": {
            "package_inputs": sha256(package / "inputs.jsonl"),
            "codebook": sha256(package / "codebook.csv"),
            "source_authority": sha256(package / "source_authority.csv"),
            "openai_canonical": sha256(args.openai.resolve()),
            "claude_canonical": sha256(args.claude.resolve()),
            "candidate_machine_mapping": sha256(out_dir / "candidate_machine_mapping.csv"),
            "payload_martin": sha256(out_dir / "payload_martin.json"),
            "payload_dominik": sha256(out_dir / "payload_dominik.json"),
            "render_files": sha256(out_dir / "render_files.json"),
        },
    }
    write_json(out_dir / "HUMAN_REVIEW_FREEZE_MANIFEST.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
