# Pre-registration: stage 5 (`stage5.py`)

Written and committed before any stage-5 run. Results will be added below this plan without changing it.

## Why

Stages 1–4 found English progress notes under Korean (and Japanese) instructions, most clearly on a real repository, where no user-side text tried stopped a single English opening line. But every measured rate so far came from headless `claude -p` runs, mostly on one model, and the only real repository was python-json-pointer. Stage 5 asks two things in one balanced design:

1. **Primary:** do interactive (TUI) sessions leak at a different rate from headless runs, under the same flags and instructions?
2. **Descriptive:** how often does the leak occur across three models, three languages and four real repositories, with every user-side language setting switched on?

## Design

Full factorial, 3 × 3 × 4 × 2 = 72 conditions, 4 runs each, 288 runs.

- **Model:** `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5` (`--model`, checked against the model in the transcript).
- **Language:** Korean, Japanese, Chinese. In every run, all three user-side settings are in that language: `"language": "korean" | "japanese" | "chinese"` in `.claude/settings.json`, a project CLAUDE.md ("항상 한국어로 답하세요." / "常に日本語で答えてください。" / "请始终用中文回答。", each followed by "keep code, commands and file names as they are"), and the prompt. Prompts and CLAUDE.md texts are in `stage5.py` (`LANGS`).
- **Repository:** four small pure-Python projects with their own test suites, each copied at a fixed commit, without `.git` and `.github`, with upstream bug fixes reverted in the source and the tests that came with those fixes left in place, so the suite fails:
  - `jsonpointer`: python-json-pointer `9c4d3da`, the seven reverts of stages 3–4; tests `python3 -m unittest`.
  - `boltons`: mahmoud/boltons `d31d821`, six fixes (`73838fc`, `8a49b74`, `2ecf547`, `59bd0fb`, `435774e`, `1e61524`); tests `python3 -m pytest`.
  - `more-itertools`: more-itertools `aa99776`, six fixes (`fbd5513`, `67fcf64`, `7847d43`, `0e6acdf`, `958990e`, `f51a53b`); tests `python3 -m unittest`.
  - `toolz`: pytoolz/toolz `451af60`, three fixes (`d2eba03`, `5a7e078`, `e36b5ea`); tests `python3 -m pytest`.
  The exact reverted text is in `tasks/reverts.json` (generated from the upstream diffs) and `langleak.REAL_TASKS`.
- **Mode:** headless (`claude -p <prompt> --output-format stream-json --verbose`) or the interactive UI started in a pseudo-terminal by the same driver as the section-5 TUI check: it takes the default choice on start-up dialogs (folder trust), types the prompt once the input box is ready, and sends `/exit` once the transcript shows the turn ended.
- **Held constant:** prompt per language and repository ("fix every failing test; after each bug fix rerun the whole suite with <the repository's test command>"), `--setting-sources project`, `--permission-mode dontAsk`, `--allowedTools "Read Grep Glob Edit Write Bash(python3 *)"`, the Bash auto-approve hook of earlier stages, a 15-minute limit, one Mac, one account.
- **Environment checks before the batch:** (1) self-check: for every repository the upstream copy passes its own test command, the copy with all reverts fails, and the copy with each single revert fails; otherwise nothing runs. (2) A short Haiku call asks Claude Code's own Bash tool which `python3` and `pytest` it runs; the batch needs Python ≥ 3.11 with pytest (a venv made by the launcher, put first on PATH through a wrapper). (3) Claude Code's auto-updater is off for every run (`DISABLE_AUTOUPDATER=1`); the version is recorded and checked before every run, and the batch stops if it changes. All of this goes into `meta.json`.
- **Order:** 4 rounds; in each round the 72 conditions run in an order shuffled with the recorded seed. A run that ends in an error (usage limit, API error, no transcript, the prompt not in the transcript, the turn not ended, wrong model) is rerun in place and listed; it is not used.

## Scoring

