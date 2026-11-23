# Claude Code switches to English mid-task: a controlled measurement

When the user writes in Korean and Claude Code works through a long tool loop, the short progress messages it writes between tool calls ("Money fixed (10/18). Next: tax.") often come out in English. The final answer of the turn stays Korean (one exception in 274 single-turn runs, in a run that delegated to an English-prompted subagent). This repo holds a small harness that reproduces the switch on synthetic repositories, the raw and per-run results, and what changed the rate.

Related issues: [anthropics/claude-code#32181](https://github.com/anthropics/claude-code/issues/32181), [#96326](https://github.com/anthropics/claude-code/issues/96326), [#96601](https://github.com/anthropics/claude-code/issues/96601).

**Short version.** Tool-output language made no difference. The `language` setting and a one-line CLAUDE.md ("always answer in Korean") each cut the switch but still left it in 25–44% of runs, with or without permission denials. What held was a CLAUDE.md sentence that names the progress messages between tool calls: 0 leaks in 59 runs in Korean, and 1 in 16 when written in English. A longer, more insistent instruction that does not name them leaked as often as the one-liner.

## Setup

- Claude Code 2.1.311, headless (`claude -p --output-format stream-json`), model `claude-opus-5-5` unless noted. Experiment v3 also ran `claude-sonnet-5-5` and `claude-fable-5-2`. The Claude Code changelog through 2.1.330 lists no change to this behavior.
- `--setting-sources project`, so only the fixture's own `.claude/settings.json` applies. No user-level CLAUDE.md was present.
- Each run starts in a fresh temp copy of a synthetic Python repo with 8 seeded bugs, a spec and an operations log. The prompt (Korean) asks Claude to fix all failing tests and rerun the suite after each fix.
- Two codebases: `ledger` (money, tax, discount, invoice, dates, currency, csv, report) and `textkit` (slug, word count, truncate, title, duration, html, palindrome, plural).
- Only main-thread assistant text is scored (`parent_tool_use_id` is null). Subagent output is excluded. A **progress message** is an assistant text block written before the run's last tool call; text after it is the answer.

**Classifier.** Code blocks, inline code, URLs, paths, identifiers, file names and `foo()` calls are stripped. A message with no Hangul and at least 8 Latin letters is `en`; no Hangul but kana/CJK is `other` (one run switched to Japanese); a Hangul share of 30% or more of letters is `ko`; anything between is `mixed`. A run "leaks" if at least one progress message is `en` or `other`. `mixed` does not count as a leak.

**Classifier check.** 145 progress messages sampled at random from v4 (`results/output-language/audit_blind_review.csv`) were labelled ko / en / mixed without seeing the classifier's labels: a second model (GPT) drafted the labels and the author reviewed each one. On the question the leak counts depend on, English or not, the two agreed on all 145 (47 English, no false positives or misses). On the three-way label they agreed on 140; the 5 disagreements were all between ko and mixed (e.g. "Bug 8: report — 단수형 처리."), which are both counted as no leak. Short English headers such as "Fix 1: slug" fall under the 8-letter floor and are labelled `empty`, so the leak counts are, if anything, lower bounds.

## Conditions

| name | what it is |
|---|---|
| base | no language instruction |
| lang | `.claude/settings.json` → `"language": "korean"` |
| claudemd | project `CLAUDE.md`: "사용자에게 보이는 모든 문장은 한국어로 작성하세요. 도구 호출 사이의 진행 설명도 포함입니다. 코드·명령어·파일명은 원문 그대로 둡니다." |
| claudemd_min | project `CLAUDE.md`: "항상 한국어로 답하세요." ("Always answer in Korean.") |

## Results

Leak rate is per run with a Wilson 95% interval. Tests are two-sided Fisher exact on run counts.

### 1. Tool-output language does not matter (v4, n = 64)

v4 crossed task (ledger / textkit) × the language of README, SPEC, logs and test-runner output (en / ko) × instruction (base / lang), 8 runs per cell. The code and its identifiers were identical between en and ko.

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

Making the logs, spec and test output Korean did not reduce the switch. The model writes "Money fixed (10/18). Next: tax." just as often when the test runner prints Korean. The `language` setting cuts the number of English messages by about 9×, but a quarter of runs still contain some.

### 2. Naming the progress messages is what holds (v8 + v10, n = 80)

The `wording` experiment reran the English-output v4 cells with five CLAUDE.md texts. Permissions were identical to v4, so most runs also hit denials.

| CLAUDE.md | names the progress messages? | leak runs | non-Korean progress messages |
|---|---|---|---|
| explicit (Korean, 3 sentences) | yes | 0/16 (0%, 0–19%) | 0/174 |
| progress clause only: "도구 호출 사이의 진행 설명도 한국어로 작성하세요." ("Write the progress notes between tool calls in Korean too.") | yes | 0/16 (0%, 0–19%) | 0/178 |
| explicit, written in English | yes | 1/16 (6%, 1–28%) | 1/145 |
| one line: "항상 한국어로 답하세요." ("Always answer in Korean.") | no | 6/16 (38%, 18–61%) | 6/87 |
| emphatic: "Every answer must be in Korean. Do not answer in English. Keep code, commands and file names as they are." (in Korean) | no | 6/16 (38%, 18–61%) | 6/68 |
| *`language` setting (v4, same cells)* | – | 5/16 (31%, 14–56%) | 5/91 |
| *no instruction (v4, same cells)* | – | 9/16 (56%, 33–77%) | 62/103 |

Pooled, the three texts that name the progress messages leaked in 1 of 48 runs and the two that do not in 12 of 32 (p < 0.001). The progress clause alone works as well as the full explicit text; length and insistence without it do nothing beyond the one-liner (6/16 vs 6/16). A one-line CLAUDE.md behaves like the `language` setting, so the location of the instruction is not what matters.

Across every experiment that used the Korean explicit text or the progress clause (v2 6 runs, v3 10 runs over three models, v5 3 long sessions, v7 8 runs, v8 16, v10 16), 0 of 59 leaked (Wilson upper bound 6%). In v3–v9 the `language` setting alone leaked in 22 of 77 runs or sessions (v3 0/10, v4 8/32, v5 3/3, v6 6/8, v7 1/8, v9 4/16).

### 3. The switch happens during long autonomous tool loops, not in answers (v5)

v5 ran 16 consecutive Korean turns per session with `claude -p -c` (fix bugs, review each file, write scripts, add tests, add type hints, benchmark, write a changelog…), 3 sessions per condition, about 100 tool calls per session.

| | sessions with a leak | non-Korean progress messages | non-Korean turn answers |
|---|---|---|---|
| base | 2/3 | 19/47 | 0/48 |
| lang | 3/3 | 6/49 | 0/48 |
| claudemd | 0/3 | 0/114 | 0/48 |

17 of base's 19 English messages were in turn 1, the 28-tool bug-fixing turn. Later turns with fewer tool calls rarely leaked. A new Korean user message pulled the progress messages back to Korean. No turn's final answer was ever non-Korean.

### 4. Weak instructions often break at a permission denial, but removing denials did not lower the rate (v6, v7, v9)

Many leaks begin with "I'll use the Read tool instead." right after a `Permission to use Bash has been denied` tool result. Every v4 run hit at least one denial, because only `Bash(python3 *)` was allowed.

Splitting v4 and v8 leaks by what came just before the first non-Korean message:

| | leaking runs | first non-Korean message right after a denial |
|---|---|---|
| no instruction (v4) | 20 | 7 |
| `language` setting (v4) | 8 | 7 |
| one-line CLAUDE.md (v8) | 6 | 5 |

Without an instruction, the model drifts into English anywhere in the loop: 102 of its 109 English messages followed an ordinary tool result. With a weak instruction, it mostly holds until a denial, then writes "I'll use the Read tool instead." in English.

- v6: all 16 runs hit a denial, and in all 12 leaking runs the first non-Korean message came right after one. The v6 "allow" arm did not remove denials, because the model chains commands with `for` loops.
- v7 fixed this with a PreToolUse hook that auto-approves non-destructive shell commands inside the workspace. Denials dropped from 11/12 runs to 1/12.

| v7 | deny | allow |
|---|---|---|
| base | 2/4 | 1/4 |
| lang | 1/4 | 0/4 |
| claudemd | 0/4 | 0/4 |

n = 4 per cell is too small to show an effect, so v9 repeated the two weak instructions with the auto-approve hook at n = 8 per cell. One run of 32 still hit a denial.

| v9, no denials | leak runs | leaks starting right after a denial |
|---|---|---|
| `language` setting | 4/16 (25%, 10–49%) | 0/4 |
| one-line CLAUDE.md | 7/16 (44%, 23–67%) | 0/7 |

The rates match the runs with denials (v4 `language` 8/32; v8 one-liner 6/16). Without denials the switch came at the same kind of moment: the planning message right after the first test run ("Fix them one by one, running the whole test suite after each.", "Fix 1/8: slug (SPEC §1)"). A denial is one of the points where the model writes a short self-directed note and that note comes out in English; it is not what causes the switch. The task mattered in both directions (wording: ledger 11/40 vs textkit 2/40; no-denials: ledger 2/16 vs textkit 9/16), which this data cannot explain.

### 5. Interactive TUI check (n = 8)

Every run above used headless `claude -p`. As a check on the interactive UI, 8 sessions ran on the same Mac with Claude Code 2.1.311 and the same flags (`--model opus --setting-sources project --permission-mode dontAsk --allowedTools …`) and the auto-approve hook, so no session hit a denial. A driver (`tui/tui_auto.py`) started the UI in a pseudo-terminal, took the default choice on start-up dialogs, typed the prompt, and sent `/exit` when the turn ended. Each session loaded only its own workspace CLAUDE.md (`tui/loaded_memory_files.tsv`).

| CLAUDE.md | sessions with a leak | non-Korean progress messages |
|---|---|---|
| one line ("always answer in Korean") | 0/4 | 0/30 |
| explicit | 0/4 | 0/35 |

No session switched. At the headless rate for the one-line CLAUDE.md without denials (7/16), 0 of 4 would happen about 10% of the time, so this neither shows that the interactive UI behaves differently nor confirms the headless rate there. It does show the explicit text holding in the UI.

## Limitations

- All measured rates come from headless `-p` runs. The interactive check (section 5) is 8 sessions, driven through a pseudo-terminal rather than typed by a person.
- Synthetic, small repositories, one natural language (Korean), and one main model (`claude-opus-5-5`) for most runs. #96601 reports the rate rose from Opus 5 to Opus 5.5; this repo has no Opus 5 comparison.
- n is 3–8 per cell and the intervals are wide. The firm results are the null effect of output language, base vs `language` setting, and naming vs not naming the progress messages; the rest is directional. The v10 wordings were designed after seeing v8.
- One Claude Code version (2.1.311), all runs on 2026-11-22.

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

`legacy/` holds the scripts for the other runs, unchanged from when they ran (some console messages are in Korean): `langleak2.py` (instruction × subagent), `langleak3.py` (three models), `langleak5.py` (16-turn sessions with `-c`), `langleak6.py` (first denial experiment). Their per-run tables are in `results/legacy/`.

`tui/` holds the interactive-check driver and scorer (`python3 tui/tui_analyze.py <transcript.jsonl>`).

`raw/` holds the stream-json of every run reported here, with local paths, the user name, account identifiers and the list of installed commands and connectors removed or replaced by placeholders (`tui-check.tgz` keeps only the message records). `langleak.py analyze <experiment> --dir <extracted dir>` reproduces the tables from it.

## License

MIT
