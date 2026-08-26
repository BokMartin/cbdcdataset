# CBDC MSED v10.2e — reproducibility bundle

This repository contains the smallest self-contained bundle needed to reproduce the numerical results and figures reported for the v10.2e analysis. The paper manuscript itself, exported PDFs, raw provider archives, duplicate build trees, and superseded experiments are intentionally excluded.

## Reproduce everything

Python 3.12 is used in continuous integration.

```bash
python -m venv .venv
python -m pip install -r requirements.txt
python run.py
```

`run.py` regenerates the frozen calibration outputs, the four ensemble/provider variants, both paper figures, and then verifies hashes, population counts, probability metrics, allocation mass, and the pending-human-validation boundary. A successful run ends with `Reproduction complete.` and leaves `results/` and `figures/` unchanged.

## What is included

- `data/calibration/`: frozen 78-unit package, adjudicated reference, and source-verified OpenAI/Claude outputs.
- `data/ensemble/`: 6,949-candidate mapping, source-verified provider outputs, corpus metadata, and provider provenance manifests.
- `scripts/`: only the calibration evaluator, ensemble analysis, their small shared helpers, and verification utilities.
- `results/calibration/`: precision 0.980, recall 0.765625, and span fidelity 1.000 for the verified union. The preregistered recall gate failed.
- `results/v10_2e_ensemble/`: deterministic ensemble, OpenAI-only, Claude-only, and exact-code-consensus outputs for 47 jurisdictions.
- `validation/human_audit/`: the frozen 365-candidate double-blind sample and 36 dual-empty controls. Human coding remains pending, so the production analysis is exploratory.
- `website/`: the deployed static research site. It contains derived tables but no manuscript PDF or source-document binaries.

The canonical provider outputs are sufficient to replay every released result without calling a model API. The removed raw API archives are not analysis inputs; their hashes and run metadata remain in the provenance manifests. Original source PDFs are not redistributed, while their filenames, page counts, authority metadata, and SHA-256 hashes remain in `data/ensemble/provenance/`.

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
