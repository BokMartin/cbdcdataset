import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
GOLD_DIR = ROOT / "validation/human_gold"
ALLOWED = {
    "",
    "ANO",
    "ANO-částečně",
    "NE-žádná rodina",
    "NE-bez nosné info",
    "NE-cizí CBDC/research",
    "skip_language",
    "structural_blank",
}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    manifest = json.loads((GOLD_DIR / "manifest.json").read_text(encoding="utf-8"))
    gold = pd.read_csv(GOLD_DIR / "gold_extraction_martin_v10f.csv", keep_default_na=False)
    source = ROOT / manifest["source_workbook"]
    counts = manifest["counts"]

    require(hashlib.sha256(source.read_bytes()).hexdigest() == manifest["source_sha256"], "gold source hash")
    require(len(gold) == counts["paragraphs"] and gold[["gold_id", "paragraph_id"]].duplicated().sum() == 0, "gold rows")
    require(set(gold["label"]).issubset(ALLOWED), "gold labels")
    require((gold["included"].astype(str) == "1").sum() == counts["positive"], "gold positive count")
    require((gold["included"].astype(str) == "0").sum() == counts["negative"], "gold negative count")
    require((gold["label"] == "skip_language").sum() == counts["skip_language"], "gold language skips")
    require((gold["label"] == "structural_blank").sum() == counts["structural_blank"], "gold structural blanks")
    require((gold["label"] == "").sum() == counts["unmarked"], "gold unmarked count")
    require((gold["label"] == "ANO-částečně").sum() == counts["partial_positive"], "gold partial count")
    partial_without_note = (gold["label"].eq("ANO-částečně") & gold["note"].eq("")).sum()
    require(partial_without_note == counts["partial_without_note"], "gold partial notes")
    unresolved = gold.loc[gold["label"].eq(""), "workbook_row"].astype(int).tolist()
    require(unresolved == manifest["unmarked_workbook_rows"], "gold unresolved rows")
    sample = pd.read_csv(ROOT / "validation/sample.csv", keep_default_na=False)
    page_manifest = pd.read_csv(ROOT / "validation/page_manifest.csv", keep_default_na=False)
    gold_pages = set(zip(gold["doc_id"], gold["page"].astype(int)))
    sampled = sample[sample["stratum"].ne("reserve_sealed")]
    sample_pages = set(zip(sampled["doc_id"], sampled["page"].astype(int)))
    require(gold_pages == sample_pages, "gold must cover the canonical unsealed sample")
    require(gold["gold_id"].nunique() == counts["pages"], "gold page count")

    blanks = gold[gold["label"].eq("structural_blank")]
    blank_pages = set(zip(blanks["doc_id"], blanks["page"].astype(int)))
    documented = {
        (row["doc_id"], int(row["page"]))
        for correction in manifest["administrative_corrections"]
        for row in correction["added_machine_rows"]
    }
    require(blank_pages == documented, "documented structural blanks")
    blank_manifest = page_manifest[
        page_manifest.apply(lambda row: (row["doc_id"], int(row["page"])) in blank_pages, axis=1)
    ]
    require(len(blank_manifest) == counts["structural_blank"], "structural blank manifest rows")
    require((pd.to_numeric(blank_manifest["chars"]) == 0).all(), "structural blank text")
    require(blank_manifest["ocr_needed"].astype(str).str.lower().isin(["true", "1"]).all(), "structural blank OCR flag")
    require(blank_manifest["render_sha256"].ne("").all(), "structural blank render evidence")
    require(manifest["sample_page_mismatches"] == [], "gold/sample mismatch must be empty")
    require(manifest["status"] == "labels_complete_unfrozen", "unexpected gold status")
    print(
        "human gold: labels_complete_unfrozen; "
        f"positive={counts['positive']}; negative={counts['negative']}; "
        f"skip={counts['skip_language']}; unmarked={counts['unmarked']}; "
        f"structural_blank={counts['structural_blank']}; "
        f"partial_without_optional_note={counts['partial_without_note']}; "
        "sample_page_mismatches=0"
    )


if __name__ == "__main__":
    main()
