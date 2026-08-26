#!/usr/bin/env python3
"""Build the legacy-layout cbdcdataset.org site from frozen v10.2e outputs."""

from __future__ import annotations

import csv
from datetime import date
import hashlib
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
import shutil
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "website_src"
OUTPUT = ROOT / "website"
RESULTS = ROOT / "results" / "v10_2e_ensemble"
FREEZE = ROOT / "validation" / "extraction_v10_2_exploratory" / "PACKAGE_FREEZE.json"
CORPUS_MANIFEST = ROOT / "validation" / "extraction_v10_2_exploratory" / "freeze" / "corpus_manifest.csv"
AI_SEAL = ROOT / "validation" / "extraction_v10_2_exploratory" / "human_review" / "2026-08-25_sampled_validation" / "ai_master_seal" / "AI_MASTER_SEAL_MANIFEST.json"
RELEASE_DATE = date(2026, 8, 26)

CENTRES = (
    "cash_substitution",
    "financial_inclusion",
    "payment_modernization",
    "monetary_transmission",
    "sovereignty_competition",
    "state_control",
)
CENTRE_LABELS = {
    "cash_substitution": "Cash substitution",
    "financial_inclusion": "Financial inclusion",
    "payment_modernization": "Payment modernisation",
    "monetary_transmission": "Monetary transmission",
    "sovereignty_competition": "Sovereignty & competition",
    "state_control": "State control",
}
STAGE_LABELS = {
    "live": "Live",
    "pilot": "Pilot",
    "active_research": "Active research",
    "paused_research": "Research (paused)",
    "cancelled": "Cancelled",
    "not_applicable": "Institutional composite",
}


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def source_sha256(path: Path) -> str:
    """Hash logical text content so source provenance is checkout-stable."""
    content = path.read_bytes()
    if path.suffix.lower() in {".csv", ".json", ".jsonl", ".js", ".sha256"}:
        content = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(content).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def number(value: object) -> float | None:
    if value in {None, ""}:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def fmt_signed(value: float) -> str:
    return f"{value:.3f}".replace("-", "−")


def fmt_interval(values: list[float]) -> str:
    return f"[{fmt_signed(values[0])}, {fmt_signed(values[1])}]"


def reset_output() -> None:
    expected = ROOT / "website"
    if OUTPUT.resolve() != expected.resolve():
        raise RuntimeError(f"Refusing to reset unexpected output path: {OUTPUT}")
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)


def headline_values() -> dict[str, object]:
    summary = load_json(RESULTS / "analysis_summary.json")
    macro = load_json(RESULTS / "macro_results.json")
    freeze = load_json(FREEZE)
    seal = load_json(AI_SEAL)
    ensemble = macro["variants"]["ensemble"]
    relation = ensemble["measurement_relation"]
    shadow = ensemble["posture"]["shadow"]
    single_provider = summary["origin_type"]["openai_only"] + summary["origin_type"]["claude_only"]
    counts = freeze["counts"]
    return {
        "DOCUMENTS": f"{counts['documents']:,}",
        "PAGES": f"{counts['pages']:,}",
        "STATEMENTS": f"{seal['counts']['full_provider_statements']:,}",
        "CANDIDATES": f"{summary['candidate_population']:,}",
        "MEASUREMENT_R": fmt_signed(relation["r"]),
        "MEASUREMENT_VARIANCE": f"{100 * relation['r'] ** 2:.1f}",
        "MEASUREMENT_CI": fmt_interval(relation["ci"]),
        "MEASUREMENT_N": relation["n"],
        "SHADOW_R": fmt_signed(shadow["r"]),
        "SHADOW_CI": fmt_interval(shadow["ci"]),
        "SHADOW_N": shadow["n"],
        "SHADOW_PHOLM": f"{shadow['p_holm']:.3f}",
        "EXACT_CODE_RATE": f"{100 * summary['agreement_among_both']['exact_code_set_rate']:.1f}",
        "SINGLE_PROVIDER_RATE": f"{100 * single_provider / summary['candidate_population']:.1f}",
        "UPDATED": RELEASE_DATE.strftime("%d %B %Y").lstrip("0"),
    }


def copy_static_source() -> None:
    for source in SOURCE.rglob("*"):
        relative = source.relative_to(SOURCE)
        if source.name in {"country_bindings.json", ".htaccess"}:
            continue
        target = OUTPUT / relative
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.suffix.lower() == ".js":
                target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
            else:
                shutil.copy2(source, target)


