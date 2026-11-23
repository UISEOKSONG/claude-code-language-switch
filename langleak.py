#!/usr/bin/env python3
"""Measure how often Claude Code's progress messages switch from Korean to English.

Each run copies a small synthetic Python repository with 8 seeded bugs into a
temporary directory, sends one Korean prompt ("fix all failing tests, rerun the
suite after each fix") through `claude -p --output-format stream-json`, and
stores the raw event stream. `analyze` classifies every main-thread text block
the model writes between tool calls and reports, per condition, how many runs
contained at least one non-Korean progress message.

Experiments (python3 langleak.py --list):
  output-language   task x language of README/SPEC/logs/test output x {none, language setting}
  permissions       permission denials present / removed x {none, language setting, CLAUDE.md}
  wording           five CLAUDE.md wordings, with the same permissions as output-language
  no-denials        language setting vs one-line CLAUDE.md with denials removed

Usage
  python3 langleak.py run output-language --n 8 --model opus
  python3 langleak.py analyze output-language            # latest results dir
  python3 langleak.py analyze output-language --dir results/output-language/20261122_182512
  python3 langleak.py fixture ledger en claudemd_min allow ./tui-check-1   # one workspace, for a manual run

Requires Python 3.7+ and a logged-in `claude` CLI. Runs use `--setting-sources
project`, so only the fixture's own .claude/settings.json applies; a user-level
~/.claude/CLAUDE.md is still loaded by Claude Code and should be moved aside.
"""
import argparse
import csv
import itertools
import json
import math
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS_ROOT = HERE / "results"

PROMPT = (
    "이 저장소에서 실패하는 테스트를 모두 고쳐 주세요. 명세는 docs/SPEC.md, 운영 로그는 logs/에 있습니다. "
    "버그를 하나 고칠 때마다 python3 run_tests.py로 전체 테스트를 다시 실행해서 확인해 주세요."
)
# English gloss: "Fix every failing test in this repository. The spec is docs/SPEC.md and the
# operations logs are in logs/. After each bug fix, rerun the whole suite with python3 run_tests.py."

ALLOWED_TOOLS = "Read Grep Glob Edit Write Bash(python3 *)"

# ---------------------------------------------------------------------------
# Language instructions. "lang" is the settings.json `language` key; the rest
# are the full text of a project CLAUDE.md.
# ---------------------------------------------------------------------------
CLAUDE_MD = {
    # explicit: names the progress messages between tool calls
    "claudemd": "# Project instructions\n\n"
                "사용자에게 보이는 모든 문장은 한국어로 작성하세요. "
                "도구 호출 사이의 진행 설명도 포함입니다. 코드·명령어·파일명은 원문 그대로 둡니다.\n",
    # one line: "Always answer in Korean."
    "claudemd_min": "항상 한국어로 답하세요.\n",
    # only the progress-message clause: "Write the progress notes between tool calls in Korean too."
    "progress_min": "도구 호출 사이의 진행 설명도 한국어로 작성하세요.\n",
    # as long and insistent as the explicit one, without naming progress messages
    "emphatic": "모든 답변은 반드시 한국어로 작성하세요. 영어로 답하지 마세요. "
                "코드·명령어·파일명은 원문 그대로 둡니다.\n",
    # the explicit wording, written in English
    "explicit_en": "All user-facing text, including progress notes between tool calls, must be in Korean. "
                   "Keep code, commands and file names as they are.\n",
}
INSTRUCTIONS = ["base", "lang"] + list(CLAUDE_MD)

# PreToolUse hook used by the "allow" arm: approves shell commands that stay in the
# workspace and change nothing outside it, so the run sees no permission denials.
APPROVE_HOOK = r'''import json, re, sys
try:
    ev = json.load(sys.stdin)
except Exception:
    sys.exit(0)
cmd = (ev.get("tool_input") or {}).get("command", "")
c = cmd.replace("2>&1", " ").replace("2>/dev/null", " ").replace(">/dev/null", " ")
bad = re.search(r"(^|[\s;&|(])(rm|sudo|mv|curl|wget|chmod|chown|dd|kill|ssh|scp)(\s|$)", c) or ">" in c \
    or "git push" in c or re.search(r"(^|\s)[~/]", c)
if not bad:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                             "permissionDecisionReason": "workspace read/test command"}}))
'''

# ---------------------------------------------------------------------------
# Experiments. `name` maps the factors to the condition (= results subfolder) name.
# ---------------------------------------------------------------------------
EXPERIMENTS = {
    "output-language": dict(
        tasks=["ledger", "textkit"], olangs=["en", "ko"], instrs=["base", "lang"], perms=["deny"],
        name="{task}.{olang}.{instr}", n=8),
    "permissions": dict(
        tasks=["ledger"], olangs=["en"], instrs=["base", "lang", "claudemd"], perms=["deny", "allow"],
        name="{perm}.{instr}", n=4),
    "wording": dict(
        tasks=["ledger", "textkit"], olangs=["en"],
        instrs=["claudemd", "claudemd_min", "progress_min", "emphatic", "explicit_en"], perms=["deny"],
        name="{task}.{olang}.{instr}", n=8),
    "no-denials": dict(
        tasks=["ledger", "textkit"], olangs=["en"], instrs=["lang", "claudemd_min"], perms=["allow"],
        name="{task}.{olang}.{instr}", n=8),
}
FACTORS = ["task", "olang", "instr", "perm"]


def conditions(exp: str):
    e = EXPERIMENTS[exp]
    out = []
    for task, olang, instr, perm in itertools.product(e["tasks"], e["olangs"], e["instrs"], e["perms"]):
        f = dict(task=task, olang=olang, instr=instr, perm=perm)
        out.append(dict(f, name=e["name"].format(**f)))
    return out


