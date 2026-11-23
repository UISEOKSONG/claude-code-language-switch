# Pre-registration: `scope` experiment (stage 1)

Written and committed before any `scope` run. Results will be added below this plan without changing it.

## Question

The `wording` experiment found that CLAUDE.md texts naming the progress notes between tool calls leaked less than generic ones ("always answer in Korean"). The generic texts all said "answer", so the difference may come from scope (the model reading "answer" as the final answer only) rather than from naming the progress notes. This stage separates the two.

## Design

- Task `textkit`, English docs and test output, Bash auto-approve hook (no permission denials), `claude-opus-5-5`, Claude Code as installed on the run machine (version recorded in `meta.json`).
- Four project CLAUDE.md texts. Each ends with the same sentence, "코드·명령어·파일명은 원문 그대로 둡니다." (keep code, commands and file names as they are), so the first sentence is the only difference.

| condition | first sentence | English gloss |
|---|---|---|
| `s_all` (A) | 사용자에게 보이는 모든 글을 한국어로 작성하세요. | Write all user-visible text in Korean. |
| `s_during` (B) | 작업하는 도중에 사용자에게 남기는 짧은 글도 한국어로 작성하세요. | Write the short notes you leave for the user while working in Korean too. |
| `s_progress` (C) | 도구 호출 사이의 진행 설명도 한국어로 작성하세요. | Write the progress notes between tool calls in Korean too. |
| `s_answer` (D) | 항상 한국어로 답하세요. | Always answer in Korean. |

- 16 runs per condition, 64 in total, run in 16 rounds; the order of the four conditions is shuffled within each round (seed recorded in `meta.json`).
- Outcome per run: at least one progress message classified `en` or `other` by `langleak.classify` (unchanged from the published version). Runs that write no progress message are reported separately.

## Analysis

- **Primary comparison: A vs B**, two-sided Fisher exact test on leaking runs, α = 0.05. This asks whether naming the during-work notes (in words other than the earlier "progress notes" phrasing) matters beyond saying "all user-visible text".
- Secondary, descriptive: C vs D (replication of the earlier contrast), A vs D (does broad scope alone help), B vs C (two ways of naming the notes). No correction is applied to these; they are reported as exploratory.
- Sensitivity: the same counts with `mixed` messages counted as leaks.

## How the result will be read

- If A leaks about as rarely as B and C, the earlier result is better explained by scope: generic texts were read as covering only the final answer.
- If A leaks at a rate near D while B and C stay low, naming the during-work notes matters beyond broad scope.
- If D does not leak clearly more than C (for example fewer than 5 of 16), the earlier contrast did not replicate in this setting, and no conclusion about A vs B will be drawn from this stage.
- Anything in between: stage 2 repeats A vs B only, with more runs, under the same rules.

## Power

With 16 runs per arm, Fisher's test has roughly 80% power for 60% vs 10% and much less for smaller gaps. Stage 1 is meant to detect a large difference or show that the effect is not large; a small difference needs stage 2.

---

## Results (added 2026-11-24, after the runs; the plan above is unchanged)

64 runs, 2026-11-23 23:50 to 2026-11-24 00:44 KST, Claude Code 2.1.311, `claude-opus-5-5`, order seed 1795445435, no errors. Every run wrote progress messages, and every run's last answer was Korean. 3 runs still hit a permission denial (2 in A, 1 in C); none of their leaks started after a denial. Raw logs: `raw/scope.tgz`; tables: `results/scope/`.

| condition | leak runs | non-Korean progress messages |
|---|---|---|
| A `s_all` (all user-visible text) | 6/16 (38%, 18–61%) | 15/59 |
| B `s_during` (notes left while working) | 0/16 (0%, 0–19%) | 0/141 |
| C `s_progress` (progress notes between tool calls) | 0/16 (0%, 0–19%) | 0/166 |
| D `s_answer` (always answer) | 11/16 (69%, 44–86%) | 27/62 |

**Primary, A vs B:** 6/16 vs 0/16, two-sided Fisher p = 0.018, below the pre-registered α = 0.05.

Secondary (exploratory): C vs D 0/16 vs 11/16, p = 0.0001, so the earlier contrast replicated in this setting. A vs D 6/16 vs 11/16, p = 0.16. B vs C 0/16 vs 0/16.

**Sensitivity.**
- Counting `mixed` as leaks: A 6/16, B 3/16 (p = 0.43), C 0/16, D 12/16. All 5 of B's `mixed` messages are Korean sentences with module names, such as "slug 통과(9/16). 다음은 word count." The classifier strips tokens containing `/`, which removes "(9/16)" and lowers the Hangul share.
- Not counting header-only English lines such as "**3. truncate**" or "**5. duration** (SPEC 5)": A 4/16, B 0/16 (p = 0.10), C 0/16, D 10/16. Two of A's six leaking runs leaked only through such headers.
- Runs with no denial only: A 5/14, B 0/16 (p = 0.014).

**Reading, by the rules above.** D leaked clearly more than C, so the earlier contrast replicated. A fell between B/C and D: broad scope alone may have helped somewhat (6/16 vs 11/16, not significant), and the pre-registered test of A against B passed, but by a margin that does not survive dropping header-only lines. Under the plan, this is the "in between" case: stage 2 repeats A vs B only, with more runs, under the same rules. Both texts that named the during-work notes, in different words, had no leaks in 32 runs.
