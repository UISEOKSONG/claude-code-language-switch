#!/usr/bin/env python3
"""Claude Code language-leak experiment, v6: do English permission-denial messages trigger the switch?

v5 showed the first English sentence right after "Permission to use Bash has been denied". v6 compares
  perm  deny (only python3 allowed in Bash, so ls/cat get denied) / allow (common read-only shell commands allowed)
  instr base / lang
on the English ledger task, single turn. Also records where denials happen.

v4 notes:

Same tasks, same code, same Korean prompt. The only manipulated variables are
  task         ledger / textkit (two different codebases, 8 seeded bugs each)
  output lang  en / ko   -- natural language of README, SPEC, logs and the
                            test runner's output (code identifiers identical)
  instruction  base (none) / lang (settings.json "language": "korean")
Model is fixed per invocation (--model). Unit of analysis is the run:
leak = at least one English progress sentence in the main thread.

Usage
  python3 langleak4.py run --n 8 --model opus
  python3 langleak4.py analyze
"""
import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import random
import math
import random
HERE = Path(__file__).resolve().parent
RESULTS_ROOT = HERE / "results6"
RESULTS = RESULTS_ROOT
PERMS = ["deny", "allow"]
INSTRS = ["base", "lang"]
CONDITIONS = [f"{p}.{i}" for p in PERMS for i in INSTRS]
TASK_NAMES, OLANGS = ["ledger"], ["en"]
ALLOWED = {
    "deny": "Read Grep Glob Edit Write Bash(python3 *)",
    "allow": ("Read Grep Glob Edit Write Bash(python3 *) Bash(ls *) Bash(ls) Bash(cat *) Bash(head *) Bash(tail *) "
              "Bash(grep *) Bash(wc *) Bash(find *) Bash(sed -n *) Bash(cd *) Bash(pwd)"),
}

PROMPT = (
    "이 저장소에서 실패하는 테스트를 모두 고쳐 주세요. 명세는 docs/SPEC.md, 운영 로그는 logs/에 있습니다. "
    "버그를 하나 고칠 때마다 python3 run_tests.py로 전체 테스트를 다시 실행해서 확인해 주세요."
)


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


def make_fixture(dst: Path, condition: str, lang_value: str) -> None:
    perm, instr = condition.split(".")
    for rel, body in build("ledger", "en").items():
        p = dst / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    (dst / ".claude").mkdir(exist_ok=True)
    settings = {"language": lang_value} if instr == "lang" else {}
    (dst / ".claude" / "settings.json").write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------
def run_one(condition: str, idx: int, args) -> dict:
    out_dir = RESULTS / condition
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / f"run_{idx:02d}.jsonl"
    err = out_dir / f"run_{idx:02d}.stderr"
    with tempfile.TemporaryDirectory(prefix=f"langleak_{condition}_") as tmp:
        work = Path(tmp)
        make_fixture(work, condition, args.lang_value)
        cmd = [
            args.claude, "-p", PROMPT,
            "--output-format", "stream-json", "--verbose",
            # only the fixture's .claude/settings.json; ignore ~/.claude/settings.json
            "--setting-sources", "project",
            "--permission-mode", "dontAsk",
            "--allowedTools", ALLOWED[condition.split(".")[0]],
        ]
        if args.model:
            cmd += ["--model", args.model]
        t0 = time.time()
        with open(raw, "w", encoding="utf-8") as fo, open(err, "w", encoding="utf-8") as fe:
            try:
                proc = subprocess.run(cmd, cwd=work, stdout=fo, stderr=fe, timeout=args.timeout)
                code = proc.returncode
            except subprocess.TimeoutExpired:
                code = "timeout"
        dt = time.time() - t0
    info = parse_run(raw)
    error = info["error"] or (None if code == 0 else f"exit={code}, see {err.name}")
    print(f"  {condition:28s} run {idx:02d}  exit={code}  {dt:5.0f}s  model={info['model']}  tools={info['tools']}")
    return {"condition": condition, "run": idx, "exit": code, "seconds": round(dt, 1),
            "model": info["model"], "error": error}