- Both modes are scored from the same source: the session transcript Claude Code writes under `~/.claude/projects/`. Main-thread text blocks before the last tool call are progress messages (subagent traffic excluded), as in `langleak.parse_run`. For headless runs the stream-json is scored too and the agreement of the two sources is reported.
- Classifier: `langleak.classify` for Korean and for Japanese (with the corrected ASCII-only path rule from stage 3); for Chinese, Han characters are the target script, kana or Hangul without Han (or more kana than Han) is `other`, with the same 8-letter floor and 0.3 ratio (`stage5.classify`).
- **Primary outcome (strict, as in stages 2–4):** a run leaks if at least one progress message is `en` or `other` and is not a heading-only line.
- Secondary: any `en`/`other` progress message; `mixed` counted too; the position of the first leak; progress messages per run; non-target final answers.
- **Blind audit:** after the batch, every strict-leak message plus an equal-sized random sample of the other progress messages go into `audit_blind.csv`, shuffled, with no condition, mode or label. The owner of this repository labels them; agreement with the classifier is reported and any disagreement is reported next to the main numbers. The classifier result stays the primary result.

## Analysis

- **Primary test:** TUI vs headless on the strict outcome, exact conditional test of a common odds ratio of 1, stratified by model × language × repository (36 strata of 4 vs 4 runs), two-sided, α = 0.05; the Mantel–Haenszel odds ratio is reported with it. If fewer than 10 runs leak in total, the comparison is reported but not interpreted.
- **Descriptive (no tests, Wilson 95% intervals):** strict leak rate by mode, model, language and repository (each pooled over the other factors), model × mode and model × language tables.
- Interactions are not tested: 4 runs per cell are too few.

## How the result will be read

- Primary p < 0.05: the interface changes the rate, in the direction of the odds ratio, for these models, languages and repositories, with the driver-typed prompt.
- Otherwise: no evidence of a difference between the TUI and headless runs. With the heterogeneous rates seen so far, a simulation of this design gives about 99% power for an odds ratio of 0.25, 86% for 0.4 and 59% for 0.5; smaller differences can be missed.
- The descriptive rates say where the leak appears, with every user-side language setting on. They do not say why.

## Not covered

One task type (fixing failing tests) with one prompt per language; four small Python repositories; one Mac, one account, one Claude Code version; a driver, not a person, types into the TUI and exits after one turn; no multi-turn conversations.

## Running

`LangLeakScope5.app` on the same Mac as stages 1–4 runs `stage5.py run --claude <claude> --python <venv python> --seed 20261125 --n 4 --resume results/scope5/run_stage5` and retries every 5 minutes after an error stop (usage limit), skipping finished runs. Afterwards: `stage5.py analyze --dir results/scope5/run_stage5`.

---

## Amendment before any run (2026-11-25, 03:50 KST)

The first self-check on the Mac stopped the batch before any run, as planned: toolz's upstream suite failed one test, `toolz/tests/test_package.py::test_has_version`, which reads the version from the installed package metadata and so fails in a source checkout that was never `pip install`ed (every reverted copy failed it too). That file is removed from `tasks/toolz`; nothing else changes. All other self-check results passed: jsonpointer, boltons and more-itertools upstream suites passed, every single revert in them failed at least one test, and the three toolz reverts each failed their own test (`test_interpose_empty`, `test_partition_all`, `test_getter`). The self-check also now ignores errors while deleting its temporary folders. No stage-5 run had started.

Two operational guards were added at the same time, before any run: the batch stops if the Mac has less than 1 GB of free disk space (it was nearly full), and only the first 2 MB of each TUI terminal stream is kept (the stream is not used for scoring).

Correction after the first minutes of the batch (2026-11-25, 05:35 KST): Claude Code 2.1.311's folder-trust dialog defaults to "No, exit", so the driver's Enter closed the first two TUI sessions before the prompt was sent (logged as errors, no transcript, not used). The driver now selects "Yes, I trust this folder" on that dialog; nothing else changes. Two runs (both headless) had completed; they are kept, as they are unaffected.

---

## Results (added 2026-11-25, after all 288 runs)