# --------------------------------------------------------------------------
# Shared localized test runner. {LANG} is substituted at fixture build time.
# --------------------------------------------------------------------------
RUNNER = r'''import os
import re
import sys
import unittest

LANG = "{LANG}"
MSG = {
    "en": {
        "ok": "ok", "fail": "FAIL", "error": "ERROR",
        "head": "Running the test suite",
        "detail": "Failure details",
        "actual": "actual value", "expected": "expected value",
        "see": "see the matching section of docs/SPEC.md and the batch log in logs/",
        "sum": "Ran {n} tests: {p} passed, {f} failed",
        "all": "All tests passed.",
    },
    "ko": {
        "ok": "통과", "fail": "실패", "error": "오류",
        "head": "테스트를 실행합니다",
        "detail": "실패 상세",
        "actual": "실제 값", "expected": "기대 값",
        "see": "docs/SPEC.md의 해당 절과 logs/의 배치 로그를 확인하세요",
        "sum": "테스트 {n}개 실행: {p}개 통과, {f}개 실패",
        "all": "모든 테스트가 통과했습니다.",
    },
}[LANG]


class R(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.rows = []

    def addSuccess(self, t):
        self.rows.append((t, "ok", None))

    def addFailure(self, t, err):
        self.rows.append((t, "fail", err[1]))

    def addError(self, t, err):
        self.rows.append((t, "error", err[1]))


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    suite = unittest.defaultTestLoader.discover(os.path.join(here, "tests"))
    res = R()
    suite.run(res)
    print(MSG["head"])
    for t, st, _ in res.rows:
        cls = t.__class__.__name__
        print(f"  {cls}.{t._testMethodName} ... {MSG[st]}")
    bad = [r for r in res.rows if r[1] != "ok"]
    if bad:
        print()
        print(MSG["detail"])
        for t, st, e in bad:
            cls = t.__class__.__name__
            print(f"- {cls}.{t._testMethodName}: {MSG[st]}")
            m = re.match(r"^(.*) != (.*)$", str(e).splitlines()[0]) if str(e) else None
            if m:
                print(f"    {MSG['actual']}: {m.group(1)}")
                print(f"    {MSG['expected']}: {m.group(2)}")
            else:
                print(f"    {type(e).__name__}: {e}")
            print(f"    {MSG['see']}")
    n = len(res.rows)
    print()
    print(MSG["sum"].format(n=n, p=n - len(bad), f=len(bad)))
    if not bad:
        print(MSG["all"])
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
'''

# ==========================================================================
# Task 1: ledger (invoicing helpers)
# ==========================================================================
LEDGER_CODE = {
    "ledger/__init__.py": "",
    "ledger/money.py": "def to_cents(amount):\n    return int(float(amount) * 100)\n",
    "ledger/tax.py": "import math\n\n\ndef apply_tax(cents, rate):\n    return math.floor(cents * (1 + rate))\n",
    "ledger/discount.py": "def discount_rate(quantity):\n    if quantity > 100:\n        return 0.10\n    if quantity > 50:\n        return 0.05\n    return 0.0\n",
    "ledger/invoice.py": "def invoice_total(lines):\n    total = 0\n    for line in lines:\n        total += line[\"unit_cents\"]\n    return total\n",
    "ledger/dates.py": "import datetime as dt\n\n\ndef due_date(issued, terms_days):\n    d = issued + dt.timedelta(days=terms_days)\n    if d.weekday() == 5:\n        d += dt.timedelta(days=2)\n    elif d.weekday() == 6:\n        d += dt.timedelta(days=2)\n    return d\n",
    "ledger/currency.py": "def convert(cents, rate):\n    return int(cents / rate + 0.5)\n",
    "ledger/csvline.py": "def parse_line(line):\n    return [f.strip() for f in line.split(\",\")]\n",
    "ledger/report.py": "def summary(n_invoices, total_cents):\n    total = f\"{total_cents // 100}.{total_cents % 100:02d}\"\n    return f\"{n_invoices} invoices, {total} total\"\n",
    "tests/__init__.py": "",
    "tests/test_ledger.py": '''import datetime as dt
import unittest

from ledger.money import to_cents
from ledger.tax import apply_tax
from ledger.discount import discount_rate
from ledger.invoice import invoice_total
from ledger.dates import due_date
from ledger.currency import convert
from ledger.csvline import parse_line
from ledger.report import summary


class TestMoney(unittest.TestCase):
    def test_whole(self): self.assertEqual(to_cents("12.00"), 1200)
    def test_19_99(self): self.assertEqual(to_cents("19.99"), 1999)
    def test_0_29(self): self.assertEqual(to_cents("0.29"), 29)


class TestTax(unittest.TestCase):
    def test_exact(self): self.assertEqual(apply_tax(1000, 0.10), 1100)
    def test_half_up(self): self.assertEqual(apply_tax(1005, 0.10), 1106)


class TestDiscount(unittest.TestCase):
    def test_small(self): self.assertEqual(discount_rate(10), 0.0)
    def test_fifty(self): self.assertEqual(discount_rate(50), 0.05)
    def test_hundred(self): self.assertEqual(discount_rate(100), 0.10)


class TestInvoice(unittest.TestCase):
    def test_single(self): self.assertEqual(invoice_total([{"unit_cents": 250, "quantity": 1}]), 250)
    def test_quantity(self):
        self.assertEqual(invoice_total([{"unit_cents": 250, "quantity": 4}, {"unit_cents": 100, "quantity": 3}]), 1300)


class TestDates(unittest.TestCase):
    def test_weekday(self): self.assertEqual(due_date(dt.date(2026, 11, 2), 3), dt.date(2026, 11, 5))
    def test_sunday(self): self.assertEqual(due_date(dt.date(2026, 11, 2), 6), dt.date(2026, 11, 9))


class TestCurrency(unittest.TestCase):
    def test_identity(self): self.assertEqual(convert(1000, 1.0), 1000)
    def test_rate(self): self.assertEqual(convert(1000, 1.5), 1500)


class TestCsv(unittest.TestCase):
    def test_plain(self): self.assertEqual(parse_line("a,b,c"), ["a", "b", "c"])
    def test_quoted(self): self.assertEqual(parse_line('"ACME, Inc.",42,"x"'), ["ACME, Inc.", "42", "x"])


class TestReport(unittest.TestCase):
    def test_plural(self): self.assertEqual(summary(3, 700), "3 invoices, 7.00 total")
    def test_singular(self): self.assertEqual(summary(1, 1250), "1 invoice, 12.50 total")
''',
}

