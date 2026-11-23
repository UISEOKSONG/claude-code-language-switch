#!/usr/bin/env python3
"""Claude Code language-leak experiment, v3 (long task, 4 language conditions x several models).

v3 drops the subagent factor (v2 showed it was not the driver) and adds a
"lang" condition (settings language only) and a model factor.

v2 notes:

v1 (short task, 5-8 tool calls) never reproduced the leak. Real sessions leaked
right after reading English-heavy subagent or Bash output, and more as the
session grew. v2 uses a longer task (8 seeded bugs, test re-run after every
fix, English spec and logs) and crosses two factors:

  language instruction: base (none) / claudemd (project CLAUDE.md says Korean)
                        / lang_hook (settings "language" + PostToolUse reminder)
  subagent:             nosub / sub (prompt asks to delegate investigation to an
                        English-prompted project subagent)

Only main-thread assistant text is scored (subagent text is excluded).

Usage
  python3 langleak2.py run --n 3
  python3 langleak2.py analyze
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
HERE = Path(__file__).resolve().parent
RESULTS_ROOT = HERE / "results3"
RESULTS = RESULTS_ROOT
LANGS = ["base", "claudemd", "lang", "lang_hook"]
MODELS = []  # set from --models
CONDITIONS = []  # "<model>.<lang>", set at run/analyze time

PROMPT = (
    "이 저장소에서 실패하는 테스트를 모두 고쳐 주세요. docs/SPEC.md와 logs/ 폴더에 단서가 있습니다. "
    "버그를 하나 고칠 때마다 전체 테스트를 다시 실행해서 확인해 주세요."
)
PROMPT_SUB = " 각 버그의 원인 조사는 investigator 서브에이전트에게 맡기세요."

KO_RULE = (
    "사용자에게 보이는 모든 문장은 한국어로 작성하세요. "
    "도구 호출 사이의 진행 설명도 포함입니다. 코드·명령어·파일명은 원문 그대로 둡니다."
)
HOOK_REMINDER = KO_RULE

AGENT_MD = """---
name: investigator
description: Investigates the root cause of one failing test in this repository and reports the exact fix. Use for every bug investigation.
tools: Read, Grep, Glob, Bash
---
You are a debugging investigator. For the failing behaviour you are given, read the relevant
source file, docs/SPEC.md and the files in logs/, run the tests if useful, and report the root
cause and the exact code change needed. Be thorough and quote the relevant spec section and log
lines. Do not edit any files.
"""

FILES = {}

FILES["README.md"] = """# ledger

Internal invoicing helpers used by the nightly billing batch.

The batch has been failing since the last refactor. The failing behaviour is
described in `docs/SPEC.md` and the batch output is in `logs/`.

## Modules
- `ledger/money.py` - parsing decimal amounts into integer cents
- `ledger/tax.py` - applying VAT to amounts in cents
- `ledger/discount.py` - tiered volume discounts
- `ledger/invoice.py` - invoice totals
- `ledger/dates.py` - payment due dates
- `ledger/currency.py` - currency conversion
- `ledger/csvline.py` - parsing one CSV line from the upstream export
- `ledger/report.py` - the one-line summary posted to the ops channel

## Running tests
    python3 -m unittest discover -s tests -v
"""

FILES["docs/SPEC.md"] = """# Billing specification (v3)

This document is the source of truth for the invoicing helpers. When the code
and this document disagree, the document wins.

## 1. Money
Amounts arrive as decimal strings such as `"19.99"`. `to_cents` must return the
exact integer number of cents. Binary floating point must not leak into the
result: `"19.99"` is 1999 cents, `"0.29"` is 29 cents.

## 2. Tax
`apply_tax(cents, rate)` returns the gross amount in cents. Fractions of a cent
are rounded half up (0.5 goes up). Example: 1005 cents at 10% is 1105.5, which
becomes 1106.

## 3. Discounts
Volume discounts are tiered by quantity:
- quantity >= 100: 10%
- quantity >= 50: 5%
- otherwise: 0%
Boundaries are inclusive. Exactly 100 units get 10%.

## 4. Invoice totals
`invoice_total(lines)` sums `unit_cents * quantity` for every line. Quantity
must never be ignored.

## 5. Due dates
`due_date(issued, terms_days)` adds `terms_days` calendar days. If the result
falls on a Saturday or Sunday, the due date moves forward to the following
Monday.

## 6. Currency
`convert(cents, rate)` converts from the invoice currency to the settlement
currency, where `rate` is "settlement units per invoice unit". 1000 cents at a
rate of 1.5 is 1500 cents. Round half up.

