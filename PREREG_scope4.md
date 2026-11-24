# Pre-registration: `scope4` experiment (stage 4)

Written and committed before any `scope4` run. Results will be added below this plan without changing it.

## Why

In stage 3 (`PREREG_scope3.md`), on a real repository (python-json-pointer with seven reverted upstream fixes), English progress notes appeared in 10/16 runs with "항상 한국어로 답하세요." ("Always answer in Korean.") in CLAUDE.md, and in 8/16 with the during-work sentence. In every case it was a single line like "Now let me look at the relevant tests." So no CLAUDE.md sentence tried there stopped it. Stage 4 asks whether the same sentence does better when it is appended to the system prompt (`--append-system-prompt`), a channel a user can also set, instead of being loaded from CLAUDE.md.

## Design

- One setting, identical to the stage-3 `real` arm: `claude-opus-5-5`, Korean prompt, the same `tasks/jsonpointer` fixture and seven reverts, English test output, Bash auto-approve hook, `--setting-sources project`, the same allowed tools, same Mac and launcher.
- Two conditions:
  - A `s_answer`: project CLAUDE.md with "항상 한국어로 답하세요. 코드·명령어·파일명은 원문 그대로 둡니다." (as in stage 3).
  - B `sys_answer`: no CLAUDE.md; the same two sentences passed with `--append-system-prompt`.
- 24 runs per condition, 48 in total, in 24 rounds with the order of the two conditions shuffled within each round (seed recorded in `meta.json`). A is rerun in this batch, not taken from stage 3, so both conditions share the same day and Claude Code version.
- The self-check and the probe of the Python that Claude Code's Bash runs are the same as in stage 3.

## Outcomes and analysis

- Primary: strict outcome as in stages 2–3 (at least one `en`/`other` progress message that is not a heading-only line). Korean classifier rules unchanged.
- Gate: if A leaks in 2 or fewer of 24 runs, the leak is reported as not reproduced in this batch and the comparison is not interpreted.
- Test: A vs B, two-sided Fisher exact, α = 0.05 (one comparison, no correction).
- Secondary, descriptive: any `en`/`other` message; `mixed` counted too; where the first leak happens; the text of the leaked lines; non-Korean final answers.

## How the result will be read

- B lower and p < 0.05: appending the sentence to the system prompt reduced the opening English line on this repository; that is a workaround users can apply, for this model, prompt and repository.
- Otherwise: no evidence that the system-prompt channel helps here; together with stage 3, no user-side text tried in this repo stopped the opening English line on the real repository.
- Not covered: other repositories, other models or languages, the interactive UI, other wordings in the system prompt.

## Power

With 24 runs per condition and A at 60% (stage 3: 10/16), the test has about 95% power if B is at 10%, 76% at 20% and 47% at 30%; with A at 50% the same figures are 83%, 49% and 21%.

## Running

`python3 langleak.py run scope4 --n 24 --seed <s> --python-real <python ≥ 3.10.7> --resume results/scope4/<dir>`, started by `LangLeakScope4.app` on the same Mac as stages 1–3.