def apply_templates(values: dict[str, object]) -> None:
    for path in OUTPUT.rglob("*.html"):
        content = path.read_text(encoding="utf-8")
        for key, value in values.items():
            content = content.replace(f"{{{{{key}}}}}", str(value))
        if re.search(r"\{\{[A-Z0-9_]+\}\}", content):
            raise RuntimeError(f"Unresolved template placeholder in {path.relative_to(OUTPUT)}")
        path.write_text(content, encoding="utf-8", newline="\n")


def extract_year(*values: str) -> int | None:
    matches: list[int] = []
    for value in values:
        matches.extend(int(item) for item in re.findall(r"(?:19|20)\d{2}", value or ""))
    return max(matches) if matches else None


def ensemble_rows() -> list[dict[str, str]]:
    return [row for row in load_csv(RESULTS / "entity_scores.csv") if row["variant"] == "ensemble"]


def build_map_data(rows: list[dict[str, str]]) -> dict[str, object]:
    country_bindings = load_json(SOURCE / "assets" / "country_bindings.json")
    stage_rows = load_csv(ROOT / "data" / "stages.csv")
    document_rows = load_csv(ROOT / "data" / "documents.csv")
    names = {row["jur"]: row["country"] for row in load_csv(ROOT / "data" / "jurisdictions.csv")}
    names.update({row["jur"]: row["country"] for row in rows})

    documents: dict[str, list[dict[str, object]]] = {}
    for row in document_rows:
        jur = row["doc_id"].split("_", 1)[0]
        documents.setdefault(jur, []).append({
            "file": row["path"],
            "label": row["doc_id"],
            "year": extract_year(row["doc_id"], row["path"]),
            "pages": int(float(row["pages"])),
            "stage_only": False,
        })
    for values in documents.values():
        values.sort(key=lambda item: (item["year"] or 0, str(item["label"])), reverse=True)

    by_jur = {row["jur"]: row for row in rows}
    ranked = sorted(rows, key=lambda row: number(row["privacy_posture"]) or 0.0, reverse=True)
    ranks = {row["jur"]: index for index, row in enumerate(ranked, start=1)}
    jurisdictions: dict[str, object] = {}
    stage_counts: dict[str, int] = {}
    for stage in stage_rows:
        jur = stage["jur"]
        final_stage = stage["stage_final"]
        stage_counts[final_stage] = stage_counts.get(final_stage, 0) + 1
        stage_doc = stage["doc_id"]
        current_docs = list(documents.get(jur, []))
        if stage_doc and all(item["label"] != stage_doc for item in current_docs):
            current_docs.insert(0, {
                "file": "",
                "label": stage_doc,
                "year": extract_year(stage_doc, stage.get("year", "")),
                "pages": 0,
                "stage_only": True,
            })
        score = by_jur.get(jur)
        centre = None
        privacy = None
        if score:
            ordered = sorted(
                ((name, number(score.get(f"score_{name}")) or 0.0) for name in CENTRES),
                key=lambda item: item[1],
                reverse=True,
            )
            centre = {
                "dominant": ordered[0][0],
                "dominant_label": CENTRE_LABELS[ordered[0][0]],
                "dominant_score": ordered[0][1],
                "second": ordered[1][0],
                "second_label": CENTRE_LABELS[ordered[1][0]],
                "second_score": ordered[1][1],
                "mixed": truthy(score["mixed_case"]),
            }
            privacy = {
                "score": number(score["privacy_posture"]) or 0.0,
                "rank": ranks[jur],
                "of": len(rows),
            }
        jurisdictions[jur] = {
            "name": names.get(jur, jur),
            "stage": final_stage,
            "stage_label": STAGE_LABELS[final_stage],
            "docs": current_docs,
            "privacy": privacy,
            "centres": centre,
        }
    payload = {
        "schema": "cbdc-v10.2e-map-v1",
        "generated_from": "data/stages.csv + data/documents.csv + results/v10_2e_ensemble/entity_scores.csv",
        "status": "exploratory; sampled double-blind human validation pending",
        "stage_counts": stage_counts,
        "countries": country_bindings,
        "jurisdictions": jurisdictions,
    }
    target = OUTPUT / "assets" / "map_data.json"
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    return payload