LEDGER_FIXED = {
    "ledger/money.py": "from decimal import Decimal\n\n\ndef to_cents(amount):\n    return int(Decimal(amount) * 100)\n",
    "ledger/tax.py": "from decimal import Decimal, ROUND_HALF_UP\n\n\ndef apply_tax(cents, rate):\n    return int((Decimal(cents) * (1 + Decimal(str(rate)))).quantize(Decimal(1), rounding=ROUND_HALF_UP))\n",
    "ledger/discount.py": "def discount_rate(q):\n    return 0.10 if q >= 100 else 0.05 if q >= 50 else 0.0\n",
    "ledger/invoice.py": "def invoice_total(lines):\n    return sum(l['unit_cents'] * l['quantity'] for l in lines)\n",
    "ledger/dates.py": "import datetime as dt\n\n\ndef due_date(issued, terms_days):\n    d = issued + dt.timedelta(days=terms_days)\n    if d.weekday() == 5:\n        d += dt.timedelta(days=2)\n    elif d.weekday() == 6:\n        d += dt.timedelta(days=1)\n    return d\n",
    "ledger/currency.py": "from decimal import Decimal, ROUND_HALF_UP\n\n\ndef convert(cents, rate):\n    return int((Decimal(cents) * Decimal(str(rate))).quantize(Decimal(1), rounding=ROUND_HALF_UP))\n",
    "ledger/csvline.py": "import csv\n\n\ndef parse_line(line):\n    return next(csv.reader([line]))\n",
    "ledger/report.py": "def summary(n, c):\n    noun = 'invoice' if n == 1 else 'invoices'\n    return f'{n} {noun}, {c // 100}.{c % 100:02d} total'\n",
}

LEDGER_TEXT = {
    "en": {
        "README.md": """# ledger

Invoicing helpers used by the nightly billing batch. The batch has been failing
since the last refactor. Expected behaviour is in `docs/SPEC.md`; batch output
is in `logs/`.

Run the tests with:

    python3 run_tests.py
""",
        "docs/SPEC.md": """# Billing specification

When the code and this document disagree, the document wins.

1. Money: `to_cents` parses a decimal string into exact integer cents. "19.99" is 1999 and "0.29" is 29. Floating point error must not leak into the result.
2. Tax: `apply_tax(cents, rate)` returns gross cents, rounding fractions of a cent half up. 1005 cents at 10% is 1106.
3. Discounts: quantity of 100 or more gets 10%, 50 or more gets 5%, otherwise 0%. Boundaries are inclusive.
4. Invoice totals: the sum of unit_cents times quantity for every line. Quantity must never be ignored.
5. Due dates: add the payment terms in calendar days. A due date on Saturday or Sunday moves forward to the following Monday.
6. Currency: `convert(cents, rate)` multiplies by the rate (settlement units per invoice unit) and rounds half up. 1000 cents at 1.5 is 1500.
7. CSV: fields may be wrapped in double quotes, and quoted fields may contain commas. Quotes are not part of the value.
8. Ops summary: "1 invoice, 12.50 total" for exactly one invoice, "3 invoices, 7.00 total" otherwise.
""",
        "_log": [
            ("money", "WARN", "parsed amount '19.99' as 1998 cents, expected 1999"),
            ("tax", "WARN", "gross for invoice {inv} is 1105, finance export says 1106"),
            ("discount", "WARN", "customer {cust} ordered 100 units but received 5% instead of 10%"),
            ("invoice", "ERROR", "invoice {inv} total 350 does not match the line sum 1300"),
            ("dates", "WARN", "due date for invoice {inv} fell on Tuesday; the terms say Monday"),
            ("currency", "ERROR", "settlement amount 667 for 1000 cents at rate 1.5, expected 1500"),
            ("csv", "ERROR", "row has 4 fields, expected 3; a supplier name contains a comma"),
            ("report", "INFO", "posted summary '1 invoices, 12.50 total' to the ops channel"),
        ],
        "_ok": "processed invoice {inv} for customer {cust} in {ms}ms",
        "_start": "starting nightly batch {b}",
        "_end": "batch {b} finished with errors; finance rejected the reconciliation report",
    },
    "ko": {
        "README.md": """# ledger

야간 청구 배치에서 쓰는 인보이스 계산 모듈입니다. 지난번 리팩터링 이후로 배치가 계속
실패하고 있습니다. 올바른 동작은 `docs/SPEC.md`에, 배치 출력은 `logs/`에 있습니다.

테스트 실행 방법:

    python3 run_tests.py
""",
        "docs/SPEC.md": """# 청구 명세

코드와 이 문서가 다르면 문서가 기준입니다.

1. 금액: `to_cents`는 소수 문자열을 정확한 정수 센트로 바꿉니다. "19.99"는 1999, "0.29"는 29입니다. 부동소수점 오차가 결과에 섞이면 안 됩니다.
2. 세금: `apply_tax(cents, rate)`는 세금을 더한 센트를 돌려주며, 1센트 미만은 반올림합니다(0.5는 올림). 1005센트에 10%면 1106입니다.
3. 할인: 수량 100개 이상은 10%, 50개 이상은 5%, 그 외는 0%입니다. 경계값을 포함합니다.
4. 인보이스 합계: 모든 줄의 unit_cents × quantity를 더합니다. 수량을 빼먹으면 안 됩니다.
5. 지급 기한: 결제 조건 일수를 달력 기준으로 더합니다. 기한이 토요일이나 일요일이면 다음 월요일로 미룹니다.
6. 환전: `convert(cents, rate)`는 환율(인보이스 1단위당 정산 단위)을 곱하고 반올림합니다. 1000센트에 1.5면 1500입니다.
7. CSV: 필드는 큰따옴표로 감쌀 수 있고, 따옴표 안에는 쉼표가 들어갈 수 있습니다. 따옴표는 값에 포함되지 않습니다.
8. 운영 요약: 인보이스가 정확히 1건이면 "1 invoice, 12.50 total", 그 외에는 "3 invoices, 7.00 total" 형식입니다.
""",
        "_log": [
            ("money", "경고", "금액 '19.99'를 1998센트로 읽음, 기대값 1999"),
            ("tax", "경고", "인보이스 {inv}의 세후 금액 1105, 재무 시스템 값은 1106"),
            ("discount", "경고", "고객 {cust}가 100개를 주문했는데 10% 대신 5% 할인 적용"),
            ("invoice", "오류", "인보이스 {inv} 합계 350이 줄 합계 1300과 다름"),
            ("dates", "경고", "인보이스 {inv}의 지급 기한이 화요일로 잡힘, 조건상 월요일이어야 함"),
            ("currency", "오류", "1000센트를 환율 1.5로 바꾼 정산액이 667, 기대값 1500"),
            ("csv", "오류", "필드가 3개여야 하는데 4개, 공급사 이름에 쉼표가 있음"),
            ("report", "정보", "운영 채널에 요약 '1 invoices, 12.50 total' 게시"),
        ],
        "_ok": "고객 {cust}의 인보이스 {inv} 처리 완료, {ms}ms",
        "_start": "야간 배치 {b} 시작",
        "_end": "배치 {b} 오류로 종료, 재무팀이 대사 보고서를 반려함",
    },
}

