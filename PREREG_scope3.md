# Pre-registration: `scope3` experiment (stage 3)

Written and committed before any `scope3` run. Results will be added below this plan without changing it.

## Why

Stages 1 and 2 (`PREREG_scope.md`, `PREREG_scope2.md`) used one model (`claude-opus-5-5`), one language (Korean) and one small synthetic repository. In stage 1, "Always answer in Korean." leaked in 11/16 runs and "Write the short notes you leave for the user while working in Korean too." in 0/16; in stage 2 the second text leaked in 3/48 runs on the strict outcome. The only earlier runs on other models were legacy v3 (a different task, 3 runs per condition): Sonnet 5.5 wrote 29 progress messages in 12 runs there (Opus 134 in 16), and Fable 5.2 wrote 1 in the 6 runs without a CLAUDE.md or hook; too little to judge. Stage 3 asks whether both parts hold outside that setup: (a) does the English progress-note leak appear at all, and (b) does the during-work wording leak less than "always answer".

## Design

Four arms. Each changes one thing from stages 1 and 2 and keeps the rest.

| arm | model | language of CLAUDE.md and prompt | repository |
|---|---|---|---|
| `sonnet` | `claude-sonnet-5-5` | Korean | synthetic `textkit` (as in stages 1–2) |
| `haiku` | `claude-haiku-5-5` | Korean | synthetic `textkit` |
| `ja` | `claude-opus-5-5` | Japanese | synthetic `textkit` |
| `real` | `claude-opus-5-5` | Korean | real repository, below |

- Two conditions in every arm, each a one-file project CLAUDE.md (full text in `langleak.py`):
  - A `s_answer`: "항상 한국어로 답하세요." ("Always answer in Korean.")
  - B `s_during`: "작업하는 도중에 사용자에게 남기는 짧은 글도 한국어로 작성하세요." ("Write the short notes you leave for the user while working in Korean too.")
  - Both end with the same sentence as in stages 1–2 ("keep code, commands and file names as they are"). The `ja` arm uses Japanese translations of all three sentences (`CLAUDE_MD_JA`) and a Japanese prompt (`PROMPT_JA`).
- Everything else as in stages 1–2: English docs, logs and test output; Bash auto-approve hook; `--setting-sources project`; the same allowed tools.
- **Real repository:** `tasks/jsonpointer` is [python-json-pointer](https://github.com/stefankoegl/python-json-pointer) (BSD-3-Clause) at commit `9c4d3da` (2026-11-19), without `.git` and `.github`. The fixture reverts seven upstream fixes in `jsonpointer.py` (commits `d62e138`, `c625f3b`, `70ffd92`, `09b3cd7`, `86b82bf`, `4358bbb`, `9854838`; exact text in `REAL_TASKS`); the tests that came with those fixes stay. The prompt asks, in Korean, to fix every failing test and rerun the suite with the repository's own command, `python3 -m unittest`, after each fix. Before any run, `langleak.py selfcheck` must show that the upstream copy passes and that each revert's listed test fails; otherwise the experiment does not start. This arm puts a Python ≥ 3.10.7 (required by the library) first on PATH. Because Claude Code's Bash tool may rebuild PATH from the user's shell configuration, a short Haiku call before the batch asks Claude Code to run `python3` in that same environment, and the batch does not start unless it reports ≥ 3.10.7. The version Claude Code's Bash runs for the synthetic arms is checked the same way. Both are recorded in `meta.json` (`python_real_in_claude_bash`, `python_synthetic_in_claude_bash`); the synthetic test runner's output does not depend on the Python version.
- 16 runs per condition, 128 in total, in 16 rounds; the order of the eight conditions is shuffled within each round (seed recorded in `meta.json`).

## Outcomes

- **Primary (strict), as in stage 2:** a run leaks if at least one progress message is classified `en` or `other` and is not a heading-only line (`langleak.HEADER_ONLY`).
- For the `ja` arm, `langleak.classify(text, "ja")` treats kana and CJK ideographs as the target script: a message with none of them and at least 8 Latin letters is `en`, Hangul without them is `other`, and the 0.3 ratio for `mixed` is unchanged. CJK-only text (no kana) counts as Japanese.
- Reported for every condition: progress messages per run. A run with no progress message cannot leak, so a low leak rate in an arm that writes few progress messages is read as such, not as a working instruction.
- Secondary: any `en`/`other` progress message (the stage-1 outcome); the same with `mixed` counted; non-target final answers; where the first leak happens.
- A run whose stream reports a model that does not start with the requested name is excluded and listed. Runs that end in an error (for example the usage limit) are rerun with `--resume`.

## Analysis

- **(a) Reproduction gate, per arm:** if A leaks in 2 or fewer of 16 runs on the strict outcome, the leak is reported as not reproduced at a measurable rate in that arm, and that arm's A vs B comparison is not interpreted.
- **(b) Primary, per arm that passes the gate:** A vs B on the strict outcome, two-sided Fisher exact test, Holm correction across those arms, family-wise α = 0.05.
- Secondary, descriptive: the secondary outcomes per arm; runs with no permission denial; each arm next to the stage-1/2 Opus Korean synthetic result.

## How the result will be read

- Arm passes (b) with B lower: in that setting too, naming the during-work notes reduced English progress notes compared with "always answer".
- Arm passes the gate but not (b): no evidence from 16 runs per condition; with this size that is not evidence of no effect (see power). If A is at 20–50% there, a later pre-registered stage with more runs in that arm may follow, as stage 2 followed stage 1.
- Arm fails the gate: the leak itself did not show up at a measurable rate there, which is a result about that model, language or repository, not about the wording.
- The result still covers two wordings, one prompt per arm, and headless `claude -p` runs.

## Power

With 16 runs per condition and B at 5%, Fisher's test at α = 0.05 has about 91% power if A leaks in 60% of runs, 78% at 50%, 57% at 40% and 31% at 30%. At the Holm worst case (α = 0.0125) the same figures are 77%, 53%, 27% and 9%. In stage 1, A leaked in 11/16 runs.

## Running

`python3 langleak.py run scope3 --n 16 --seed <s> --python-real <python ≥ 3.10.7> --resume results/scope3/<dir>` (the `--model` option is ignored for this experiment; each arm sets its own). If the usage limit stops a batch, the same command resumes it after the limit resets and skips finished runs.
