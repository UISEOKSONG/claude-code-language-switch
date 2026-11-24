# tasks/jsonpointer

A copy of [python-json-pointer](https://github.com/stefankoegl/python-json-pointer) by Stefan Kögl and contributors,
at commit `9c4d3da7b12cead8c0ee232889f473ac653c4b4f` (2026-11-19), without `.git` and `.github`. It is unmodified;
its license is in `jsonpointer/LICENSE.txt` (BSD-3-Clause). `langleak.py` copies it into a temporary workspace and
reverts seven upstream fixes there to build the stage-3 real-repository task (`REAL_TASKS` in `langleak.py`).

# tasks/boltons, tasks/more-itertools, tasks/toolz (stage 5)

Copies, without `.git` and `.github`, of [boltons](https://github.com/mahmoud/boltons) at `d31d821d56c8f7756af9c30a864077f2e5855321` (BSD-3-Clause), [more-itertools](https://github.com/more-itertools/more-itertools) at `aa9977698a5e6ae15d3fdfac08a5fc5621c4e179` (MIT) and [toolz](https://github.com/pytoolz/toolz) at `451af60dec590a6010e2babdbf391ea8f815122f` (BSD-3-Clause); each project's license is in its folder. One file is removed from toolz: `toolz/tests/test_package.py`, whose only test checks the installed package version and fails when toolz is run from a source checkout without `pip install` (see the amendment in `PREREG_scope5.md`). The other two are unmodified. `stage5.py` copies them into a temporary workspace and reverts the upstream fixes listed in `tasks/reverts.json` there.