## 7. CSV
Upstream lines are comma separated. Fields may be wrapped in double quotes and
quoted fields may contain commas. Quotes are not part of the value.

## 8. Ops summary
`summary(n_invoices, total_cents)` returns e.g. `"1 invoice, 12.50 total"` or
`"3 invoices, 7.00 total"`. Use the singular form for exactly one invoice.
"""

FILES["ledger/__init__.py"] = ""

FILES["ledger/money.py"] = '''def to_cents(amount: str) -> int:
    """Parse a decimal amount string into integer cents."""
    return int(float(amount) * 100)
'''

FILES["ledger/tax.py"] = '''import math


def apply_tax(cents: int, rate: float) -> int:
    """Return gross cents after VAT, rounding half up."""
    return math.floor(cents * (1 + rate))
'''

FILES["ledger/discount.py"] = '''def discount_rate(quantity: int) -> float:
    """Return the tiered volume discount rate for a quantity."""
    if quantity > 100:
        return 0.10
    if quantity > 50:
        return 0.05
    return 0.0
'''

FILES["ledger/invoice.py"] = '''def invoice_total(lines):
    """lines: iterable of dicts with unit_cents and quantity."""
    total = 0
    for line in lines:
        total += line["unit_cents"]
    return total
'''

FILES["ledger/dates.py"] = '''import datetime as dt


def due_date(issued: dt.date, terms_days: int) -> dt.date:
    """Add terms_days; weekend due dates move to the following Monday."""
    d = issued + dt.timedelta(days=terms_days)
    if d.weekday() == 5:  # Saturday
        d += dt.timedelta(days=2)
    elif d.weekday() == 6:  # Sunday
        d += dt.timedelta(days=2)
    return d
'''

FILES["ledger/currency.py"] = '''def convert(cents: int, rate: float) -> int:
    """Convert invoice-currency cents to settlement-currency cents."""
    return int(cents / rate + 0.5)
'''

FILES["ledger/csvline.py"] = '''def parse_line(line: str):
    """Split one upstream CSV line into fields."""
    return [f.strip() for f in line.split(",")]
'''

FILES["ledger/report.py"] = '''def summary(n_invoices: int, total_cents: int) -> str:
    total = f"{total_cents // 100}.{total_cents % 100:02d}"
    return f"{n_invoices} invoices, {total} total"
'''

FILES["tests/__init__.py"] = ""

FILES["tests/test_ledger.py"] = '''import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ledger.money import to_cents
from ledger.tax import apply_tax
from ledger.discount import discount_rate
from ledger.invoice import invoice_total
from ledger.dates import due_date
from ledger.currency import convert
from ledger.csvline import parse_line
from ledger.report import summary


class TestMoney(unittest.TestCase):
    def test_whole(self):
        self.assertEqual(to_cents("12.00"), 1200)

    def test_19_99(self):
        self.assertEqual(to_cents("19.99"), 1999)

    def test_0_29(self):
        self.assertEqual(to_cents("0.29"), 29)

    def test_large(self):
        self.assertEqual(to_cents("1234.50"), 123450)


class TestTax(unittest.TestCase):
    def test_exact(self):
        self.assertEqual(apply_tax(1000, 0.10), 1100)

    def test_half_up(self):
        self.assertEqual(apply_tax(1005, 0.10), 1106)

    def test_zero_rate(self):
        self.assertEqual(apply_tax(999, 0.0), 999)


class TestDiscount(unittest.TestCase):
    def test_small(self):
        self.assertEqual(discount_rate(10), 0.0)

    def test_fifty(self):
        self.assertEqual(discount_rate(50), 0.05)

    def test_hundred(self):
        self.assertEqual(discount_rate(100), 0.10)

    def test_many(self):
        self.assertEqual(discount_rate(500), 0.10)


class TestInvoice(unittest.TestCase):
    def test_single(self):
        self.assertEqual(invoice_total([{"unit_cents": 250, "quantity": 1}]), 250)

    def test_quantity(self):
        lines = [{"unit_cents": 250, "quantity": 4}, {"unit_cents": 100, "quantity": 3}]
        self.assertEqual(invoice_total(lines), 1300)

    def test_empty(self):
        self.assertEqual(invoice_total([]), 0)


class TestDates(unittest.TestCase):
    def test_weekday(self):
        self.assertEqual(due_date(dt.date(2026, 11, 2), 3), dt.date(2026, 11, 5))

    def test_saturday(self):
        self.assertEqual(due_date(dt.date(2026, 11, 2), 5), dt.date(2026, 11, 9))

    def test_sunday(self):
        self.assertEqual(due_date(dt.date(2026, 11, 2), 6), dt.date(2026, 11, 9))

    def test_thirty(self):
        self.assertEqual(due_date(dt.date(2026, 11, 2), 30), dt.date(2026, 12, 2))


class TestCurrency(unittest.TestCase):
    def test_identity(self):
        self.assertEqual(convert(1000, 1.0), 1000)

    def test_rate(self):
        self.assertEqual(convert(1000, 1.5), 1500)

    def test_round(self):
        self.assertEqual(convert(1, 1.5), 2)


class TestCsv(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(parse_line("a,b,c"), ["a", "b", "c"])

    def test_quoted(self):
        self.assertEqual(parse_line('"ACME, Inc.",42,"x"'), ["ACME, Inc.", "42", "x"])

    def test_empty_field(self):
        self.assertEqual(parse_line("a,,c"), ["a", "", "c"])


class TestReport(unittest.TestCase):
    def test_plural(self):
        self.assertEqual(summary(3, 700), "3 invoices, 7.00 total")

    def test_singular(self):
        self.assertEqual(summary(1, 1250), "1 invoice, 12.50 total")


if __name__ == "__main__":
    unittest.main()
'''


def _batch_log(n_batches: int = 6, seed: int = 7) -> str:
    rnd = random.Random(seed)
    out = []
    errors = [
        ("money", "WARN", "parsed amount '19.99' as 1998 cents (expected 1999)"),
        ("tax", "WARN", "gross for invoice {inv} is 1105, finance export says 1106"),
        ("discount", "WARN", "customer {cust} ordered 100 units but received 5% instead of 10%"),
        ("invoice", "ERROR", "invoice {inv} total 350 does not match line sum 1300"),
        ("dates", "WARN", "due date for invoice {inv} fell on Tuesday; terms say Monday"),
        ("currency", "ERROR", "settlement amount 667 for 1000 cents at rate 1.5; expected 1500"),
        ("csv", "ERROR", 'row has 4 fields, expected 3: \'"ACME, Inc.",42,"x"\''),
        ("report", "INFO", "posted summary '1 invoices, 12.50 total' to #ops-billing"),
    ]
    t = 0
    for b in range(1, n_batches + 1):
        out.append(f"2026-11-{10 + b:02d}T02:00:00Z INFO  batch: starting nightly batch id={4400 + b}")
        for i in range(25):
            t += rnd.randint(1, 9)
            inv = rnd.randint(10000, 99999)
            cust = rnd.choice(["C-1042", "C-2210", "C-3307", "C-4471", "C-5530"])
            if rnd.random() < 0.3:
                mod, lvl, msg = rnd.choice(errors)
                out.append(f"2026-11-{10 + b:02d}T02:{t // 60 % 60:02d}:{t % 60:02d}Z {lvl:5s} {mod}: "
                           + msg.format(inv=inv, cust=cust))
            else:
                out.append(f"2026-11-{10 + b:02d}T02:{t // 60 % 60:02d}:{t % 60:02d}Z DEBUG worker: "
                           f"processed invoice {inv} for customer {cust} in {rnd.randint(3, 80)}ms")
        out.append(f"2026-11-{10 + b:02d}T02:59:00Z ERROR batch: batch {4400 + b} finished with errors; "
                   "reconciliation report rejected by finance")
    return "\n".join(out) + "\n"


FILES["logs/batch.log"] = _batch_log()
FILES["logs/finance_rejections.txt"] = """Finance reconciliation - rejected batches

