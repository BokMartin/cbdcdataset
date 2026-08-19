import argparse
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SEED = 42
N_PROBABILITY = 60
N_RESERVE = 40


def hash_rank(doc_id):
    return hashlib.sha256(f"{SEED}|{doc_id}".encode()).hexdigest()


def make_split(queue):
    extracted = queue[queue["extraction_status"] == "extracted"].copy()
    if extracted["doc_id"].duplicated().any():
        raise ValueError("duplicate doc_id")
    extracted["stratum"] = extracted["language"] + "|" + extracted["scope"]
    rows = []
    for stratum, group in extracted.groupby("stratum"):
        ids = sorted(group["doc_id"], key=hash_rank)
        calibration = max(1, round(0.30 * len(ids))) if len(ids) > 1 else 0
        for i, doc_id in enumerate(ids):
            rows.append({
                "doc_id": doc_id, "stratum": stratum,
                "split": "held_out" if len(ids) == 1 or i >= calibration else "calibration",
                "rule": "singleton->held_out" if len(ids) == 1 else "hash-rank",
            })
    result = pd.DataFrame(rows)
    if set(result["doc_id"]) != set(extracted["doc_id"]):
        raise AssertionError("incomplete split")
    return result


def make_sample(manifest, split, queue):
    pages = manifest[manifest["doc_id"] != ""].copy()
    pages[["page", "chars"]] = pages[["page", "chars"]].astype(int)
    for name in ["ocr_needed", "tableish"]:
        pages[name] = pages[name].astype(str).str.lower().isin(["true", "1"])
    unknown = set(pages["doc_id"]) - set(split["doc_id"])
    status = queue.set_index("doc_id")["extraction_status"].to_dict()
    if any(status.get(doc_id) != "queued_series3" for doc_id in unknown):
        raise ValueError("unexpected manifest document outside split")
    pages = pages.merge(split[["doc_id", "split"]], on="doc_id", how="left", validate="many_to_one")
    held_out = pages[pages["split"] == "held_out"].reset_index(drop=True)
    if len(held_out) < N_PROBABILITY + N_RESERVE:
        raise ValueError("held-out page pool is too small")
    permutation = np.random.default_rng(SEED).permutation(len(held_out))

    def selected(indices, stratum, start):
        rows = []
        for order, index in enumerate(indices, start):
            row = held_out.iloc[index]
            rows.append({
                "doc_id": row["doc_id"], "fname": row["fname"], "page": int(row["page"]),
                "stratum": stratum, "language": row["lang_guess"], "chars": int(row["chars"]),
                "ocr_needed": bool(row["ocr_needed"]),
                "inclusion_prob": round(N_PROBABILITY / len(held_out), 6) if stratum == "probability" else "",
                "draw_order": order,
            })
        return rows

    plan = selected(permutation[:N_PROBABILITY], "probability", 0)
    plan += selected(permutation[N_PROBABILITY:N_PROBABILITY + N_RESERVE], "reserve_sealed", 100)
    used = {(row["fname"], row["page"]) for row in plan}

    def stress(pool, name, count):
        pool = pool[~pool.apply(lambda row: (row["fname"], row["page"]) in used, axis=1)]
        sample = pool.sample(n=min(count, len(pool)), random_state=SEED) if len(pool) else pool
        rows = []
        for row in sample.itertuples():
            used.add((row.fname, row.page))
            rows.append({
                "doc_id": row.doc_id, "fname": row.fname, "page": int(row.page),
                "stratum": name, "language": row.lang_guess, "chars": int(row.chars),
                "ocr_needed": bool(row.ocr_needed), "inclusion_prob": "", "draw_order": "",
            })
        return rows

    plan += stress(held_out[(held_out["lang_guess"] != "en") & (held_out["lang_guess"] != "")], "stress_nonEN", 8)
    plan += stress(held_out[held_out["ocr_needed"] & (held_out["chars"] == 0)], "stress_ocr_zerotext", 3)
    plan += stress(held_out[held_out["ocr_needed"] & (held_out["chars"] > 0)], "stress_ocr_lowtext", 3)
    plan += stress(held_out[held_out["tableish"]], "stress_tableish", 3)
    plan += stress(held_out[held_out["chars"] > 4_500], "stress_long", 4)
    result = pd.DataFrame(plan)
    result["pdf_available"] = True
    if result[["fname", "page"]].astype(str).agg("|".join, axis=1).duplicated().any():
        raise AssertionError("duplicate sampled page")
    return result, len(held_out), len(unknown), int(pages["doc_id"].isin(unknown).sum())


def same_csv(expected, frozen):
    expected = expected.fillna("").astype(str).reset_index(drop=True)
    frozen = frozen.fillna("").astype(str).reset_index(drop=True)
    return list(expected.columns) == list(frozen.columns) and expected.equals(frozen)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    queue = pd.read_csv(ROOT / "data/documents.csv", keep_default_na=False)
    manifest = pd.read_csv(ROOT / "validation/page_manifest.csv", keep_default_na=False)
    split = make_split(queue)
    sample, n_pages, prospective_docs, prospective_pages = make_sample(manifest, split, queue)
    if args.write:
        split.to_csv(ROOT / "validation/split.csv", index=False, lineterminator="\n")
        sample.to_csv(ROOT / "validation/sample.csv", index=False, lineterminator="\n")
    else:
        frozen_split = pd.read_csv(ROOT / "validation/split.csv", keep_default_na=False)
        frozen_sample = pd.read_csv(ROOT / "validation/sample.csv", keep_default_na=False)
        if not same_csv(split, frozen_split) or not same_csv(sample, frozen_sample):
            raise AssertionError("frozen split or sample differs; inspect before --write")
    print(f"split: {split['split'].value_counts().to_dict()}; held-out pages={n_pages}")
    print(f"prospective boundary: {prospective_docs} documents, {prospective_pages} pages")


if __name__ == "__main__":
    main()