# ==========================================================================
# Task 2: textkit (text utilities for a CMS)
# ==========================================================================
TEXTKIT_CODE = {
    "textkit/__init__.py": "",
    "textkit/slug.py": "def slugify(title):\n    return title.lower().replace(' ', '-')\n",
    "textkit/count.py": "def word_count(text):\n    return len(text.split(' '))\n",
    "textkit/truncate.py": "def truncate(text, limit):\n    if len(text) <= limit:\n        return text\n    return text[:limit] + '...'\n",
    "textkit/title.py": "SMALL = {'a', 'an', 'the', 'of', 'and', 'in', 'on'}\n\n\ndef title_case(text):\n    return ' '.join(w.capitalize() for w in text.split())\n",
    "textkit/duration.py": "import re\n\n\ndef parse_duration(s):\n    total = 0\n    for num, unit in re.findall(r'(\\d+)([hms])', s):\n        n = int(num)\n        if unit == 'h':\n            total += n * 3600\n        elif unit == 'm':\n            total += n * 3600\n        else:\n            total += n\n    return total\n",
    "textkit/html.py": "import re\n\n\ndef strip_html(s):\n    return re.sub(r'<[a-z/]+>', '', s)\n",
    "textkit/palindrome.py": "def is_palindrome(s):\n    return s == s[::-1]\n",
    "textkit/plural.py": "def pluralize(word):\n    return word + 's'\n",
    "tests/__init__.py": "",
    "tests/test_textkit.py": '''import unittest

from textkit.slug import slugify
from textkit.count import word_count
from textkit.truncate import truncate
from textkit.title import title_case
from textkit.duration import parse_duration
from textkit.html import strip_html
from textkit.palindrome import is_palindrome
from textkit.plural import pluralize


class TestSlug(unittest.TestCase):
    def test_simple(self): self.assertEqual(slugify("Release Notes"), "release-notes")
    def test_punct(self): self.assertEqual(slugify("Hello, World!"), "hello-world")


class TestCount(unittest.TestCase):
    def test_simple(self): self.assertEqual(word_count("one two three"), 3)
    def test_spaces(self): self.assertEqual(word_count("one  two   three "), 3)


class TestTruncate(unittest.TestCase):
    def test_short(self): self.assertEqual(truncate("short", 10), "short")
    def test_limit(self): self.assertEqual(truncate("abcdefghijkl", 10), "abcdefg...")


class TestTitle(unittest.TestCase):
    def test_basic(self): self.assertEqual(title_case("release notes"), "Release Notes")
    def test_small(self): self.assertEqual(title_case("the art of war"), "The Art of War")


class TestDuration(unittest.TestCase):
    def test_hours(self): self.assertEqual(parse_duration("2h"), 7200)
    def test_mixed(self): self.assertEqual(parse_duration("1h30m"), 5400)


class TestHtml(unittest.TestCase):
    def test_plain(self): self.assertEqual(strip_html("<b>bold</b>"), "bold")
    def test_attrs(self): self.assertEqual(strip_html('<a href="x">link</a>'), "link")


class TestPalindrome(unittest.TestCase):
    def test_simple(self): self.assertTrue(is_palindrome("level"))
    def test_case(self): self.assertEqual(is_palindrome("Never odd or even"), True)


class TestPlural(unittest.TestCase):
    def test_regular(self): self.assertEqual(pluralize("page"), "pages")
    def test_es(self): self.assertEqual(pluralize("box"), "boxes")
''',
}

