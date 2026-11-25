# Claude Code writes its between-tool progress notes in English: a controlled measurement

When the user writes in Korean and Claude Code works through a tool loop, the short progress messages it writes between tool calls ("Money fixed (10/18). Next: tax.") often come out in English. In most runs where this happened, the first progress message was already English: it is less a mid-task drift than English narration from the start of the loop. The last answer of the turn was Korean in all 274 single-turn runs; one run had an English line ("I'm waiting for the results of the final run.") after its last tool call, before the Korean report. This repo holds a small harness that reproduces the behaviour on synthetic repositories, the raw and per-run results, and what changed the rate.

Related issues: [anthropics/claude-code#32181](https://github.com/anthropics/claude-code/issues/32181), [#96326](https://github.com/anthropics/claude-code/issues/96326), [#96601](https://github.com/anthropics/claude-code/issues/96601).

**Short version.** With a Korean prompt, the `language` setting and generic CLAUDE.md rules ("always answer in Korean", or a longer insistent version) still left English progress messages in about a quarter to nearly half of runs in the comparisons below. Of the CLAUDE.md texts tried, the ones that explicitly covered the progress notes between tool calls leaked in 1 of 48 runs, against 12 of 32 for the two that did not. A pre-registered follow-up on one task separated scope from naming: "write all user-visible text in Korean" leaked in 13 of 48 runs, "write the short notes you leave while working in Korean too" in 3 of 48 (p = 0.012). So the clause naming the during-work notes did more than broadening the rule, though neither removed the English entirely. A third pre-registered stage (section 6) then tried other models, Japanese and a real repository: under "always answer" the English notes showed up on Sonnet 5.5 (4/16), in Japanese (5/16) and on the real repository (10/16), but the during-work wording did not reduce them significantly anywhere, and on the real repository it left English in 8 of 16 runs. A fourth stage put "always answer in Korean" in the system prompt (`--append-system-prompt`) instead of CLAUDE.md: 16/24 against 17/24, no difference. On the real repository the leak was nearly always one opening line, "(Now) let me look at the relevant tests.", and none of the user-side texts tried here stopped it. A fifth pre-registered stage (section 7, 288 runs) then switched on every user-side setting at once (`language`, CLAUDE.md and the prompt in the same language) and crossed three models, three languages and four real repositories with headless and interactive sessions: the English notes appeared in every model, language and repository, at the same rate in the interactive UI as headless (28% vs 31%, p = 0.75), and far more often on some repositories (60%) than others (6%). A sixth stage switched only the `language` setting on and off within one batch (Opus, Korean, two repositories, 96 runs): 30/48 vs 31/48, p = 1.00. So none of the user-side options tried here prevents the opening English line. Localising the repository's docs, logs and test output into Korean did not change the rate detectably.

## Setup

- Claude Code 2.1.311, headless (`claude -p --output-format stream-json`), model `claude-opus-5-5` unless noted. Experiment v3 also ran `claude-sonnet-5-5` and `claude-fable-5-2`. A keyword search of the Claude Code changelog through 2.1.330 found no entry about this behaviour, which does not show that later versions behave the same.
- `--setting-sources project`, so only the fixture's own `.claude/settings.json` applies. No user-level CLAUDE.md was present.
- Each run starts in a fresh temp copy of a synthetic Python repo with 8 seeded bugs, a spec and an operations log. The prompt (Korean) asks Claude to fix all failing tests and rerun the suite after each fix.
- Two codebases: `ledger` (money, tax, discount, invoice, dates, currency, csv, report) and `textkit` (slug, word count, truncate, title, duration, html, palindrome, plural).
- Only main-thread assistant text is scored (`parent_tool_use_id` is null). Subagent output is excluded. A **progress message** is an assistant text block written before the run's last tool call; text after it is the answer.

**Classifier.** Code blocks, inline code, URLs, paths, identifiers, file names and `foo()` calls are stripped. A message with no Hangul and at least 8 Latin letters is `en`; no Hangul but kana/CJK is `other` (one run switched to Japanese); a Hangul share of 30% or more of letters is `ko`; anything between is `mixed`. A run "leaks" if at least one progress message is `en` or `other`. `mixed` does not count as a leak.

**Classifier check.** The v4 audit sample has 150 random progress messages (`results/output-language/audit_sample.csv`). The 5 the classifier labelled `empty` were left out of the blind review; they are short headers, all English ("Fix 1: slug", "**4. title**", "**6. html**", "Fix 1: slug.", "**8. plural**"). The other 145 were labelled ko / en / mixed without seeing the classifier's labels: a second model (GPT) drafted the labels and the author reviewed each one (`audit_blind_review.csv`). Within those 145 the two agreed on English-or-not for all 145 (47 English) and on the three-way label for 140; the 5 disagreements were between ko and mixed. So the classifier missed short English headers, and the audit says nothing about its accuracy on other batches or the TUI transcripts. See also the sensitivity check below.

## Conditions

| name | what it is |
|---|---|
| base | no language instruction |
| lang | `.claude/settings.json` → `"language": "korean"` |
| claudemd | project `CLAUDE.md`: "사용자에게 보이는 모든 문장은 한국어로 작성하세요. 도구 호출 사이의 진행 설명도 포함입니다. 코드·명령어·파일명은 원문 그대로 둡니다." |
| claudemd_min | project `CLAUDE.md`: "항상 한국어로 답하세요." ("Always answer in Korean.") |

## Results

Leak rate is per run with a Wilson 95% interval. Tests are two-sided Fisher exact on run counts.

### 1. Localising docs, logs and test output did not change the rate detectably (v4, n = 64)

v4 crossed task (ledger / textkit) × the language of README, SPEC, logs and test-runner output (en / ko) × instruction (base / lang), 8 runs per cell. The code and its identifiers were identical between en and ko, so this changes all of those at once; it does not isolate tool output alone.

| | leak runs | non-Korean progress messages |
|---|---|---|
| output en | 14/32 (44%, 28–61%) | 67/194 |
| output ko | 14/32 (44%, 28–61%) | 54/161 |
| base | 20/32 (62%, 45–77%) | 109/176 (62%) |
| lang | 8/32 (25%, 13–42%) | 12/179 (7%) |

- Output language, within base: 9/16 vs 11/16, p = 0.72.
- Output language, within lang: 5/16 vs 3/16, p = 0.69.
- base vs lang, Korean output: 11/16 vs 3/16, p = 0.011.
- base vs lang, English output: 9/16 vs 5/16, p = 0.29.
- base vs lang, both outputs: 20/32 vs 8/32, p = 0.005.

Both output languages gave 14/32 leaking runs and about a third of progress messages non-Korean (67/194 vs 54/161). With 32 runs per arm the 95% interval for the difference is about −23 to +23 points, so a moderate effect is still possible. In this setup the `language` setting lowered the leak rate (20/32 → 8/32) and cut non-Korean messages about 9×, but a quarter of runs still had some.

### 2. Texts that covered the progress notes leaked less (v8 + v10, n = 80)

The `wording` experiment reran the English-output v4 cells with five CLAUDE.md texts. Permissions were identical to v4, so most runs also hit denials. v8 (explicit vs one line) ran first; v10 (the other three texts) was designed after seeing v8 and ran three hours later.

| CLAUDE.md | names the progress messages? | leak runs | non-Korean progress messages |
|---|---|---|---|
| explicit (Korean, 3 sentences) | yes | 0/16 (0%, 0–19%) | 0/174 |
| progress clause only: "도구 호출 사이의 진행 설명도 한국어로 작성하세요." ("Write the progress notes between tool calls in Korean too.") | yes | 0/16 (0%, 0–19%) | 0/178 |
| explicit, written in English | yes | 1/16 (6%, 1–28%) | 1/145 |
| one line: "항상 한국어로 답하세요." ("Always answer in Korean.") | no | 6/16 (38%, 18–61%) | 6/87 |
| emphatic: "Every answer must be in Korean. Do not answer in English. Keep code, commands and file names as they are." (in Korean) | no | 6/16 (38%, 18–61%) | 6/68 |
| *`language` setting (v4, same cells, earlier batch)* | – | 5/16 (31%, 14–56%) | 5/91 |
| *no instruction (v4, same cells, earlier batch)* | – | 9/16 (56%, 33–77%) | 62/103 |

Within each batch the direction is the same: v8 0/16 vs 6/16, v10 1/32 vs 6/16. Pooled, the three texts that covered the progress notes leaked in 1 of 48 runs and the two that did not in 12 of 32 (Fisher p ≈ 0.00004). Treat this as exploratory: v10 was designed after v8, the contrast was not fixed in advance, and with all ten pairwise comparisons Holm-corrected the single v8 comparison (p = 0.018) would not stand alone. The texts also differ in length, scope and wording at once. In particular, the one-line and emphatic texts both say "answer"; the model may read that as the final answer only, and no text here covered "all user-visible text" without naming the progress notes. The 0/16 results for the two Korean texts that named them do not show that they are equally effective, and the similar rates for the one-liner and the `language` setting (an earlier batch) do not show that the instruction's location is irrelevant.

**Stage 1 follow-up (pre-registered, `PREREG_scope.md`).** On `textkit` without denials, four CLAUDE.md texts with the same closing sentence: "all user-visible text in Korean" 6/16, "the short notes you leave while working, too" 0/16, "the progress notes between tool calls, too" 0/16, "always answer in Korean" 11/16. The pre-registered comparison of the first two passed (p = 0.018) but not when header-only lines like "**3. truncate**" are excluded (4/16 vs 0/16, p = 0.10), so a larger stage 2 of that comparison was pre-registered in `PREREG_scope2.md`, with heading-only lines excluded from the primary outcome. **Stage 2:** "all user-visible text" 13/48 vs "the short notes you leave while working, too" 3/48 (strict outcome, p = 0.012; 16/48 vs 3/48 counting every English line). In this setup, naming the during-work notes helped beyond a broad scope rule, though it did not remove the English entirely.

As raw counts only (different models, tasks, times, permissions and units): every run or session that used the Korean explicit text or the progress clause had no leak (v2 6 runs, v3 10 runs over three models, v5 3 sessions, v7 8, v8 16, v10 16; 0 of 59). Runs with the `language` setting alone leaked in 22 of 77 (v3 0/10, v4 8/32, v5 3/3 sessions, v6 6/8, v7 1/8, v9 4/16); 3 of the v3 runs were Fable runs that wrote no progress messages at all, so could not leak. These pooled counts are not a risk estimate for other settings.

**Sensitivity.** Counting `mixed` messages as leaks too: explicit-or-clause texts 3/48 vs 16/32 (the two Korean texts stay at 0/32), v4 en vs ko 18/32 vs 14/32. Lowering the English floor from 8 to 7 letters: v4 en and ko each 16/32, wording 1/48 vs 14/32. The weak instructions leak more under looser definitions; the explicit Korean texts stay at zero.

### 3. English progress notes from the start of the tool loop (v4, v5, v8–v10)

v5 ran 16 consecutive Korean turns per session with `claude -p -c` (fix bugs, review each file, write scripts, add tests, add type hints, benchmark, write a changelog…), 3 sessions per condition, about 100 tool calls per session.

| | sessions with a leak | non-Korean progress messages | non-Korean turn answers |
|---|---|---|---|
| base | 2/3 | 19/47 | 0/48 |
| lang | 3/3 | 6/49 | 0/48 |
| claudemd | 0/3 | 0/114 | 0/48 |

17 of base's 19 English messages were in turn 1, the 28-tool bug-fixing turn; later turns leaked rarely. The later turns also differ in task and tool count, so this does not separate turn length from the effect of a fresh Korean message. With the `language` setting the pattern differed (turn 1: 1/25, later turns: 5/24). No turn's final answer was non-Korean.

In the single-turn experiments most leaks did not start after Korean narration. In 24 of 28 leaking v4 runs, 11 of 13 in `wording` and 10 of 11 in `no-denials`, no Korean progress message came before the first non-Korean one. The first leak came either right after the first tool calls (tool call 2–5) or, in about half of the leaking v4 runs, when the model started fixing after reading the code (tool call 11–15); either way it was usually the first narration the run wrote.

### 4. Leaks occur right after permission denials and without them (v6, v7, v9)

Many leaks begin with "I'll use the Read tool instead." right after a `Permission to use Bash has been denied` tool result. Every v4 run hit at least one denial, because only `Bash(python3 *)` was allowed.

Splitting v4 and v8 leaks by what came just before the first non-Korean message:

| | leaking runs | first non-Korean message right after a denial |
|---|---|---|
| no instruction (v4) | 20 | 7 |
| `language` setting (v4) | 8 | 7 |
| one-line CLAUDE.md (v8) | 6 | 5 |

Without an instruction, 102 of the 109 English messages followed an ordinary tool result. With a weak instruction, most leaking runs started right after a denial, often with "I'll use the Read tool instead."

- v6: all 16 runs hit a denial, and in all 12 leaking runs the first non-Korean message came right after one. The v6 "allow" arm did not remove denials, because the model chains commands with `for` loops.
- v7 fixed this with a PreToolUse hook that auto-approves non-destructive shell commands inside the workspace. Denials dropped from 11/12 runs to 1/12.

| v7 | deny | allow |
|---|---|---|
| base | 2/4 | 1/4 |
| lang | 1/4 | 0/4 |
| claudemd | 0/4 | 0/4 |

n = 4 per cell is too small to show an effect (3/12 vs 1/12 overall, p = 0.59), so v9 repeated the two weak instructions with the auto-approve hook at n = 8 per cell. One run of 32 (`ledger.en.lang/run_06`, no leak) still hit a denial.

| v9, no denials | leak runs | leaks starting right after a denial |
|---|---|---|
| `language` setting | 4/16 assigned (25%, 10–49%); 4/15 with no denial (27%, 11–52%) | 0/4 |
| one-line CLAUDE.md | 7/16 (44%, 23–67%) | 0/7 |

Comparable cells with denials, from earlier batches: `language` 5/16 (v4, English output), one-liner 6/16 (v8). All 11 v9 leaks happened in runs with no denial, so denials are not necessary for a leak; how much a denial raises the risk is not estimated by this data. Without denials the first leak came at the planning note after the first test run ("Fix them one by one, running the whole test suite after each.", "Fix 1/8: slug (SPEC §1)"). The task mattered in both directions (wording: ledger 11/40 vs textkit 2/40; no-denials: ledger 2/16 vs textkit 9/16), which this data cannot explain.

### 5. Interactive TUI check (n = 8)

Every run above used headless `claude -p`. As a check on the interactive UI, 8 sessions ran on the same Mac (2026-11-23, 22:25–22:35 KST) with Claude Code 2.1.311 and the same flags (`--model opus --setting-sources project --permission-mode dontAsk --allowedTools …`) and the auto-approve hook, so no session hit a denial. A driver (`tui/tui_auto.py`) started the UI in a pseudo-terminal, took the default choice on start-up dialogs, typed the prompt, and sent `/exit` when the turn ended. Each session loaded only its own workspace CLAUDE.md (`tui/loaded_memory_files.tsv`).

| CLAUDE.md | sessions with a leak | non-Korean progress messages |
|---|---|---|
| one line ("always answer in Korean") | 0/4 | 0/30 |
| explicit | 0/4 | 0/35 |

No session leaked. The comparable headless cell (`ledger`, English output, one-line text, no denials) had 1/8, at which 0 of 4 happens about 59% of the time; the upper 95% bound for 0/4 is 49%. This check is too small to say whether the interactive UI behaves differently or whether either text works better there. Scoring used the session transcripts, not the rendered screen.

### 6. Stages 3–4: other models, Japanese, a real repository, the system prompt (n = 128 + 48, pre-registered)

`PREREG_scope3.md` has the plan and the full write-up. Four arms, each changing one thing from stages 1–2, each comparing "always answer in Korean/Japanese" (A) with "write the short notes you leave while working in Korean/Japanese too" (B), 16 runs per condition, strict outcome:

| arm | A | B | Fisher p |
|---|---|---|---|
| Sonnet 5.5, Korean, synthetic | 4/16 | 1/16 | 0.33 |
| Haiku 5.5, Korean, synthetic | 1/16 | 4/16 | 0.33 (below the pre-registered gate, not interpreted) |
| Opus 5.5, Japanese, synthetic | 5/16 | 2/16 | 0.39 |
| Opus 5.5, Korean, real repository | 10/16 | 8/16 | 0.72 |

The real repository is [python-json-pointer](https://github.com/stefankoegl/python-json-pointer) with seven of its own upstream fixes reverted (the tests that came with them fail). There, every leaking run had a single English line, "(Now) let me look at the relevant/failing tests.", almost always as the first progress message. Haiku leaked differently: when it did, most or all of its progress messages were English. The Japanese row uses a corrected classifier: the pre-registered one mislabelled Japanese messages that contain a slash (the B cell was 4/16 with it); see the deviation note in `PREREG_scope3.md`.

Stage 4 (`PREREG_scope4.md`, pre-registered) repeated the real-repository setting with "always answer in Korean" in CLAUDE.md (17/24) against the same sentence appended to the system prompt with `--append-system-prompt` (16/24), p = 1.00. Every leak was the first progress message and nothing else, in 32 of 33 runs a variant of "(Now) let me look at the relevant/failing tests."

### 7. Stage 5: every setting on, 3 models × 3 languages × 4 real repositories × headless/TUI (n = 288, pre-registered)

`PREREG_scope5.md` has the plan, the amendments made before and during the batch, and the full write-up. Every run had `"language"`, a CLAUDE.md rule and the prompt in Korean, Japanese or Chinese; the repositories were python-json-pointer, boltons, more-itertools and toolz, each with several of its own upstream fixes reverted. Both interfaces were scored from the session transcript.

| | strict leak runs |
|---|---|
| interactive UI (TUI) | 41/144 (28%) |
| headless `claude -p` | 44/144 (31%) |
| Opus / Sonnet / Haiku 5.5 | 40/96 (42%) / 31/96 (32%) / 14/96 (15%) |
| Korean / Japanese / Chinese | 25/96 (26%) / 32/96 (33%) / 28/96 (29%) |
| jsonpointer / boltons / more-itertools / toolz | 15/72 (21%) / 23/72 (32%) / 43/72 (60%) / 4/72 (6%) |

The pre-registered test of TUI vs headless, stratified by model × language × repository, found no difference (Mantel–Haenszel OR 0.86, p = 0.75). So the earlier headless numbers are not an artefact of `claude -p`. Most leaks again started at the first progress message (62/85), but here they also included mid-task explanations of a bug in English, and some Haiku and Sonnet runs were mostly English. A blind human audit of 252 progress messages agreed with the classifier on leak / no leak for 249; the 3 misses were short English lines the classifier did not count. One unplanned comparison (Opus/Korean on python-json-pointer leaked in 0/8 runs with the `language` setting on, against 27/40 with only CLAUDE.md in stages 3–4) was tested directly in stage 6 (`PREREG_scope6.md`) and did not hold: 12/24 with the setting on vs 9/24 off, and 30/48 vs 31/48 over two repositories (p = 1.00).

## Limitations

- Stages 1–4 are headless `-p` runs. Stage 5 (section 7) adds 144 interactive sessions, but they are driven through a pseudo-terminal (one prompt, then `/exit`), not typed by a person, and there are no multi-turn conversations.
- Before stage 3, synthetic small repositories, Korean, and `claude-opus-5-5`. Stages 3–5 add Sonnet and Haiku 5.5, Japanese and Chinese, and four small Python repositories; one task type (fixing failing tests) throughout. #96601 reports the rate rose from Opus 5 to Opus 5.5; this repo has no Opus 5 comparison.
- n is 3–8 per cell and the intervals are wide. The clearest results are base vs `language` setting in v4 and the within-batch wording contrasts in v8 and v10; the wording result is exploratory (v10 designed after v8) and does not identify which part of the text matters. Comparisons across batches (v4 vs v8 vs v9) are confounded with time of day.
- One Claude Code version (2.1.311), one Mac, one account. Headless runs: 2026-11-22 14:47 to 2026-11-23 00:20 KST, by the first and last run logs (v4's `meta.json` start time is when the script was launched; it then waited for a usage reset). TUI check: 2026-11-23.
- Stages 3–5 have 4–24 runs per cell, enough only for large differences; stage 5 cannot test interactions (4 runs per cell). One prompt per language.

## Reproduce

```
python3 langleak.py --list                                  # experiments and their conditions
python3 langleak.py run output-language --n 8 --model opus  # about one minute per run
python3 langleak.py analyze output-language                 # latest results dir
```

`langleak.py` runs the single-turn experiments. Results go to `results/<experiment>/<timestamp>/<condition>/run_NN.jsonl` (raw stream-json). `analyze` prints per-condition and marginal leak rates, Fisher tests and denial timing, and writes `summary_runs.csv` and `audit_sample.csv`. Touch `results/<experiment>/STOP` to stop after the current run; `--resume <dir>` continues an interrupted run, and the script stops by itself after three errors in a row (for example a usage limit).

`python3 langleak.py fixture <task> <olang> <instruction> <deny|allow> <dir>` writes a single workspace, for trying a condition by hand in the interactive TUI.

Move `~/.claude/CLAUDE.md` aside while running, since Claude Code loads it regardless of `--setting-sources`.

| run label in this README | experiment | n per cell |
|---|---|---|
| v4 | `output-language` | 8 |
| v7 | `permissions` | 4 |
| v8, v10 | `wording` (v8: explicit and one-line; v10: the other three) | 8 |
| v9 | `no-denials` | 8 |
| stage 1 | `scope`, see `PREREG_scope.md` | 16 |
| stage 2 | `scope2`, see `PREREG_scope2.md` | 48 |
| stage 3 | `scope3`, see `PREREG_scope3.md` (needs `--python-real`, a Python ≥ 3.10.7; `python3 langleak.py selfcheck --python <it>` checks the real-repository task first) | 16 |
| stage 4 | `scope4`, see `PREREG_scope4.md` (real repository only; CLAUDE.md vs `--append-system-prompt`) | 24 |
| stage 5 | `stage5.py run`, see `PREREG_scope5.md` (models × languages × 4 real repositories × headless/TUI; needs a Python ≥ 3.11 with pytest) | 4 |
| stage 6 | `stage5.py run --experiment scope6`, see `PREREG_scope6.md` (Opus, Korean, `language` setting on vs off, 2 repositories) | 24 |

`tasks/jsonpointer` is an unmodified copy of python-json-pointer (BSD-3-Clause) used by stage 3; see `tasks/NOTICE.md`.

`legacy/` holds the scripts for the other runs, unchanged from when they ran (some console messages are in Korean): `langleak2.py` (instruction × subagent), `langleak3.py` (three models), `langleak5.py` (16-turn sessions with `-c`), `langleak6.py` (first denial experiment). Their per-run tables are in `results/legacy/`.

`tui/` holds the interactive-check driver and scorer (`python3 tui/tui_analyze.py <transcript.jsonl>`).

`raw/` holds the stream-json of every run reported here, with local paths, the user name, account identifiers and the list of installed commands and connectors removed or replaced by placeholders (`tui-check.tgz` keeps only the message records). `langleak.py analyze <experiment> --dir <extracted dir>` reproduces the tables from it.

## License

MIT
