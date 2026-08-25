# v10.2e sampled human-validation amendment

Date frozen: 2026-08-25, before human review of the production candidate set.

## Scope and supersession

This amendment supersedes only the full-census human-adjudication design in `PROTOCOL_AMENDMENT.md`. No coding had begun in the superseded workbooks. Provider runs, source verification, matching, the frozen development calibration, and the unopened 40-page reserve remain unchanged.

The full-corpus outputs are treated as an exploratory LLM-assisted candidate dataset, not as a fully human-adjudicated gold dataset. Human review is a probability-sample validation of that dataset. Substantive results derived from all candidates must be described accordingly and accompanied by the sampled error estimates and sensitivity limits below.

## Candidate sample

The sampling frame contains all 6,949 deduplicated, source-verified production candidates. Required sample size was calculated before coding for a two-sided 95% interval, worst-case proportion 0.5, target half-width 0.05, and finite-population correction:

`n = ceil[N z^2 p(1-p) / {e^2(N-1) + z^2 p(1-p)}] = 365`.

Thus 365/6,949 candidates (5.2526%) are reviewed. The achieved worst-case finite-population-corrected half-width is 0.04993. Selection is without replacement by SHA-256 rank using seed `cbdc-v10.2e-sampled-validation-20260825-v1`, stratified by source language and provider-origin type (`both`, `openai_only`, `claude_only`). Hamilton proportional allocation is used with at least one case from every nonempty stratum. Both authors independently code the identical 365 cases. Provider identity, provider code, origin type, stratum, and original candidate identifier are hidden from both workbooks.

Because rare strata are deliberately represented, population point estimates use inverse inclusion-probability weights. The primary 95% interval is design based with finite-population correction; a worst-case variance contribution of 0.25 is used for any sampled non-census stratum with only one observation. Unweighted estimates are reported only as sensitivity checks.

## Separate dual-empty audit

Both authors also retain the already frozen 36/359 (10.03%) probability sample of source units where neither provider returned a candidate. This audit estimates the proportion of `dual-empty` units containing at least one eligible missed claim and its claim yield within that frame only. It does not identify misses in units with one or more extracted candidates and therefore is not a production-recall estimator.

## Human coding and consensus

Martin and Dominik complete their workbooks independently and do not compare decisions until both files are returned and hash-locked. For each sampled candidate they record inclusion (`keep`, `exclude`, or temporarily `needs_context`), the final code and auxiliary fields required by the codebook, confidence, and any exact-span correction. All `needs_context` states are resolved before analysis. They also independently complete the dual-empty audit and any corresponding supplement rows.

After lock, only disagreements are discussed. The consensus record is the human reference for sampled performance estimates; it does not silently alter unsampled records. Any later rule applied to unsampled records must be deterministic, documented, and reported as a sensitivity analysis rather than human adjudication.

## Predeclared reporting

The paper reports:

1. inverse-probability-weighted human keep rate for the 6,949-candidate union, with a 95% interval;
2. weighted candidate validity by provider after unblinding;
3. weighted exact provider-to-consensus code agreement conditional on a human `keep` decision;
4. pre-consensus Martin–Dominik percent agreement, Krippendorff's alpha, and Gwet's AC1 on the common candidate sample, plus code agreement among candidates kept by both;
5. the 36-unit dual-empty missed-claim rate and claim yield, explicitly limited to the dual-empty frame;
6. the frozen calibration precision, recall, span fidelity, and their intervals as the only controlled retrieval-performance estimates;
7. sensitivity of substantive tables to at least (a) the full source-verified LLM union and (b) exclusion or reweighting implied by the sampled human decisions.

The production sample is not described as a complete gold standard, and no full-production recall claim is made. The paper states the 5.2526% sampled validation design; the earlier manuscript statement about a 15% double-coded sample no longer describes this version.

## Frozen artifacts

The selection parameters, mapping hash, and stratum counts are recorded in `human_review/2026-08-25_sampled_validation/SAMPLED_VALIDATION_FREEZE_MANIFEST.json`. Plaintext `sample_machine_mapping.csv` is sealed outside the repository and withheld until both independent workbooks are locked; it is then added and verified against the pre-review hash. The superseded full-census workbooks remain archived for provenance but must not be coded.