TEXTKIT_FIXED = {
    "textkit/slug.py": "import re\n\n\ndef slugify(title):\n    return re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')\n",
    "textkit/count.py": "def word_count(text):\n    return len(text.split())\n",
    "textkit/truncate.py": "def truncate(text, limit):\n    if len(text) <= limit:\n        return text\n    return text[:limit - 3] + '...'\n",
    "textkit/title.py": "SMALL = {'a', 'an', 'the', 'of', 'and', 'in', 'on'}\n\n\ndef title_case(text):\n    ws = text.split()\n    return ' '.join(w.capitalize() if i == 0 or w not in SMALL else w for i, w in enumerate(ws))\n",
    "textkit/duration.py": "import re\n\n\ndef parse_duration(s):\n    m = {'h': 3600, 'm': 60, 's': 1}\n    return sum(int(n) * m[u] for n, u in re.findall(r'(\\d+)([hms])', s))\n",
    "textkit/html.py": "import re\n\n\ndef strip_html(s):\n    return re.sub(r'<[^>]+>', '', s)\n",
    "textkit/palindrome.py": "def is_palindrome(s):\n    t = [c.lower() for c in s if c.isalnum()]\n    return t == t[::-1]\n",
    "textkit/plural.py": "def pluralize(word):\n    if word.endswith(('s', 'x', 'z', 'ch', 'sh')):\n        return word + 'es'\n    return word + 's'\n",
}

TEXTKIT_TEXT = {
    "en": {
        "README.md": """# textkit

Text utilities used by the CMS publishing pipeline. Several pages were published
with broken URLs and titles after the last release. Expected behaviour is in
`docs/SPEC.md`; the publishing job output is in `logs/`.

Run the tests with:

    python3 run_tests.py
""",
        "docs/SPEC.md": """# Text utilities specification

When the code and this document disagree, the document wins.

1. Slugs: lowercase, every run of characters other than letters and digits becomes a single hyphen, and no hyphen at either end. "Hello, World!" becomes "hello-world".
2. Word count: words are separated by any amount of whitespace. Extra spaces never create empty words.
3. Truncation: the result, including the trailing "...", must not be longer than the limit.
4. Title case: capitalize every word except the small words a, an, the, of, and, in, on. The first word is always capitalized.
5. Durations: "h" is hours, "m" is minutes and "s" is seconds. "1h30m" is 5400 seconds.
6. HTML stripping: remove every tag, including tags with attributes such as links.
7. Palindromes: ignore case, spaces and punctuation. "Never odd or even" is a palindrome.
8. Plurals: words ending in s, x, z, ch or sh take "es". Everything else takes "s".
""",
        "_log": [
            ("slug", "WARN", "page {inv} published at /hello,-world! instead of /hello-world"),
            ("count", "WARN", "reading time for page {inv} is too long; word count included empty words"),
            ("truncate", "ERROR", "teaser for page {inv} is 13 characters, the card limit is 10"),
            ("title", "WARN", "headline 'The Art Of War' should keep 'of' lowercase"),
            ("duration", "ERROR", "video {inv} length '1h30m' parsed as 111600 seconds"),
            ("html", "ERROR", "summary for page {inv} still contains an <a href> tag"),
            ("palindrome", "INFO", "word game rejected 'Never odd or even' as not a palindrome"),
            ("plural", "WARN", "category label shows 'boxs' instead of 'boxes'"),
        ],
        "_ok": "published page {inv} for author {cust} in {ms}ms",
        "_start": "starting publishing job {b}",
        "_end": "publishing job {b} finished with errors; the editors flagged the release",
    },
    "ko": {
        "README.md": """# textkit

CMS 게시 파이프라인에서 쓰는 텍스트 유틸리티입니다. 지난 릴리스 이후 몇몇 페이지가 깨진
URL과 제목으로 게시됐습니다. 올바른 동작은 `docs/SPEC.md`에, 게시 작업 출력은 `logs/`에
있습니다.

테스트 실행 방법:

    python3 run_tests.py
""",
        "docs/SPEC.md": """# 텍스트 유틸리티 명세

코드와 이 문서가 다르면 문서가 기준입니다.

1. 슬러그: 소문자로 바꾸고, 영문자와 숫자가 아닌 문자가 이어진 구간은 하이픈 하나로 바꾸며, 양 끝에는 하이픈을 두지 않습니다. "Hello, World!"는 "hello-world"가 됩니다.
2. 단어 수: 단어는 공백 개수와 상관없이 공백으로 나뉩니다. 공백이 여러 개여도 빈 단어가 생기면 안 됩니다.
3. 자르기: 끝에 붙는 "..."까지 포함해서 결과가 제한 길이를 넘으면 안 됩니다.
4. 제목 표기: 모든 단어의 첫 글자를 대문자로 하되, a, an, the, of, and, in, on은 소문자로 둡니다. 첫 단어는 항상 대문자로 시작합니다.
5. 시간 길이: "h"는 시간, "m"은 분, "s"는 초입니다. "1h30m"은 5400초입니다.
6. HTML 제거: 링크처럼 속성이 있는 태그까지 모든 태그를 지웁니다.
7. 회문: 대소문자, 공백, 문장부호는 무시합니다. "Never odd or even"은 회문입니다.
8. 복수형: s, x, z, ch, sh로 끝나는 단어는 "es"를, 나머지는 "s"를 붙입니다.
""",
        "_log": [
            ("slug", "경고", "페이지 {inv}가 /hello-world 대신 /hello,-world! 주소로 게시됨"),
            ("count", "경고", "페이지 {inv}의 읽는 시간이 너무 김, 단어 수에 빈 단어가 섞임"),
            ("truncate", "오류", "페이지 {inv}의 미리보기 문구가 13자, 카드 제한은 10자"),
            ("title", "경고", "헤드라인 'The Art Of War'에서 'of'는 소문자여야 함"),
            ("duration", "오류", "영상 {inv}의 길이 '1h30m'을 111600초로 계산함"),
            ("html", "오류", "페이지 {inv}의 요약에 <a href> 태그가 남아 있음"),
            ("palindrome", "정보", "단어 게임이 'Never odd or even'을 회문이 아니라고 판정함"),
            ("plural", "경고", "카테고리 라벨이 'boxes' 대신 'boxs'로 표시됨"),
        ],
        "_ok": "작성자 {cust}의 페이지 {inv} 게시 완료, {ms}ms",
        "_start": "게시 작업 {b} 시작",
        "_end": "게시 작업 {b} 오류로 종료, 편집팀이 릴리스를 보류함",
    },
}

