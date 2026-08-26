#!/usr/bin/env python3
"""Build the deployable cbdcdataset.org static site from frozen outputs."""

from __future__ import annotations

import csv
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "website_src"
OUTPUT = ROOT / "website"
RESULTS = ROOT / "results" / "v10_2e_ensemble"
FREEZE = ROOT / "validation" / "extraction_v10_2_exploratory" / "PACKAGE_FREEZE.json"
AI_SEAL = (
    ROOT
    / "validation"
    / "extraction_v10_2_exploratory"
    / "human_review"
    / "2026-08-25_sampled_validation"
    / "ai_master_seal"
    / "AI_MASTER_SEAL_MANIFEST.json"
)
RELEASE_DATE = date(2026, 8, 26)


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def finite_or_none(value: str | float | int | None) -> str | float | int | None:
    if value in {None, ""}:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    return number if math.isfinite(number) else None


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
    (OUTPUT / "assets").mkdir(parents=True)
    (OUTPUT / "data").mkdir(parents=True)
    (OUTPUT / "downloads").mkdir(parents=True)


def render_index() -> dict[str, object]:
    summary = load_json(RESULTS / "analysis_summary.json")
    macro = load_json(RESULTS / "macro_results.json")
    freeze = load_json(FREEZE)
    seal = load_json(AI_SEAL)
    ensemble = macro["variants"]["ensemble"]
    relation = ensemble["measurement_relation"]
    shadow = ensemble["posture"]["shadow"]
    single_provider = summary["origin_type"]["openai_only"] + summary["origin_type"]["claude_only"]

    counts = freeze["counts"]
    values = {
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
    content = (SOURCE / "index.html").read_text(encoding="utf-8")
    for key, value in values.items():
        content = content.replace(f"{{{{{key}}}}}", str(value))
    if "{{" in content or "}}" in content:
        raise RuntimeError("Unresolved template placeholder in website index")
    (OUTPUT / "index.html").write_text(content, encoding="utf-8", newline="\n")
    return {"counts": counts, "provider_statements": seal["counts"]["full_provider_statements"], **values}


def build_entity_data() -> int:
    with (RESULTS / "entity_scores.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row["variant"] == "ensemble"]
    fields = [
        "jur",
        "iso3",
        "country",
        "dominant_centre",
        "privacy_family_share",
        "privacy_posture",
        "analytic_candidate_mass",
        "documents",
        "mixed_case",
        "is_composite",
    ]
    numeric = {"privacy_family_share", "privacy_posture", "analytic_candidate_mass", "documents"}
    entities = []
    for row in rows:
        item = {key: finite_or_none(row.get(key)) if key in numeric else row.get(key) for key in fields}
        entities.append(item)
    entities.sort(key=lambda item: str(item["country"]))
    payload = {
        "schema": "cbdc-v10.2e-website-entity-table-v1",
        "status": "exploratory; sampled double-blind human validation pending",
        "entities": entities,
    }
    (OUTPUT / "data" / "entities.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return len(entities)


def copy_assets() -> None:
    shutil.copy2(SOURCE / "styles.css", OUTPUT / "styles.css")
    shutil.copy2(SOURCE / "app.js", OUTPUT / "app.js")
    shutil.copy2(ROOT / "figures" / "v10_2e_ensemble_composition.png", OUTPUT / "assets" / "ensemble-composition.png")
    shutil.copy2(ROOT / "figures" / "v10_2e_model_sensitivity.png", OUTPUT / "assets" / "model-sensitivity.png")

    downloads = {
        ROOT / "paper" / "current.pdf": "cbdc-msed-v10-paper.pdf",
        RESULTS / "entity_scores.csv": "entity_scores.csv",
        RESULTS / "distributions.csv": "distributions.csv",
        RESULTS / "candidate_allocations.csv.gz": "candidate_allocations.csv.gz",
        RESULTS / "analysis_summary.json": "analysis_summary.json",
        RESULTS / "macro_results.json": "macro_results.json",
        RESULTS / "analysis_manifest.json": "analysis_manifest.json",
    }
    for source, name in downloads.items():
        shutil.copy2(source, OUTPUT / "downloads" / name)


def legacy_routes() -> None:
    routes = {
        "about.html": "about",
        "contribute.html": "about",
        "data.html": "data",
        "paper.html": "paper",
        "pipeline.html": "method",
        "privacy-index.html": "results",
    }
    template = """<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>CBDC Dataset</title><meta http-equiv=\"refresh\" content=\"0; url=index.html#{anchor}\">
<link rel=\"canonical\" href=\"https://cbdcdataset.org/#{anchor}\"></head>
<body><p>This page has moved to <a href=\"index.html#{anchor}\">the current CBDC Dataset</a>.</p></body></html>\n"""
    for filename, anchor in routes.items():
        (OUTPUT / filename).write_text(template.format(anchor=anchor), encoding="utf-8", newline="\n")
    (OUTPUT / "404.html").write_text(template.format(anchor="top"), encoding="utf-8", newline="\n")
    (OUTPUT / "robots.txt").write_text(
        "User-agent: *\nAllow: /\nSitemap: https://cbdcdataset.org/sitemap.xml\n",
        encoding="utf-8",
        newline="\n",
    )
    (OUTPUT / "sitemap.xml").write_text(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n"
        "  <url><loc>https://cbdcdataset.org/</loc></url>\n"
        "</urlset>\n",
        encoding="utf-8",
        newline="\n",
    )


def write_manifests(values: dict[str, object], entity_count: int) -> None:
    source_files = [
        RESULTS / "analysis_summary.json",
        RESULTS / "macro_results.json",
        RESULTS / "entity_scores.csv",
        RESULTS / "distributions.csv",
        RESULTS / "candidate_allocations.csv.gz",
        ROOT / "paper" / "current.pdf",
        ROOT / "figures" / "v10_2e_ensemble_composition.png",
        ROOT / "figures" / "v10_2e_model_sensitivity.png",
    ]
    manifest = {
        "schema": "cbdc-v10.2e-website-build-v1",
        "research_status": "exploratory; sampled double-blind human validation pending",
        "build_date": RELEASE_DATE.isoformat(),
        "site_url": "https://cbdcdataset.org/",
        "entity_rows": entity_count,
        "headline_values": values,
        "sources": {
            str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path) for path in source_files
        },
    }
    manifest_path = OUTPUT / "downloads" / "deployment_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    files = sorted(path for path in OUTPUT.rglob("*") if path.is_file() and path.name != "checksums.sha256")
    lines = [f"{sha256(path)}  {path.relative_to(OUTPUT).as_posix()}" for path in files]
    (OUTPUT / "downloads" / "checksums.sha256").write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )


def verify(values: dict[str, object], entity_count: int) -> None:
    index = (OUTPUT / "index.html").read_text(encoding="utf-8")
    required = [
        "113 documents",
        "3,963 page units",
        "11,358",
        "6,949",
        "r = 0.219",
        "r = −0.286",
        "human audit is in progress",
        "exploratory production results",
    ]
    missing = [value for value in required if value not in index]
    if missing:
        raise RuntimeError(f"Website verification failed; missing markers: {missing}")
    if values["CANDIDATES"] != "6,949" or entity_count != 47:
        raise RuntimeError("Unexpected website data counts")
    if not (OUTPUT / "downloads" / "checksums.sha256").is_file():
        raise RuntimeError("Download checksums were not generated")


def main() -> None:
    reset_output()
    values = render_index()
    entity_count = build_entity_data()
    copy_assets()
    legacy_routes()
    write_manifests(values, entity_count)
    verify(values, entity_count)
    files = [path for path in OUTPUT.rglob("*") if path.is_file()]
    print(f"website: {len(files)} files, {entity_count} entity rows, output={OUTPUT}")


if __name__ == "__main__":
    main()
