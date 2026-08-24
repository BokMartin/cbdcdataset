# Reference review status, 2026-08-24

The completed blind workbook contains 69 adjudication cases: 26 keep, 35 exclude, and 8 needs-context. Sixty-eight rows display `COMPLETE`; `RA-014` displays `#REF!` because its QC formula lost the adjudicator-cell reference. The row itself contains decision, code, and initials, so this is a workbook formula defect rather than missing human input.

Before generating the v10.2 machine reference, the author must confirm 25 targeted checks in `SCOPE_READJUDICATION_v10_1_BLIND_reviewed.xlsx`:

- 19 decision checks, including all eight `needs_context` rows and rule conflicts involving glossaries, future research, fragments, and executed pilot findings;
- two code-only checks (`INTEROP.crossborder` versus `INTEROP.domestic`);
- four metadata-only checks where the keep/exclude decision can remain.

The review workbook does not overwrite the author's labels. Its `Final checks` sheet records the current label, recommendation, reason, and an `accept/revise/undecided` field. The corrected copy also repairs `Review!M18`. The v10.2 model package contains none of this information.

Codebook notes from the author were resolved prospectively as follows:

- keep `LEGAL.basis` as a narrow audit-only code; the disputed `RA-017` passage is general market regulation and does not qualify;
- keep `STAB.disintermediation`; it is analytically necessary for deposits, bank funding, lending, runs, and monetary transmission;
- do not merge `ADOPT.experience` with `INTEROP.domestic`; tighten their boundary;
- card-network integration is domestic unless the source explicitly states a foreign jurisdiction/CBDC, corridor, remittance, FX, or cross-currency flow.

The 40-page reserve remains sealed. Claude and Codex may run the blinded v10.2 development package while these author confirmations are completed, but model results must stay sealed until the v10.2 reference is frozen.