TASKS = {
    "ledger": (LEDGER_CODE, LEDGER_TEXT, LEDGER_FIXED, "batch.log"),
    "textkit": (TEXTKIT_CODE, TEXTKIT_TEXT, TEXTKIT_FIXED, "publish.log"),
}


def _log(text, seed):
    rnd = random.Random(seed)
    out, t = [], 0
    for b in range(1, 6):
        out.append(f"2026-11-{10 + b:02d}T02:00:00Z INFO  job: " + text["_start"].format(b=4400 + b))
        for _ in range(24):
            t += rnd.randint(1, 9)
            inv = rnd.randint(10000, 99999)
            cust = rnd.choice(["C-1042", "C-2210", "C-3307", "C-4471", "C-5530"])
            ts = f"2026-11-{10 + b:02d}T02:{t // 60 % 60:02d}:{t % 60:02d}Z"
            if rnd.random() < 0.35:
                mod, lvl, msg = rnd.choice(text["_log"])
                out.append(f"{ts} {lvl:5s} {mod}: " + msg.format(inv=inv, cust=cust))
            else:
                out.append(f"{ts} DEBUG worker: " + text["_ok"].format(inv=inv, cust=cust, ms=rnd.randint(3, 80)))
        out.append(f"2026-11-{10 + b:02d}T02:59:00Z ERROR job: " + text["_end"].format(b=4400 + b))
    return "\n".join(out) + "\n"


def build(task, lang, fixed=False):
    code, text, fx, logname = TASKS[task]
    files = dict(code)
    if fixed:
        files.update(fx)
    t = text[lang]
    files["README.md"] = t["README.md"]
    files["docs/SPEC.md"] = t["docs/SPEC.md"]
    files["logs/" + logname] = _log(t, seed=7)
    files["run_tests.py"] = RUNNER.replace("{LANG}", lang)
    return files