Runs: 2026-11-25, 05:26–18:25 KST, on the same Mac, Claude Code 2.1.311 throughout (auto-updater off, version checked before every run), seed 20261125. All 288 cells were completed with the requested model. Six runs ended in an error and were rerun in place, as planned: two TUI sessions closed by the folder-trust dialog before the driver fix (see above), two that lost the network (`ENOTFOUND`), and two TUI sessions that spanned the laptop sleeping in transit (one timed out, one never showed its input box). The batch also stopped twice on the 1 GB disk guard and was restarted; finished runs were kept. Transcript and stream-json gave the same strict label in 144/144 headless runs. Files: `results/scope5/` (per-run table, every progress message, blind-audit sheet), raw logs in `raw/scope5.tgz` (transcripts reduced to the user/assistant messages used for scoring; the session's environment, tool and account attachments are removed; TUI terminal streams are not published).

### Primary

| | strict leak runs |
|---|---|
| TUI | 41/144 (28%, 95% CI 22–36%) |
| headless | 44/144 (31%, 24–39%) |

Exact conditional test stratified by model × language × repository (36 strata): Mantel–Haenszel OR = 0.86, **p = 0.75**. More than 10 runs leaked, so the comparison is interpreted: no evidence that the interactive UI leaks at a different rate from headless runs. Per model the two modes were close: Opus 20/48 vs 20/48, Sonnet 14/48 vs 17/48, Haiku 7/48 vs 7/48 (TUI vs headless).

### Descriptive (strict outcome, pooled over the other factors)

| factor | level | leak runs |
|---|---|---|
| model | Opus 5.5 | 40/96 (42%, 32–52%) |
| | Sonnet 5.5 | 31/96 (32%, 24–42%) |
| | Haiku 5.5 | 14/96 (15%, 9–23%) |
| language | Korean | 25/96 (26%, 18–36%) |
| | Japanese | 32/96 (33%, 25–43%) |
| | Chinese | 28/96 (29%, 21–39%) |
| repository | jsonpointer | 15/72 (21%, 13–32%) |
| | boltons | 23/72 (32%, 22–43%) |
| | more-itertools | 43/72 (60%, 48–70%) |
| | toolz | 4/72 (6%, 2–13%) |

Model × language: Opus ko 9/32, ja 17/32, zh 14/32; Sonnet 8/32, 12/32, 11/32; Haiku 8/32, 3/32, 3/32. Repository × model: more-itertools Opus 20/24, Sonnet 17/24, Haiku 6/24; toolz Opus 4/24, Sonnet 0/24, Haiku 0/24.

- In 62 of the 85 leaking runs the first English message was the first progress message. 126 progress messages were strict leaks; the most common was still "Let me look at the relevant tests." and close variants, but on these repositories many were mid-task explanations of a bug in English ("Outside a handler, `full_trace` is never set. I'll add a class-level default."). Ten runs had three or more English progress messages, six of them Haiku or Sonnet; in one Haiku run (Chinese, more-itertools, headless) every progress message and the final answer were English, the only non-target final answer in the batch.
- With every user-side language setting on, the leak appeared in all three models, all three languages and all four repositories, in both interfaces; its rate depended far more on the repository (6% to 60%) and the model than on the language or the interface.

### Not pre-registered (exploratory)

On python-json-pointer, Opus with Korean leaked in 0/8 runs here, against 27/40 in stages 3–4, where only the CLAUDE.md sentence was set (stage 5 also sets `"language": "korean"` and runs on another day). This points at the `language` setting helping on that repository (Fisher p = 0.0005 for 0/8 vs 27/40), but it is a comparison across batches that this design did not plan, and with every setting on Opus/Korean still leaked in 6/8 runs on more-itertools. A direct test would put the `language` setting on and off within one batch.

### Classifier audit

`results/scope5/audit_blind.csv` holds the 126 strict-leak messages and 126 random other progress messages, shuffled, with no condition or label; the key is kept out of the repository until the audit is done. Its result will be added here.
