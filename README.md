# CBDC MSED v10.2e — reproducibility bundle

This repository contains the smallest self-contained bundle needed to reproduce the numerical results, figures, and pre-adjudication human-validation metrics reported for the v10.2e analysis. The paper manuscript itself, exported PDFs, raw provider archives, duplicate build trees, and superseded experiments are intentionally excluded.

## Reproduce everything

Python 3.12 is used in continuous integration.

```bash
python -m venv .venv
python -m pip install -r requirements.txt
python run.py
```

`run.py` regenerates the frozen calibration outputs, the four ensemble/provider variants, both paper figures, and the blind human-audit summary. It then verifies hashes, population counts, probability metrics, allocation mass, and the human-validation release boundary. A successful run ends with `Reproduction complete.` and leaves `results/` and `figures/` unchanged.

## What is included

- `data/calibration/`: frozen 78-unit package, adjudicated reference, and source-verified OpenAI/Claude outputs.
- `data/ensemble/`: 6,949-candidate mapping, source-verified provider outputs, corpus metadata, and provider provenance manifests.
- `scripts/`: only the calibration evaluator, ensemble analysis, their small shared helpers, and verification utilities.
- `results/calibration/`: precision 0.980, recall 0.765625, and span fidelity 1.000 for the verified union. The preregistered recall gate failed.
- `results/v10_2e_ensemble/`: deterministic ensemble, OpenAI-only, Claude-only, and exact-code-consensus outputs for 47 jurisdictions.
- `validation/human_audit/`: the frozen 365-candidate double-blind sample, completed independent reviewer data, 319-case adjudication queue, 36 dual-empty controls, two recovered claims, and a review-ready workbook.
- `results/human_validation/`: reproducible pre-adjudication validity and intercoder estimates. One untranslated candidate and five untranslated dual-empty units are excluded; all confidence values are treated as high by author instruction.
- `website/`: the deployed static research site. It contains derived tables but no manuscript PDF or source-document binaries.

The canonical provider outputs are sufficient to replay every released result without calling a model API. The removed raw API archives are not analysis inputs; their hashes and run metadata remain in the provenance manifests. Original source PDFs are not redistributed, while their filenames, page counts, authority metadata, and SHA-256 hashes remain in `data/ensemble/provenance/`.

## Research status

This is a work in progress. The blind author audit is complete, but consensus adjudication remains open: raw inclusion agreement is 62.6% (228/364), Gwet's AC1 is 0.426, and the reviewer-specific design-weighted validity estimates are 78.6% and 76.1%. The 77.3% midpoint is descriptive, not a final consensus estimate. Future releases will test whether improving LLMs, a larger and better-balanced document corpus, and a more precisely operationalized family structure improve recall, cross-provider stability, and human coding agreement.

## Integrity

`checksums.sha256` covers every input, script, validation artifact, result, and figure in the reproducibility bundle. Verify it without regenerating results:

```bash
python scripts/update_checksums.py
```

After an intentional reviewed change, refresh the inventory with:

```bash
python scripts/update_checksums.py --write
```

The GitHub Actions workflow runs the full reproduction and fails if any tracked result or figure changes.