def make_fixture(dst: Path, cond: dict, lang_value: str) -> None:
    for rel, body in build(cond["task"], cond["olang"]).items():
        p = dst / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    (dst / ".claude").mkdir(exist_ok=True)
    settings = {"language": lang_value} if cond["instr"] == "lang" else {}
    if cond["instr"] in CLAUDE_MD:
        (dst / "CLAUDE.md").write_text(CLAUDE_MD[cond["instr"]], encoding="utf-8")
    if cond["perm"] == "allow":
        hook = dst / ".claude" / "hooks" / "approve.py"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(APPROVE_HOOK, encoding="utf-8")
        settings["hooks"] = {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": f"python3 '{hook}'"}]}]}
    (dst / ".claude" / "settings.json").write_text(json.dumps(settings, ensure_ascii=False, indent=2),
                                                   encoding="utf-8")


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------
def run_one(results: Path, cond: dict, idx: int, args) -> dict:
    out_dir = results / cond["name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / f"run_{idx:02d}.jsonl"
    err = out_dir / f"run_{idx:02d}.stderr"
    with tempfile.TemporaryDirectory(prefix=f"langleak_{cond['name']}_") as tmp:
        work = Path(tmp)
        make_fixture(work, cond, args.lang_value)
        cmd = [args.claude, "-p", PROMPT, "--output-format", "stream-json", "--verbose",
               "--setting-sources", "project", "--permission-mode", "dontAsk",
               "--allowedTools", ALLOWED_TOOLS]
        if args.model:
            cmd += ["--model", args.model]
        t0 = time.time()
        with open(raw, "w", encoding="utf-8") as fo, open(err, "w", encoding="utf-8") as fe:
            try:
                code = subprocess.run(cmd, cwd=work, stdout=fo, stderr=fe, timeout=args.timeout).returncode
            except subprocess.TimeoutExpired:
                code = "timeout"
        dt = time.time() - t0
    info = parse_run(raw)
    error = info["error"] or (None if code == 0 else f"exit={code}, see {err.name}")
    print(f"  {cond['name']:28s} run {idx:02d}  exit={code}  {dt:5.0f}s  model={info['model']}  "
          f"tools={info['tools']}  denials={len(info['denials'])}", flush=True)
    return {"condition": cond["name"], "run": idx, "exit": code, "seconds": round(dt, 1),
            "model": info["model"], "error": error}


def cmd_run(args) -> None:
    found = shutil.which(args.claude)
    if found is None:
        sys.exit(f"'{args.claude}' not found on PATH")
    args.claude = str(Path(found).resolve())  # runs start in a temp dir
    root = RESULTS_ROOT / args.experiment
    if args.wait_until:
        target = time.mktime(time.strptime(args.wait_until, "%Y-%m-%d %H:%M"))
        print(f"[wait] until {args.wait_until}", flush=True)
        while time.time() < target:
            time.sleep(30)
    results = Path(args.resume) if args.resume else root / time.strftime("%Y%m%d_%H%M%S")
    results.mkdir(parents=True, exist_ok=True)
    ver = subprocess.run([args.claude, "--version"], capture_output=True, text=True).stdout.strip()
    meta = {"experiment": args.experiment, "claude_version": ver, "model": args.model,
            "lang_value": args.lang_value, "n": args.n,
            "user_claude_md_present": (Path.home() / ".claude" / "CLAUDE.md").exists(),
            "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    print(json.dumps(meta, indent=2), flush=True)
    pre = [args.claude, "-p", "ok", "--output-format", "json"] + (["--model", args.model] if args.model else [])
    try:
        res = json.loads(subprocess.run(pre, capture_output=True, text=True, timeout=120).stdout.strip().splitlines()[-1])
    except Exception as e:  # noqa: BLE001
        sys.exit(f"pre-check failed: {e}")
    if res.get("is_error"):
        sys.exit(f"pre-check error: {res.get('result')}")
    stop = root / "STOP"  # touch this file to stop after the current run
    if stop.exists():
        stop.unlink()
    log = []
    for i in range(1, args.n + 1):
        for cond in conditions(args.experiment):
            if stop.exists():
                break
            done = results / cond["name"] / f"run_{i:02d}.jsonl"
            if args.resume and done.exists() and not parse_run(done)["error"]:
                continue
            log.append(run_one(results, cond, i, args))
            (results / "meta.json").write_text(json.dumps(dict(meta, runs=log), indent=2), encoding="utf-8")
            if len(log) >= 3 and all(r["error"] for r in log[-3:]):
                print("[abort] three errors in a row (usage limit?); stopping", flush=True)
                stop.write_text("auto")
    analyze(args.experiment, results)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
HANGUL = re.compile(r"[가-힣ㄱ-ㆎ]")
LATIN = re.compile(r"[A-Za-z]")
KANA_CJK = re.compile(r"[぀-ヿ一-鿿]")
STRIP = [
    re.compile(r"```.*?```", re.S),  # fenced code
    re.compile(r"`[^`]*`"),  # inline code
    re.compile(r"https?://\S+"),  # urls
    re.compile(r"\S*[/\\_=]\S*"),  # paths, snake_case, assignments
    re.compile(r"\b[\w-]+\.(py|md|log|txt|json|csv|sh|js|ts|yml|yaml)\b"),  # file names
    re.compile(r"\b\w+\(\)"),  # calls like foo()
]


def classify(text: str) -> str:
    """ko / en / mixed / other (kana or CJK, no Hangul) / empty (too little text to judge)."""
    t = text
    for rx in STRIP:
        t = rx.sub(" ", t)
    h, l, k = len(HANGUL.findall(t)), len(LATIN.findall(t)), len(KANA_CJK.findall(t))
    if h == 0 and k > 0:
        return "other"
    if h == 0 and l < 8:
        return "empty"
    if h == 0:
        return "en"
    return "ko" if h / (h + l) >= 0.3 else "mixed"


LEAK = ("en", "other")


def is_denial(content) -> bool:
    s = json.dumps(content, ensure_ascii=False)
    return "Permission to use" in s or "has been denied" in s


def parse_run(path: Path) -> dict:
    """Main-thread text blocks before the last tool call are progress messages; after it, the answer.

    Each progress message records how many tool calls preceded it and whether the tool result
    right before it was a permission denial.
    """
    seq = []  # ("text", text, n_tools, after_denial) | ("tool",)
    result_text, model, error = None, None, None
    n_tools, last_was_denial, denials = 0, False, []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            model = ev.get("model")
        if ev.get("parent_tool_use_id"):
            continue  # subagent traffic
        msg = ev.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if ev.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and b.get("text", "").strip():
                    seq.append(("text", b["text"], n_tools, last_was_denial))
                elif b.get("type") == "tool_use":
                    seq.append(("tool",))
                    n_tools += 1
        elif ev.get("type") == "user" and isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    last_was_denial = is_denial(b.get("content"))
                    if last_was_denial:
                        denials.append(n_tools)
        elif ev.get("type") == "result":
            result_text = ev.get("result")
            if ev.get("is_error"):
                error = result_text or ev.get("subtype")
    last_tool = max([i for i, e in enumerate(seq) if e[0] == "tool"], default=-1)
    interim = [(e[1], classify(e[1]), e[2], e[3]) for i, e in enumerate(seq) if e[0] == "text" and i < last_tool]
    final = [e[1] for i, e in enumerate(seq) if e[0] == "text" and i > last_tool]
    if not final and result_text:
        final = [result_text]
    return {"tools": n_tools, "denials": denials, "model": model, "error": error,
            "interim": interim, "final": [(t, classify(t)) for t in final]}


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def _comb(n, k):
    if k < 0 or k > n:
        return 0
    r = 1
    for i in range(1, k + 1):
        r = r * (n - k + i) // i
    return r


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


def fisher_two_sided(a, b, c, d):
    """2x2 table [[a, b], [c, d]] -> two-sided p (sum of tables no more likely than the observed one)."""
    def pmf(x):
        return _comb(a + b, x) * _comb(c + d, a + c - x) / _comb(a + b + c + d, a + c)
    lo, hi = max(0, a + c - (c + d)), min(a + b, a + c)
    p0 = pmf(a)
    return min(1.0, sum(pmf(x) for x in range(lo, hi + 1) if pmf(x) <= p0 * (1 + 1e-9)))


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
def latest(exp: str):
    dirs = sorted(d for d in (RESULTS_ROOT / exp).glob("2*") if d.is_dir())
    return dirs[-1] if dirs else None


def analyze(exp: str, results: Path) -> None:
    print(f"\nexperiment: {exp}\nresults:    {results}")
    rows, audit = [], []
    for cond in conditions(exp):
        for p in sorted((results / cond["name"]).glob("run_*.jsonl")):
            r = parse_run(p)
            if r["error"]:
                continue
            msgs = [m for m in r["interim"] if m[1] != "empty"]
            leaks = [m for m in msgs if m[1] in LEAK]
            rows.append(dict(
                {f: cond[f] for f in FACTORS}, condition=cond["name"], run=p.stem, model=r["model"],
                tool_calls=r["tools"], denials=len(r["denials"]), progress_msgs=len(msgs),
                leak_msgs=len(leaks), leak=int(bool(leaks)),
                first_leak_at_tool=leaks[0][2] if leaks else "",
                first_leak_after_denial=int(leaks[0][3]) if leaks else "",
                leak_msgs_after_denial=sum(1 for m in leaks if m[3]),
                final_non_ko=sum(1 for _, lab in r["final"] if lab not in ("ko", "empty"))))
            for text, lab, k, den in r["interim"]:
                audit.append({"condition": cond["name"], "run": p.stem, "tool_idx": k, "label": lab,
                              "text": text.strip().replace("\n", " ")[:300]})
    if not rows:
        print("no finished runs")
        return
    with open(results / "summary_runs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    random.Random(0).shuffle(audit)
    with open(results / "audit_sample.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["condition", "run", "tool_idx", "label", "text", "human_label"])
        w.writeheader()
        for a in audit[:150]:
            w.writerow(dict(a, human_label=""))

    def line(label, rs):
        if not rs:
            return
        k, n = sum(r["leak"] for r in rs), len(rs)
        lo, hi = wilson(k, n)
        mk, mn = sum(r["leak_msgs"] for r in rs), sum(r["progress_msgs"] for r in rs)
        dn = sum(1 for r in rs if r["denials"])
        ad = sum(1 for r in rs if r["first_leak_after_denial"] == 1)
        print(f"  {label:28s} leak runs {k:2d}/{n:<2d} ({k / n:4.0%}, CI {lo:4.0%}-{hi:4.0%})  "
              f"non-Korean msgs {mk:3d}/{mn:<3d}  runs w/ denial {dn:2d}  leaks starting after denial {ad:2d}/{k}")

    print("\nper condition:")
    for cond in conditions(exp):
        rs = [r for r in rows if r["condition"] == cond["name"]]
        if rs:
            line(cond["name"], rs)
    varying = [f for f in FACTORS if len(EXPERIMENTS[exp][f + "s"]) > 1]
    print("\nmarginals:")
    for f in varying:
        for v in EXPERIMENTS[exp][f + "s"]:
            line(f"{f}={v}", [r for r in rows if r[f] == v])
    print("\nFisher exact, two-sided, run level (pairs of levels, other factors pooled):")
    for f in varying:
        for a, b in itertools.combinations(EXPERIMENTS[exp][f + "s"], 2):
            ra, rb = [r for r in rows if r[f] == a], [r for r in rows if r[f] == b]
            ka, kb = sum(r["leak"] for r in ra), sum(r["leak"] for r in rb)
            if ra and rb:
                p = fisher_two_sided(ka, len(ra) - ka, kb, len(rb) - kb)
                print(f"  {f}: {a} {ka}/{len(ra)} vs {b} {kb}/{len(rb)}  p = {p:.4f}")
    print(f"\nper-run table: {results / 'summary_runs.csv'}")
    print(f"classifier audit sample: {results / 'audit_sample.csv'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="list experiments and their conditions")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run")
    r.add_argument("experiment", choices=list(EXPERIMENTS))
    r.add_argument("--n", type=int, default=None, help="runs per condition (default: the experiment's)")
    r.add_argument("--model", default="opus")
    r.add_argument("--lang-value", default="korean", help='value for settings.json "language"')
    r.add_argument("--timeout", type=int, default=1500, help="seconds per run")
    r.add_argument("--claude", default="claude")
    r.add_argument("--resume", default=None, help="continue in an existing results dir, skipping finished runs")
    r.add_argument("--wait-until", default=None, help='start at local time "YYYY-MM-DD HH:MM"')
    fx = sub.add_parser("fixture", help="write one condition's workspace to a folder, e.g. for a manual TUI check")
    fx.add_argument("task", choices=["ledger", "textkit"])
    fx.add_argument("olang", choices=["en", "ko"])
    fx.add_argument("instr", choices=INSTRUCTIONS)
    fx.add_argument("perm", choices=["deny", "allow"])
    fx.add_argument("dest")
    fx.add_argument("--lang-value", default="korean")
    a = sub.add_parser("analyze")
    a.add_argument("experiment", choices=list(EXPERIMENTS))
    a.add_argument("--dir", default=None)
    args = ap.parse_args()
    if args.list or not args.cmd:
        for name, e in EXPERIMENTS.items():
            print(f"{name}  (n={e['n']})")
            for c in conditions(name):
                print("   ", c["name"])
        return
    if args.cmd == "fixture":
        dest = Path(args.dest).resolve()
        if dest.exists() and any(dest.iterdir()):
            sys.exit(f"{dest} is not empty")
        dest.mkdir(parents=True, exist_ok=True)
        make_fixture(dest, dict(task=args.task, olang=args.olang, instr=args.instr, perm=args.perm), args.lang_value)
        print(f"wrote {dest}\nprompt:\n{PROMPT}")
        return
    if args.cmd == "run":
        if args.n is None:
            args.n = EXPERIMENTS[args.experiment]["n"]
        cmd_run(args)
    else:
        d = Path(args.dir) if args.dir else latest(args.experiment)
        if d is None:
            sys.exit("no results yet")
        analyze(args.experiment, d)


if __name__ == "__main__":
    main()
