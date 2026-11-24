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
