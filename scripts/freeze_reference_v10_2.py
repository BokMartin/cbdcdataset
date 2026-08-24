#!/usr/bin/env python3
"""Apply completed blind scope decisions to the frozen v10.1 calibration reference."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-reference", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    with args.base_reference.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    decision_payload = json.loads(args.decisions.read_text(encoding="utf-8"))
    decisions = decision_payload["decisions"]

    if len(decisions) != 69 or len({d["review_case_id"] for d in decisions}) != 69:
        raise ValueError("expected 69 unique scope decisions")
    if any(d["final_decision"] not in {"keep", "exclude"} for d in decisions):
        raise ValueError("all decisions must be keep or exclude")
    if any(d["final_decision"] == "keep" and not d["final_code"] for d in decisions):
        raise ValueError("every kept case needs a code")

    index: dict[tuple[str, str], list[int]] = {}
    for position, row in enumerate(rows):
        index.setdefault((row["gold_id"], row["paragraph_id"]), []).append(position)

    changes: list[dict[str, str]] = []
    for decision in decisions:
        key = (decision["gold_id"], decision["paragraph_id"])
        positions = index.get(key, [])
        if len(positions) != 1:
            raise ValueError(f"{decision['review_case_id']} maps to {len(positions)} reference rows")
        row = rows[positions[0]]
        old_truth = row["reference_truth"]
        old_code = row["reference_code"]
        keep = decision["final_decision"] == "keep"
        row["reference_truth"] = "positive" if keep else "excluded"
        row["reference_code"] = decision["final_code"] if keep else ""
        if not keep:
            row["reference_span"] = ""
        row["adjudication_case_id"] = decision["review_case_id"]
        row["adjudication_rule"] = (
            f"scope_readjudication_v10_2_{decision['resolution_source']}_{decision['final_decision']}"
        )
        changes.append(
            {
                "review_case_id": decision["review_case_id"],
                "gold_id": decision["gold_id"],
                "paragraph_id": decision["paragraph_id"],
                "doc_id": decision["doc_id"],
                "page": str(decision["page"]),
                "old_truth": old_truth,
                "new_truth": row["reference_truth"],
                "old_code": old_code,
                "new_code": row["reference_code"],
                "resolution_source": decision["resolution_source"],
            }
        )

    reference_path = args.output_dir / "calibration_reference_v10_2.csv"
    with reference_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    change_path = args.output_dir / "reference_changes_v10_2.csv"
    with change_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(changes[0]))
        writer.writeheader()
        writer.writerows(changes)

    truth_counts = Counter(row["reference_truth"] for row in rows)
    probability_counts = Counter(
        row["reference_truth"] for row in rows if row["stratum"] == "probability"
    )
    transition_counts = Counter(
        f"{change['old_truth']}->{change['new_truth']}" for change in changes
    )
    summary = {
        "schema_version": "calibration-reference-v10.2",
        "frozen": True,
        "reserve_status": "sealed",
        "row_count": len(rows),
        "page_count": len({row["gold_id"] for row in rows}),
        "truth_counts": dict(sorted(truth_counts.items())),
        "probability_truth_counts": dict(sorted(probability_counts.items())),
        "scope_decision_counts": dict(sorted(Counter(d["final_decision"] for d in decisions).items())),
        "transition_counts": dict(sorted(transition_counts.items())),
        "accepted_final_checks": decision_payload["accepted_final_checks"],
        "single_author_readjudication": True,
        "base_reference": args.base_reference.as_posix(),
        "base_reference_sha256": sha256(args.base_reference),
        "decisions": args.decisions.as_posix(),
        "decisions_sha256": sha256(args.decisions),
        "source_workbook_sha256": decision_payload["source_workbook_sha256"],
        "reference_csv": reference_path.name,
        "reference_csv_sha256": sha256(reference_path),
        "change_log_csv": change_path.name,
        "change_log_csv_sha256": sha256(change_path),
    }
    summary_path = args.output_dir / "calibration_reference_v10_2.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
