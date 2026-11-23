# Pre-registration: `scope2` experiment (stage 2)

Written and committed before any `scope2` run. Results will be added below this plan without changing it.

## Why

In stage 1 (`PREREG_scope.md`), "all user-visible text in Korean" (A) leaked in 6/16 runs and "the short notes you leave while working, too" (B) in 0/16 (p = 0.018). Two of A's six leaking runs leaked only through numbered heading lines that name a module, such as "**3. truncate**". Without those lines the comparison was 4/16 vs 0/16 (p = 0.10). Stage 2 repeats A vs B with more runs, and fixes in advance how such heading lines are treated.

## Design

- Same setup as stage 1: task `textkit`, English docs and test output, Bash auto-approve hook, `claude-opus-5-5`, Claude Code as installed on the run machine (version recorded in `meta.json`).
- Conditions: `s_all` (A) and `s_during` (B), the same CLAUDE.md texts as stage 1, including the shared closing sentence.
- 48 runs per condition, 96 in total, in 48 rounds; the order of A and B is shuffled within each round (seed recorded in `meta.json`).
- Stage-1 runs are not pooled into the primary test.

## Outcomes

- **Primary (strict):** a run leaks if at least one progress message is classified `en` or `other` by `langleak.classify` and is not a heading-only line as defined by `langleak.HEADER_ONLY` (a numbered heading that names a module or spec section, e.g. "**3. truncate**", "Fix 1: slug", "**5. duration** (SPEC 5)"). Both are fixed in the committed `langleak.py`.
- Secondary: the stage-1 outcome (any `en`/`other` progress message), and the same with `mixed` counted as a leak.

## Analysis

- **Primary: A vs B on the strict outcome**, two-sided Fisher exact test, α = 0.05.
- Secondary, descriptive: A vs B on the secondary outcomes; runs with no permission denial only; stage 1 + stage 2 combined.

## How the result will be read

- Primary test passes, with B lower: naming the during-work notes reduced English progress notes beyond what a broad "all user-visible text" rule did, in this setup.
- Primary test does not pass: no evidence in this setup that naming the notes adds to a broad scope rule; the stage-1 difference may have come from heading lines or chance.
- Either way the result covers one model, one task and one language; it says nothing about other wordings.

## Power

With 48 runs per arm, Fisher's test has about 91% power for 25% vs 2%, 75% for 20% vs 2%, and 48% for 15% vs 2% (strict outcome; stage 1 observed 25% vs 0%).

## Running

`python3 langleak.py run scope2 --n 48 --model opus --seed <s> --resume results/scope2/<dir>`. If the usage limit stops a batch, the same command resumes it after the limit resets and skips finished runs.

---

## Results (added 2026-11-24, after the runs; the plan above is unchanged)

96 runs, 2026-11-24 01:18 to 02:48 KST, Claude Code 2.1.311, `claude-opus-5-5`, seed 20261124. The usage limit stopped the batch after round 44; the launcher waited and resumed at 02:41, re-running the failed runs (rounds 45–46) and finishing the rest. `meta.json` was rewritten by the resumed invocation and lists only its 8 runs; every run's stream-json is in `raw/scope2.tgz`. Every run wrote progress messages and ended with a Korean answer. 2 A runs hit a permission denial; no leak started after one.

| condition | strict leak runs (primary) | any `en`/`other` (stage-1 outcome) | `mixed` counted too | non-Korean progress messages |
|---|---|---|---|---|
| A `s_all` | 13/48 (27%, 17–41%) | 16/48 | 24/48 | 33/129 |
| B `s_during` | 3/48 (6%, 2–17%) | 3/48 | 12/48 | 3/395 |

**Primary, A vs B on the strict outcome:** 13/48 vs 3/48, two-sided Fisher p = 0.012, below α = 0.05.

Secondary: stage-1 outcome 16/48 vs 3/48 (p = 0.0016); `mixed` counted 24/48 vs 12/48 (p = 0.020); runs with no denial 13/46 vs 3/48 (p = 0.006); stage 1 and 2 combined, strict, 17/64 vs 3/64 (p = 0.001).

B's three leaking runs each had one English line at the start of the loop: "Let me check the test file before fixing them one at a time.", "Plain bugs. I'll fix them one by one, running the tests after each.", "Let me look at the tests quickly, then fix one by one."

**Reading, by the rules above.** The primary test passed with B lower. In this setup, naming the notes left while working reduced English progress notes beyond what a broad "all user-visible text" rule did. It did not remove them (3/48). This covers one model, one task and one language, and only these two wordings.
