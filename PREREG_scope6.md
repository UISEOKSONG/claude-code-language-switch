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