def cmd_run(args) -> None:
    if shutil.which(args.claude) is None:
        sys.exit(f"'{args.claude}' not found on PATH")
    ver = subprocess.run([args.claude, "--version"], capture_output=True, text=True).stdout.strip()
    meta = {"claude_version": ver, "model": args.model, "lang_value": args.lang_value, "n": args.n,
            "user_claude_md_present": (Path.home() / ".claude" / "CLAUDE.md").exists(),
            "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    wait_file = RESULTS_ROOT / "WAIT_UNTIL"
    if wait_file.exists():
        try:
            target = float(wait_file.read_text().strip())
        except ValueError:
            target = 0
        print(f"[wait] {time.strftime('%H:%M:%S', time.localtime(target))}까지 대기 (사용량 초기화 이후 시작)")
        while time.time() < target and not (RESULTS_ROOT / "START_NOW").exists():
            time.sleep(30)
        print(f"[wait] 시작 {time.strftime('%H:%M:%S')}")
    global RESULTS
    RESULTS = RESULTS_ROOT / time.strftime("%Y%m%d_%H%M%S")
    RESULTS.mkdir(parents=True, exist_ok=True)
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    pre = [args.claude, "-p", "ok", "--output-format", "json", "--model", args.model]
    try:
        res = json.loads(subprocess.run(pre, capture_output=True, text=True, timeout=120).stdout.strip().splitlines()[-1])
    except Exception as e:  # noqa: BLE001
        sys.exit(f"사전 점검 실패: {e}")
    if res.get("is_error"):
        sys.exit(f"사전 점검 에러: {res.get('result')}")
    print("인증 OK. 실험을 시작합니다.\n")
    log = []
    stop = RESULTS_ROOT / "STOP"
    go = RESULTS_ROOT / "GO"
    for f in (stop, go):
        if f.exists():
            f.unlink()
    for i in range(1, args.n + 1):
        if i == args.pilot + 1:
            print(f"\n[pilot] {args.pilot}회차까지 끝났습니다. 중간 분석:")
            cmd_analyze(args)
            print(f"\n[pilot] 계속하려면 {go}, 멈추려면 {stop} 파일을 만드세요. 기다리는 중... {time.strftime('%H:%M:%S')}")
            t0 = time.time()
            while not go.exists() and not stop.exists() and time.time() - t0 < args.pilot_wait:
                time.sleep(20)
            if not go.exists():
                print("[pilot] GO가 없어 여기서 멈춥니다.")
                break
            print(f"[pilot] GO 확인, 이어서 진행합니다. {time.strftime('%H:%M:%S')}")
        for c in CONDITIONS:
            if stop.exists():
                print("[stop] STOP 파일을 확인해 멈춥니다.")
                break
            rec = run_one(c, i, args)
            log.append(rec)
            (RESULTS / "meta.json").write_text(json.dumps(dict(meta, runs=log), ensure_ascii=False, indent=2), encoding="utf-8")
    cmd_analyze(args)


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------
HANGUL = re.compile(r"[가-힣ㄱ-ㆎ]")
LATIN = re.compile(r"[A-Za-z]")
STRIP = [
    re.compile(r"```.*?```", re.S),  # fenced code
    re.compile(r"`[^`]*`"),  # inline code
    re.compile(r"https?://\S+"),  # urls
    re.compile(r"\S*[/\\_=]\S*"),  # paths, snake_case, assignments
    re.compile(r"\b[\w-]+\.(py|md|log|txt|json|csv|sh|js|ts|yml|yaml)\b"),  # file names
    re.compile(r"\b\w+\(\)"),  # calls like foo()
]
KANA_CJK = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")


def classify(text: str) -> str:
    t = text
    for rx in STRIP:
        t = rx.sub(" ", t)
    h = len(HANGUL.findall(t))
    l = len(LATIN.findall(t))
    k = len(KANA_CJK.findall(t))
    if h == 0 and k > 0:
        return "other"
    if h == 0 and l < 8:
        return "empty"
    if h == 0:
        return "en"
    if h / (h + l) >= 0.3:
        return "ko"
    return "mixed"


SUB_TOOLS = {"Task", "Agent"}


def parse_run(path: Path) -> dict:
    """Main-thread assistant text only, split into interim (a tool call follows) and final."""
    seq = []  # ("text", str, n_tools_before, sub_seen) | ("tool", name)
    result_text = None
    model = None
    error = None
    n_tools = 0
    sub_seen = False
    denials = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            model = ev.get("model")
        if ev.get("type") == "assistant" and not ev.get("parent_tool_use_id"):
            for block in ev.get("message", {}).get("content", []) or []:
                if block.get("type") == "text" and block.get("text", "").strip():
                    seq.append(("text", block["text"], n_tools, sub_seen))
                elif block.get("type") == "tool_use":
                    name = block.get("name", "")
                    seq.append(("tool", name, n_tools, sub_seen))
                    n_tools += 1
                    if name in SUB_TOOLS:
                        sub_seen = True
        elif ev.get("type") == "user" and not ev.get("parent_tool_use_id"):
            content = ev.get("message", {}).get("content")
            if isinstance(content, list):
                for block in content:
                    if block.get("type") == "tool_result" and "Permission to use" in str(block.get("content")):
                        denials.append(n_tools)
        elif ev.get("type") == "result":
            result_text = ev.get("result")
            if ev.get("is_error"):
                error = result_text or ev.get("subtype")
    last_tool = max([i for i, e in enumerate(seq) if e[0] == "tool"], default=-1)
    interim = [(e[1], e[2], e[3]) for i, e in enumerate(seq) if e[0] == "text" and i < last_tool]
    final = [e[1] for i, e in enumerate(seq) if e[0] == "text" and i > last_tool]
    if not final and result_text:
        final = [result_text]
    return {
        "tools": n_tools,
        "sub_calls": sum(1 for e in seq if e[0] == "tool" and e[1] in SUB_TOOLS),
        "interim": [(t, classify(t), k, sb) for t, k, sb in interim],
        "final": [(t, classify(t)) for t in final],
        "ok": result_text is not None and error is None,
        "denials": denials,
        "model": model,
        "error": error,
    }


def _pct(a, b):
    return f"{a:3d}/{b:<3d} {a / b:6.1%}" if b else f"{a:3d}/{b:<3d}    n/a"


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
    """2x2 table [[a, b], [c, d]] -> two-sided p (sum of tables as or less likely)."""
    def pmf(x):
        return _comb(a + b, x) * _comb(c + d, a + c - x) / _comb(a + b + c + d, a + c)
    lo, hi = max(0, a + c - (c + d)), min(a + b, a + c)
    p0 = pmf(a)
    return min(1.0, sum(pmf(x) for x in range(lo, hi + 1) if pmf(x) <= p0 * (1 + 1e-9)))


def cmd_analyze(args) -> None:
    global RESULTS
    if getattr(args, "dir", None):
        RESULTS = Path(args.dir)
    elif RESULTS == RESULTS_ROOT:
        dirs = sorted(d for d in RESULTS_ROOT.glob("2*") if d.is_dir())
        if not dirs:
            print("no results yet")
            return
        RESULTS = dirs[-1]
    print(f"\nresults: {RESULTS}")
    rows, audit = [], []
    for c in CONDITIONS:
        for p in sorted((RESULTS / c).glob("run_*.jsonl")):
            r = parse_run(p)
            if r["error"]:
                continue
            im = [x for x in r["interim"] if x[1] != "empty"]
            fm = [lab for _, lab in r["final"] if lab != "empty"]
            en = [x for x in im if x[1] in ("en", "other")]
            rows.append({
                "condition": c, "run": p.stem, "model": r["model"], "tool_calls": r["tools"],
                "interim_msgs": len(im), "interim_en": len(en), "interim_other": sum(1 for x in im if x[1] == "other"),
                "leak": int(bool(en)), "first_en_at_tool": en[0][2] if en else "",
                "denials": len(r["denials"]), "first_denial_at_tool": r["denials"][0] if r["denials"] else "",
                "leak_right_after_denial": int(bool(en) and any(d <= en[0][2] <= d + 1 for d in r["denials"])),
                "final_non_ko": sum(1 for x in fm if x != "ko"),
            })
            for t, lab, k, _ in r["interim"]:
                audit.append({"condition": c, "run": p.stem, "tool_idx": k, "label": lab,
                              "text": t.strip().replace("\n", " ")[:300]})
    if not rows:
        print("no results yet")
        return
    with open(RESULTS / "summary_runs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    random.Random(0).shuffle(audit)
    with open(RESULTS / "audit_sample.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["condition", "run", "tool_idx", "label", "text", "human_label"])
        w.writeheader()
        for a in audit[:150]:
            w.writerow(dict(a, human_label=""))

    def show(name, rs):
        k, n = sum(r["leak"] for r in rs), len(rs)
        lo, hi = wilson(k, n)
        sk, sn = sum(r["interim_en"] for r in rs), sum(r["interim_msgs"] for r in rs)
        onsets = sorted(r["first_en_at_tool"] for r in rs if r["first_en_at_tool"] != "")
        med = onsets[len(onsets) // 2] if onsets else "-"
        print(f"  {name:22s} leak runs {k:2d}/{n:<2d} ({k / n if n else 0:4.0%}, 95% CI {lo:4.0%}-{hi:4.0%})"
              f"   en sentences {sk:3d}/{sn:<3d}   onset median tool #{med}")

    print("\nper condition (run-level):")
    for c in CONDITIONS:
        rs = [r for r in rows if r["condition"] == c]
        if rs:
            show(c, rs)
    print("\nmarginals:")
    for i, vals in ((0, PERMS), (1, INSTRS)):
        for v in vals:
            show(["perm", "instr"][i] + "=" + v, [r for r in rows if r["condition"].split(".")[i] == v])
    print("\ntests (Fisher exact, two-sided, run-level):")
    for instr in INSTRS:
        de = [r for r in rows if r["condition"] == f"deny.{instr}"]
        al = [r for r in rows if r["condition"] == f"allow.{instr}"]
        a_, b_ = sum(r["leak"] for r in de), len(de) - sum(r["leak"] for r in de)
        c_, d_ = sum(r["leak"] for r in al), len(al) - sum(r["leak"] for r in al)
        if de and al:
            print(f"  deny vs allow | instr={instr:4s}: {a_}/{a_ + b_} vs {c_}/{c_ + d_}, p = {fisher_two_sided(a_, b_, c_, d_):.4f}")
    leaks = [r for r in rows if r["leak"]]
    print(f"\nleaking runs whose first non-Korean sentence came right after a permission denial: "
          f"{sum(r['leak_right_after_denial'] for r in leaks)}/{len(leaks)}")
    print(f"runs with any denial: deny={sum(1 for r in rows if r['condition'].startswith('deny') and r['denials'])}/"
          f"{sum(1 for r in rows if r['condition'].startswith('deny'))}, allow={sum(1 for r in rows if r['condition'].startswith('allow') and r['denials'])}/"
          f"{sum(1 for r in rows if r['condition'].startswith('allow'))}")
    print(f"\nper-run table: {RESULTS / 'summary_runs.csv'}")
    print(f"classifier audit sample (150 sentences, fill human_label): {RESULTS / 'audit_sample.csv'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--n", type=int, default=4)
    r.add_argument("--pilot", type=int, default=99, help="pause after this many rounds and wait for GO/STOP")
    r.add_argument("--pilot-wait", type=int, default=7200, help="seconds to wait for GO before stopping")
    r.add_argument("--model", default="opus")
    r.add_argument("--lang-value", default="korean")
    r.add_argument("--timeout", type=int, default=1500)
    r.add_argument("--claude", default="claude")
    a = sub.add_parser("analyze")
    a.add_argument("--dir", default=None)
    args = ap.parse_args()
    {"run": cmd_run, "analyze": cmd_analyze}[args.cmd](args)


if __name__ == "__main__":
    main()
