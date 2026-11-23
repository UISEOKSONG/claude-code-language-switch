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