def build_privacy_data(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    ordered = sorted(rows, key=lambda row: number(row["privacy_posture"]) or 0.0, reverse=True)
    output_rows: list[dict[str, object]] = []
    for rank, row in enumerate(ordered, start=1):
        output_rows.append({
            "rank": rank,
            "jur": row["jur"],
            "country": row["country"],
            "iso3": row["iso3"],
            "privacy_posture": number(row["privacy_posture"]) or 0.0,
            "privacy_family_share": number(row["privacy_family_share"]),
            "dominant_centre": row["dominant_centre"],
            "analytic_candidate_mass": number(row["analytic_candidate_mass"]) or 0.0,
            "documents": int(number(row["documents"]) or 0),
            "is_composite": truthy(row["is_composite"]),
        })
    max_abs = max(abs(float(row["privacy_posture"])) for row in output_rows)
    payload = {
        "schema": "cbdc-v10.2e-privacy-posture-website-v1",
        "meta": {
            "status": "exploratory; sampled double-blind human validation pending",
            "scale": [-1, 1],
            "max_abs_posture": max_abs,
            "rows": len(output_rows),
        },
        "rows": output_rows,
    }
    data_dir = OUTPUT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "privacy_posture_v10_2e.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    with (data_dir / "privacy_posture_v10_2e.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(output_rows)
    return output_rows


def copy_release_assets() -> None:
    image_dir = OUTPUT / "assets" / "img"
    image_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "figures" / "v10_2e_ensemble_composition.png", image_dir / "fig_composition.png")
    shutil.copy2(ROOT / "figures" / "v10_2e_model_sensitivity.png", image_dir / "fig_correlations.png")
    data_dir = OUTPUT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    downloads = {
        ROOT / "paper" / "current.pdf": "MSED2026_Bok_Stroukal_preprint.pdf",
        RESULTS / "entity_scores.csv": "entity_scores.csv",
        RESULTS / "distributions.csv": "distributions.csv",
        RESULTS / "candidate_allocations.csv.gz": "candidate_allocations.csv.gz",
        RESULTS / "analysis_summary.json": "analysis_summary.json",
        RESULTS / "macro_results.json": "macro_results.json",
        RESULTS / "analysis_manifest.json": "analysis_manifest.json",
        CORPUS_MANIFEST: "corpus_manifest.csv",
        ROOT / "data" / "stages.csv": "jurisdiction_stage.csv",
        ROOT / "data" / "codebook.csv": "codebook.csv",
    }
    for source, name in downloads.items():
        target = data_dir / name
        if source.suffix.lower() in {".csv", ".json"}:
            encoding = "utf-8-sig" if source.suffix.lower() == ".csv" else "utf-8"
            target.write_text(source.read_text(encoding="utf-8-sig"), encoding=encoding, newline="\n")
        else:
            shutil.copy2(source, target)


