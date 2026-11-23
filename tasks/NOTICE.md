# tasks/jsonpointer

A copy of [python-json-pointer](https://github.com/stefankoegl/python-json-pointer) by Stefan Kögl and contributors,
at commit `9c4d3da7b12cead8c0ee232889f473ac653c4b4f` (2026-11-19), without `.git` and `.github`. It is unmodified;
its license is in `jsonpointer/LICENSE.txt` (BSD-3-Clause). `langleak.py` copies it into a temporary workspace and
reverts seven upstream fixes there to build the stage-3 real-repository task (`REAL_TASKS` in `langleak.py`).
