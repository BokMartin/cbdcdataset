import json
import re
from pathlib import Path

import pandas as pd
from docx import Document
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]


def text_of(path):
    document = Document(path)
    parts = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells)
    for section in document.sections:
        parts.extend(paragraph.text for paragraph in section.header.paragraphs)
        parts.extend(paragraph.text for paragraph in section.footer.paragraphs)
    return "\n".join(parts)


def decimal(text, value, digits=2):
    value = f"{value:.{digits}f}"
    return any(re.search(rf"(?<![\d.]){re.escape(item)}(?!\d)", text)
               for item in [value, value.replace("-", "−")])


def main():
    text = text_of(ROOT / "paper/current.docx")
    candidates = pd.read_csv(ROOT / "data/candidates.csv", keep_default_na=False)
    scores = pd.read_csv(ROOT / "results/scores.csv", keep_default_na=False)
    stages = pd.read_csv(ROOT / "data/stages.csv", keep_default_na=False)
    audit = json.loads((ROOT / "results/audit.json").read_text(encoding="utf-8"))
    robustness = json.loads((ROOT / "results/robustness.json").read_text(encoding="utf-8"))
    sensitivity = json.loads((ROOT / "results/cash_gate_sensitivity.json").read_text(encoding="utf-8"))
    dominant = scores["dominant_centre"].value_counts()
    mixed = int(scores["mixed_case"].astype(str).str.lower().isin(["true", "1"]).sum())
    regression = audit["regression"]
    checks = {
        "candidate count": "6,139" in text,
        "kept count": "5,624" in text and (candidates["v5_verdict"] == "keep").sum() == 5_624,
        "yielding documents": "ninety-three" in text or "93 " in text,
        "sovereignty count": "leads with twelve jurisdictions" in text and dominant["sovereignty_competition"] == 12,
        "state-control count": "state control follows with eleven" in text and dominant["state_control"] == 11,
        "modernisation and inclusion counts": "payment modernisation and financial inclusion with nine each" in text and dominant["payment_modernization"] == dominant["financial_inclusion"] == 9,
        "transmission count": "monetary transmission with seven" in text and dominant["monetary_transmission"] == 7,
        "cash count": "dominates nowhere" in text and dominant.get("cash_substitution", 0) == 0,
        "mixed count": "nineteen of the forty-eight" in text and mixed == 19,
        "no stale mixed count": "twenty-two of the forty-eight" not in text and "eighteen of the forty-eight" not in text,
        "cash sensitivity": "dominant centre in nine jurisdictions" in text and "−0.22 and −0.37" in text and sensitivity["ungated"].get("cash_substitution") == 9,
        "obsolete regime claim absent": "regime type and region would" not in text and "for about a fifth of cases" not in text,
        "shadow citation": "Elgin et al., 2021" in text and "Medina" not in text,
        "measure names": "privacy-family share" in text and "documented privacy posture" in text,
        "obsolete commitment names absent": all(term not in text for term in ["documented privacy commitment", "binding architectural", "measurement-validation"]),
        "regression sample": "thirty-three jurisdictions" in text and regression["n"] == 33,
        "entity framing": "forty-seven jurisdictions and two institutional composites" in text,
        "robustness": all(robustness[key]["shadow"]["r"] < -0.2 for key in ["headline", "decision_only", "document_balanced", "min8_privacy_statements", "wholesale_excluded"]) and robustness["lodo_range"]["shadow"]["max"] < -0.2,
        "page limit": len(PdfReader(ROOT / "paper/current.pdf").pages) <= 12,
        "stage counts": all(phrase in text for phrase in [
            "one live deployment", "ten pilots", "thirteen active research programmes",
            "twenty-two paused programmes", "one cancelled project",
        ]) and stages["stage_final"].value_counts().to_dict().get("active_research") == 13 and stages["stage_final"].value_counts().to_dict().get("paused_research") == 22 and stages["stage_final"].value_counts().to_dict().get("cancelled") == 1,
        "DCash cancellation": "The cancelled case is DCash 2.0" in text and "ECCU remains in the historical design analysis" in text,
        "vocabulary democracy": decimal(text, audit["pairwise"]["vocabulary"]["vdem"]["r"]),
        "posture democracy": decimal(text, audit["pairwise"]["commitment"]["vdem"]["r"]),
        "posture shadow economy": decimal(text, audit["pairwise"]["commitment"]["shadow"]["r"]),
        "shared variance": re.search(r"(?<!\d)18\s*%(?!\d)", text) is not None and round(100 * audit["vocab_vs_commitment"]["r"] ** 2) == 18,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise AssertionError("paper checks failed: " + ", ".join(failed))
    print(f"paper: {len(checks)} checks passed")


if __name__ == "__main__":
    main()