def auxiliary_routes() -> None:
    page = """<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Page not found — CBDC Dataset</title><link rel=\"stylesheet\" href=\"styles.css\"></head><body><div class=\"layout\"><aside class=\"side\"><a class=\"brand\" href=\"index.html\">CBDC <span>Dataset</span></a></aside><main class=\"content\"><section class=\"hero\"><div class=\"wrap\"><h1>Page not found</h1><p class=\"lead\">The current release may have moved this file. Start from the data page or the reproducibility repository.</p><div class=\"btn-row\"><a class=\"btn btn-primary\" href=\"data.html\">Current data</a><a class=\"btn btn-outline\" href=\"index.html\">Home</a></div></div></section></main></div></body></html>\n"""
    (OUTPUT / "404.html").write_text(page, encoding="utf-8", newline="\n")
    (OUTPUT / "robots.txt").write_text("User-agent: *\nAllow: /\nSitemap: https://cbdcdataset.org/sitemap.xml\n", encoding="utf-8", newline="\n")
    pages = ["", "privacy-index.html", "data.html", "paper.html", "pipeline.html", "contribute.html", "about.html"]
    lines = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>", '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    lines.extend(f"  <url><loc>https://cbdcdataset.org/{page}</loc></url>" for page in pages)
    lines.append("</urlset>")
    (OUTPUT / "sitemap.xml").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_manifests(values: dict[str, object], privacy_rows: int) -> None:
    source_files = [
        RESULTS / "analysis_summary.json",
        RESULTS / "macro_results.json",
        RESULTS / "entity_scores.csv",
        RESULTS / "distributions.csv",
        RESULTS / "candidate_allocations.csv.gz",
        CORPUS_MANIFEST,
        ROOT / "data" / "stages.csv",
        ROOT / "data" / "codebook.csv",
        ROOT / "paper" / "current.pdf",
        ROOT / "figures" / "v10_2e_ensemble_composition.png",
        ROOT / "figures" / "v10_2e_model_sensitivity.png",
    ]
    manifest = {
        "schema": "cbdc-v10.2e-legacy-layout-website-build-v1",
        "research_status": "exploratory; sampled double-blind human validation pending",
        "build_date": RELEASE_DATE.isoformat(),
        "site_url": "https://cbdcdataset.org/",
        "privacy_rows": privacy_rows,
        "headline_values": values,
        "sources": {str(path.relative_to(ROOT)).replace("\\", "/"): source_sha256(path) for path in source_files},
    }
    path = OUTPUT / "data" / "deployment_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    files = sorted(path for path in OUTPUT.rglob("*") if path.is_file() and path.name != "checksums.sha256")
    lines = [f"{sha256(path)}  {path.relative_to(OUTPUT).as_posix()}" for path in files]
    (OUTPUT / "data" / "checksums.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        for name in ("href", "src", "action"):
            if values.get(name):
                self.links.append(str(values[name]))


def verify(values: dict[str, object], map_payload: dict[str, object], privacy_rows: list[dict[str, object]]) -> None:
    required_pages = ["index.html", "privacy-index.html", "data.html", "paper.html", "pipeline.html", "contribute.html", "about.html"]
    missing_pages = [name for name in required_pages if not (OUTPUT / name).is_file()]
    if missing_pages:
        raise RuntimeError(f"Missing website pages: {missing_pages}")
    combined = "\n".join((OUTPUT / name).read_text(encoding="utf-8") for name in required_pages)
    markers = ["113", "3,963", "11,358", "6,949", "r</em> = 0.219", "−0.286", "human audit", "interactive"]
    missing_markers = [value for value in markers if value not in combined]
    if missing_markers:
        raise RuntimeError(f"Missing current-release markers: {missing_markers}")
    forbidden = ["5,624", "6,139", "privacy_index_v1", "CBDC_MASTER_2026-07-28", "Web vibecoded with Claude"]
    stale = [value for value in forbidden if value in combined]
    if stale:
        raise RuntimeError(f"Legacy research markers remain: {stale}")
    if values["CANDIDATES"] != "6,949" or len(privacy_rows) != 47:
        raise RuntimeError("Unexpected current-release population")
    jurisdictions = map_payload["jurisdictions"]
    if jurisdictions["ECCU"]["stage"] != "cancelled" or map_payload["stage_counts"].get("cancelled") != 1:
        raise RuntimeError("DCash cancellation is absent from map data")
    if not (OUTPUT / "assets" / "countries-50m.json").is_file() or not (OUTPUT / "assets" / "map_data.json").is_file():
        raise RuntimeError("Interactive map assets are incomplete")
    if (OUTPUT / ".htpasswd").exists() or (OUTPUT / "assets" / "country_bindings.json").exists():
        raise RuntimeError("Private or build-only file entered the deploy tree")
    missing_links: list[tuple[str, str]] = []
    for page_name in required_pages + ["thanks.html", "404.html"]:
        parser = LinkParser()
        parser.feed((OUTPUT / page_name).read_text(encoding="utf-8"))
        for link in parser.links:
            parsed = urlparse(link)
            if parsed.scheme or link.startswith(("#", "mailto:")):
                continue
            local = link.split("#", 1)[0].split("?", 1)[0]
            if local and not (OUTPUT / local).exists():
                missing_links.append((page_name, link))
    if missing_links:
        raise RuntimeError(f"Broken local links: {missing_links}")


def main() -> None:
    reset_output()
    values = headline_values()
    copy_static_source()
    apply_templates(values)
    rows = ensemble_rows()
    map_payload = build_map_data(rows)
    privacy_rows = build_privacy_data(rows)
    copy_release_assets()
    auxiliary_routes()
    write_manifests(values, len(privacy_rows))
    verify(values, map_payload, privacy_rows)
    files = [path for path in OUTPUT.rglob("*") if path.is_file()]
    print(f"website: {len(files)} files, {len(privacy_rows)} privacy rows, output={OUTPUT}")


if __name__ == "__main__":
    main()
