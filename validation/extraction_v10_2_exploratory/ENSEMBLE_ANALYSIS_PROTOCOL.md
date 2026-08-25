# v10.2e ensemble analysis

Frozen: 2026-08-25, before unblinding the sampled human reviews.

## Candidate mass

The unit of analysis is the deduplicated candidate. Every candidate contributes total mass 1.

- One provider only: that provider receives mass 1.
- Both providers: each provider receives mass 0.5.
- Within a provider, its mass is divided equally among distinct codes. Repeated evidence for the same code does not increase mass.
- If one code has conflicting auxiliary annotations, its code mass is divided equally among the distinct `(ODR, privacy direction, privacy relation, strength)` tuples.
- If both providers assign the same code set, the combined code mass is 1. Categorical labels are never averaged.

The main analysis uses the full source-verified union. OpenAI-only, Claude-only and exact-code-consensus analyses are reported as sensitivity variants. Provider origin remains visible in all machine outputs.

## Analytic filters and weights

Purpose and privacy scores use non-`NONE` decisions and proposals. Decision weight is 1 and proposal weight is 0.5. Strength remains 1–3. Candidate allocation multiplies these weights, so disagreement does not duplicate evidence. Findings remain in the released distributions but do not enter commitment scores.

The six purpose centres reuse the frozen code-to-centre map and lexical dictionary. The longest source-verified quotation attached to an annotation tuple is the deterministic text representative. Percentile calibration thresholds are estimated once from the ensemble and applied unchanged to all sensitivity variants.

## Human validation boundary

The 365-candidate probability sample estimates candidate validity and coding agreement. It does not replace all 6,949 machine labels and does not estimate full-corpus recall. The 36-unit dual-empty audit estimates misses only inside that frame. Until both reviews are hash-locked and adjudicated, human-validation fields in the paper remain explicitly pending.

After adjudication, the main full-union analysis is retained and accompanied by a deterministic sensitivity analysis using the sample's inverse-probability-weighted error estimates. No unsampled candidate is described as human coded.
