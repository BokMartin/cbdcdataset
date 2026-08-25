#!/usr/bin/env python3
"""Verify frozen v10.2e ensemble outputs."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/v10_2e_ensemble"


def sha256(path: Path) -> str:
    content = path.read_bytes()
    if path.suffix.lower() in {".csv", ".json", ".jsonl", ".md"}:
        content = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(content).hexdigest()


def main() -> None:
    manifest = json.loads((OUT / "analysis_manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((OUT / "analysis_summary.json").read_text(encoding="utf-8"))
    for relative, expected in manifest["outputs"].items():
        path = ROOT / relative
        if sha256(path) != expected:
            raise AssertionError(f"output hash mismatch: {relative}")
    for item in manifest["inputs"].values():
        path = ROOT / item["path"]
        if sha256(path) != item["sha256"]:
            raise AssertionError(f"input hash mismatch: {item['path']}")

    with gzip.open(OUT / "candidate_allocations.csv.gz", "rt", encoding="utf-8", newline="") as handle:
        allocations = pd.read_csv(handle, keep_default_na=False)
    mass = allocations.groupby(["variant", "candidate_id"])["allocation_weight"].sum()
    if not np.allclose(mass.to_numpy(), 1.0, atol=1e-10):
        raise AssertionError("candidate mass does not equal one")
    expected_populations = {"ensemble": 6949, "openai": 5622, "claude": 5634, "consensus": 1788}
    observed = allocations.groupby("variant")["candidate_id"].nunique().to_dict()
    if observed != expected_populations:
        raise AssertionError(f"variant populations: {observed}")
    if summary["origin_type"] != {"both": 4307, "claude_only": 1327, "openai_only": 1315}:
        raise AssertionError("origin counts changed")
    if summary["agreement_among_both"]["exact_code_set"] != 1788:
        raise AssertionError("exact-code agreement changed")
    if summary["human_validation"]["status"] != "pending_blind_double_review":
        raise AssertionError("human-validation status changed unexpectedly")

    scores = pd.read_csv(OUT / "entity_scores.csv", keep_default_na=False)
    if scores.groupby("variant")["jur"].nunique().to_dict() != {"claude": 47, "consensus": 47, "ensemble": 47, "openai": 47}:
        raise AssertionError("entity coverage changed")
    print("ensemble v10.2e: hashes, mass, populations and pending-human boundary verified")


if __name__ == "__main__":
    main()