Batch 4401: totals do not match the line items (quantities look ignored).
Batch 4402: VAT rounding differs from the finance export on half-cent values.
Batch 4403: settlement amounts are lower than invoice amounts at rates above 1.
Batch 4404: several customers with exactly 100 units did not get the 10% tier.
Batch 4405: one supplier name containing a comma shifted every column after it.
Batch 4406: due dates on Sundays were pushed to Tuesday instead of Monday.
Also: cent values like 19.99 are off by one in roughly 1 in 7 rows.
Also: the ops summary says "1 invoices", please fix the grammar.
"""

# Reference fixes, used only to verify the fixture.
FIXED = {
    "ledger/money.py": '''from decimal import Decimal


def to_cents(amount: str) -> int:
    return int(Decimal(amount) * 100)
''',
    "ledger/tax.py": '''from decimal import Decimal, ROUND_HALF_UP


def apply_tax(cents: int, rate: float) -> int:
    v = Decimal(cents) * (1 + Decimal(str(rate)))
    return int(v.quantize(Decimal(1), rounding=ROUND_HALF_UP))
''',
    "ledger/discount.py": '''def discount_rate(quantity: int) -> float:
    if quantity >= 100:
        return 0.10
    if quantity >= 50:
        return 0.05
    return 0.0
''',
    "ledger/invoice.py": '''def invoice_total(lines):
    return sum(l["unit_cents"] * l["quantity"] for l in lines)
''',
    "ledger/dates.py": '''import datetime as dt


def due_date(issued, terms_days):
    d = issued + dt.timedelta(days=terms_days)
    if d.weekday() == 5:
        d += dt.timedelta(days=2)
    elif d.weekday() == 6:
        d += dt.timedelta(days=1)
    return d
''',
    "ledger/currency.py": '''from decimal import Decimal, ROUND_HALF_UP


def convert(cents, rate):
    v = Decimal(cents) * Decimal(str(rate))
    return int(v.quantize(Decimal(1), rounding=ROUND_HALF_UP))
''',
    "ledger/csvline.py": '''import csv


def parse_line(line):
    return next(csv.reader([line]))
''',
    "ledger/report.py": '''def summary(n_invoices, total_cents):
    total = f"{total_cents // 100}.{total_cents % 100:02d}"
    noun = "invoice" if n_invoices == 1 else "invoices"
    return f"{n_invoices} {noun}, {total} total"
''',
}


def make_fixture(dst: Path, condition: str, lang_value: str) -> None:
    lang = condition.split(".")[-1]
    sub = "nosub"
    for rel, body in FILES.items():
        p = dst / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    (dst / ".claude").mkdir(exist_ok=True)
    settings = {}
    if lang == "claudemd":
        (dst / "CLAUDE.md").write_text("# Project instructions\n\n" + KO_RULE + "\n", encoding="utf-8")
    if lang in ("lang", "lang_hook"):
        settings["language"] = lang_value
    if lang == "lang_hook":
        hook = dst / ".claude" / "hooks" / "lang_reminder.py"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(
            "import json, sys\n"
            "try:\n    ev = json.load(sys.stdin).get('hook_event_name', 'PostToolUse')\n"
            "except Exception:\n    ev = 'PostToolUse'\n"
            "print(json.dumps({'hookSpecificOutput': {"
            "'hookEventName': ev, "
            f"'additionalContext': {HOOK_REMINDER!r}}}}}, ensure_ascii=False))\n",
            encoding="utf-8",
        )
        cmd = f"python3 '{hook}'"
        entry = [{"matcher": "*", "hooks": [{"type": "command", "command": cmd}]}]
        settings["hooks"] = {"PostToolUse": entry, "PostToolUseFailure": entry}
    if sub == "sub":
        ag = dst / ".claude" / "agents" / "investigator.md"
        ag.parent.mkdir(parents=True, exist_ok=True)
        ag.write_text(AGENT_MD, encoding="utf-8")
    (dst / ".claude" / "settings.json").write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )


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
            "--allowedTools", "Read Grep Glob Edit Write Bash(python3 *)",
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
    user_md = Path.home() / ".claude" / "CLAUDE.md"
    meta = {
        "claude_version": ver,
        "models": args.models,
        "lang_value": args.lang_value,
        "n": args.n,
        "user_claude_md_present": user_md.exists(),
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    global RESULTS
    RESULTS = RESULTS_ROOT / time.strftime("%Y%m%d_%H%M%S")
    RESULTS.mkdir(parents=True, exist_ok=True)
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print("\n모델별 인증 확인 중...")
    ok_models = []
    for m in [x.strip() for x in args.models.split(",") if x.strip()]:
        pre = [args.claude, "-p", "ok", "--output-format", "json", "--model", m]
        try:
            out = subprocess.run(pre, capture_output=True, text=True, timeout=120).stdout
            res = json.loads(out.strip().splitlines()[-1])
            err = res.get("result", "") if res.get("is_error") else None
        except Exception as e:  # noqa: BLE001
            err = str(e)
        print(f"  {m}: {'OK' if err is None else 'SKIP - ' + str(err)[:120]}")
        if err is None:
            ok_models.append(m)
    if not ok_models:
        sys.exit("사용 가능한 모델이 없습니다.")
    meta["models"] = ok_models
    conds = [(m, f"{m}.{l}") for m in ok_models for l in LANGS]
    print("실험을 시작합니다.\n")
    log = []
    for i in range(1, args.n + 1):
        for m, c in conds:  # interleave so time-of-day drift hits all conditions equally
            args.model = m
            rec = run_one(c, i, args)
            log.append(rec)
            if rec.get("error") and rec["seconds"] < 60:
                print(f"  [skip] {c} run {i:02d} 바로 에러: {rec['error']}")
    meta["runs"] = log
    meta_path = RESULTS / "meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
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
        "model": model,
        "error": error,
    }


def _pct(a, b):
    return f"{a:3d}/{b:<3d} {a / b:6.1%}" if b else f"{a:3d}/{b:<3d}    n/a"


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
    rows, examples = [], []
    global CONDITIONS
    CONDITIONS = sorted(d.name for d in RESULTS.iterdir() if d.is_dir())
    for c in CONDITIONS:
        for p in sorted((RESULTS / c).glob("run_*.jsonl")):
            r = parse_run(p)
            if r["error"]:
                continue
            im = [x for x in r["interim"] if x[1] != "empty"]
            fm = [lab for _, lab in r["final"] if lab != "empty"]
            first_en = next((k for _, lab, k, _ in im if lab in ("en", "other")), "")
            rows.append({
                "condition": c, "run": p.stem, "model": r["model"], "completed": r["ok"],
                "tool_calls": r["tools"], "sub_calls": r["sub_calls"],
                "interim_msgs": len(im),
                "interim_en": sum(1 for x in im if x[1] in ("en", "other")),
                "interim_mixed": sum(1 for x in im if x[1] == "mixed"),
                "interim_after_sub": sum(1 for x in im if x[3]),
                "interim_en_after_sub": sum(1 for x in im if x[3] and x[1] in ("en", "other")),
                "first_en_at_tool": first_en,
                "final_msgs": len(fm),
                "final_en": fm.count("en") + fm.count("mixed"),
            })
            for t, lab, k, sb in r["interim"]:
                if lab in ("en", "other") and len(examples) < 15:
                    examples.append((c, p.stem, k, t.strip().replace("\n", " ")[:110]))
    if not rows:
        print("no results yet")
        return
    with open(RESULTS / "summary_runs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print("\ncondition                    runs  tools(avg)  sub(avg)  interim en/total        runs_any_en  final non-ko")
    for c in CONDITIONS:
        rs = [r for r in rows if r["condition"] == c]
        if not rs:
            continue
        print(
            f"{c:28s} {len(rs):4d}  {sum(r['tool_calls'] for r in rs) / len(rs):9.1f}  "
            f"{sum(r['sub_calls'] for r in rs) / len(rs):7.1f}   "
            f"{_pct(sum(r['interim_en'] for r in rs), sum(r['interim_msgs'] for r in rs))}   "
            f"{sum(1 for r in rs if r['interim_en'] > 0):3d}/{len(rs):<3d}     "
            f"{sum(r['final_en'] for r in rs):3d}/{sum(r['final_msgs'] for r in rs):<3d}"
        )
    print("\nby factor (interim en/total, runs with any en):")
    groups = {}
    for r in rows:
        m, l = r["condition"].rsplit(".", 1)
        for key in (f"lang={l}", f"model={m}"):
            g = groups.setdefault(key, [0, 0, 0, 0])
            g[0] += r["interim_en"]; g[1] += r["interim_msgs"]; g[2] += r["interim_en"] > 0; g[3] += 1
    for key in sorted(groups):
        g = groups[key]
        print(f"  {key:36s} {_pct(g[0], g[1])}   {g[2]}/{g[3]} runs")
    if examples:
        print("\nEnglish interim examples [condition/run @tool#]:")
        for c, run, k, t in examples:
            print(f"  [{c}/{run} @{k}] {t}")
    print(f"\nper-run table: {RESULTS / 'summary_runs.csv'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--n", type=int, default=5, help="runs per condition")
    r.add_argument("--models", default="opus,claude-sonnet-5-5,claude-fable-5-2", help="comma-separated models, interleaved")
    r.add_argument("--lang-value", default="korean", help='value for settings "language"')
    r.add_argument("--timeout", type=int, default=1500)
    r.add_argument("--claude", default="claude")
    a = sub.add_parser("analyze")
    a.add_argument("--dir", default=None, help="results/<timestamp> folder (default: latest)")
    args = ap.parse_args()
    {"run": cmd_run, "analyze": cmd_analyze}[args.cmd](args)


if __name__ == "__main__":
    main()
