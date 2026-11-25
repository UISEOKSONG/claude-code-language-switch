# Pre-registration: stage 6 (`stage5.py run --experiment scope6`)

Written and committed before any stage-6 run. Results will be added below this plan without changing it.

## Why

Stage 5 had an unplanned contrast. On python-json-pointer, Opus 5.5 with Korean leaked English progress notes in 0/8 runs when the `"language": "korean"` setting, a CLAUDE.md rule and a Korean prompt were all set, against 27/40 in stages 3–4, where only the CLAUDE.md rule and the Korean prompt were set. Those came from different batches on different days, so they cannot say whether the `language` setting itself made the difference. On more-itertools, with all three set, Opus/Korean still leaked in 6/8 runs. Stage 6 tests the setting directly, within one batch.

## Design

- Held constant: `claude-opus-5-5`, headless (`claude -p`), the Korean CLAUDE.md rule and the Korean prompt of stage 5, the same fixtures (seven reverts in python-json-pointer, six in more-itertools), the same flags, hook, Python venv, self-check and probes as stage 5.
- Varied: `"language": "korean"` in `.claude/settings.json` present (`lang_on`, identical to the stage-5 Opus/Korean/headless cells) or absent (`lang_off`).
- Two repositories: `jsonpointer` (where the stage-5 contrast appeared) and `more-itertools` (where stage 5 still leaked with the setting on).
- 2 × 2 = 4 conditions, 24 runs each, 96 runs, in 24 rounds with the four conditions shuffled within each round (seed in `meta.json`). Errors are rerun in place as in stage 5. Auto-updater off; version and free disk space checked before every run.

## Outcome and analysis

- Primary outcome: the strict outcome of stages 2–5, scored from the session transcript.
- **Primary test:** `lang_on` vs `lang_off`, exact conditional test of a common odds ratio of 1 stratified by repository, two-sided, α = 0.05, with the Mantel–Haenszel odds ratio. If `lang_off` leaks in fewer than 5 of 48 runs, the leak is not reproduced without the setting and the comparison is not interpreted.
- Secondary, descriptive: per-repository rates with Fisher's test (not corrected; the question is whether the effect, if any, holds on both); progress messages per run; position of the first leak.

## How the result will be read

- p < 0.05 with fewer leaks under `lang_on`: on these repositories, for Opus and Korean, the `language` setting reduces the English progress notes beyond what CLAUDE.md and the prompt do. The per-repository results say whether that holds on both or only on jsonpointer.
- Otherwise: no evidence that the setting helps; the stage-5 contrast was most likely a difference between batches.

## Power

With 24 runs per cell, Fisher's test at α = 0.05 has about 98% power for 65% vs 10% (roughly the jsonpointer contrast), 62% for 65% vs 30%, and 34% for 75% vs 50%. So a large effect on jsonpointer will show; a moderate one on more-itertools may not.

## Not covered

One model, one language, two repositories, headless only, one prompt.

---

## Results (added 2026-11-26, after all 96 runs)

Run on 2026-11-26, 01:34–04:32 KST, same Mac, Claude Code 2.1.311, seed 20261126. All 96 runs finished on the first attempt with the requested model; no run was rerun. Transcript and stream-json agreed on the strict label in 96/96 runs. Files: `results/scope6/`, raw logs in `raw/scope6.tgz` (reduced as in stage 5).

| | `language` on | `language` off | Fisher p |
|---|---|---|---|
| jsonpointer | 12/24 | 9/24 | 0.56 |
| more-itertools | 18/24 | 22/24 | 0.24 |
| both | 30/48 (62%) | 31/48 (65%) | |

**Primary:** stratified exact test, Mantel–Haenszel OR (on vs off) = 0.90, **p = 1.00**. The setting-off arm leaked in 31/48 runs, so the comparison is interpreted: no evidence that the `language` setting reduces the English progress notes beyond the CLAUDE.md rule and the Korean prompt.

- Every one of the 61 leaking runs leaked at its first progress message; the most common lines were again "Let me look at the relevant tests and code." and close variants (73 strict-leak messages in all; 8 runs had more than one). No final answer was in another language.
- The stage-5 contrast that motivated this stage (python-json-pointer, Opus/Korean, 0/8 with the setting on) did not hold: with the setting on, the same cell leaked in 12/24 runs here. The 0/8 was most likely chance or a difference between batches.
- Taken with stages 3–5: on these repositories, for Opus and Korean, none of the user-side options tried (two CLAUDE.md wordings, the system-prompt append, the `language` setting, and all of them together in stage 5) stopped the opening English line.
