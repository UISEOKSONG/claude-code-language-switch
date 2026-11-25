#!/usr/bin/env python3
"""Stage 5 (PREREG_scope5.md): English progress notes across models, languages, real repositories,
and headless vs interactive (TUI) runs of Claude Code.

    python stage5.py selfcheck --python <py>             # every repository: upstream passes, each revert fails
    python stage5.py run --claude <claude> --python <py> --seed <s> --resume <dir> [--n 4]
    python stage5.py analyze --dir <dir>                  # tables, primary test, blind-audit sheet

<py> is a Python >= 3.11 with pytest installed (the launcher makes a venv). It is put first on PATH as
`python3` for every run, so the hook, the tests and Claude Code's Bash all use it. Both modes are scored
from the session transcript Claude Code writes under ~/.claude/projects (headless runs also keep their
stream-json, which is scored too, to check the two sources agree).

Shares the classifier, heading rule, hook and statistics with langleak.py.
"""
import argparse
import fcntl
import hashlib
import itertools
import json
import os
import pty
import random
import re
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
from pathlib import Path

import langleak as L

HERE = Path(__file__).resolve().parent
TASKS = HERE / "tasks"
ALLOWED_TOOLS = L.ALLOWED_TOOLS
TIMEOUT = 900
CONFIG = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")

MODELS = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}
LANGS = {
    "ko": dict(setting="korean",
               md="항상 한국어로 답하세요. 코드·명령어·파일명은 원문 그대로 둡니다.\n",
               prompt="이 저장소에서 실패하는 테스트를 모두 고쳐 주세요. 버그를 하나 고칠 때마다 {cmd}로 "
                      "전체 테스트를 다시 실행해서 확인해 주세요."),
    "ja": dict(setting="japanese",
               md="常に日本語で答えてください。コード・コマンド・ファイル名は原文のままにしてください。\n",
               prompt="このリポジトリで失敗しているテストをすべて直してください。バグを1つ直すたびに {cmd} で"
                      "テスト全体を再実行して確認してください。"),
    "zh": dict(setting="chinese",
               md="请始终用中文回答。代码、命令和文件名保持原样。\n",
               prompt="请修复这个仓库中所有失败的测试。每修复一个 bug，都请用 {cmd} 重新运行全部测试进行确认。"),
}
# English gloss of the three prompts: "Fix every failing test in this repository. After each bug fix,
# rerun the whole suite with {cmd} to check." CLAUDE.md: "Always answer in <language>. Keep code,
# commands and file names as they are." Plus "language": "<language>" in .claude/settings.json.
MODES = ["headless", "tui"]


def _reverts():
    data = json.loads((TASKS / "reverts.json").read_text(encoding="utf-8"))
    out = {}
    for repo, items in data.items():
        out[repo] = [(it["commit"], h["file"], h["after"], h["before"]) for it in items for h in it["hunks"]]
    # python-json-pointer: the same seven reverts as stages 3-4 (langleak.REAL_TASKS)
    out["jsonpointer"] = [(c, "jsonpointer.py", old, new) for c, old, new, _ in L.REAL_TASKS["jsonpointer"]["bugs"]]
    return out


REVERTS = _reverts()
REPOS = {
    "jsonpointer": "python3 -m unittest",
    "boltons": "python3 -m pytest",
    "more-itertools": "python3 -m unittest",
    "toolz": "python3 -m pytest",
}


EXP = "scope5"  # "scope6" (PREREG_scope6.md): Opus, Korean, headless, the `language` setting on vs off


def conditions():
    if EXP == "scope6":
        return [dict(model="opus", lang="ko", repo=r, mode="headless", setting=st,
                     name=f"opus.ko.{r}.headless.{st}")
                for r in ("jsonpointer", "more-itertools") for st in ("lang_on", "lang_off")]
    return [dict(model=m, lang=lg, repo=r, mode=md, name=f"{m}.{lg}.{r}.{md}")
            for m, lg, r, md in itertools.product(MODELS, LANGS, REPOS, MODES)]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def copy_repo(repo, dst: Path, only=None, reverted=True):
    """Copy tasks/<repo> to dst and apply its reverts (all, or only the ones whose commit is `only`)."""
    src = TASKS / repo
    for f in sorted(src.rglob("*")):
        if f.is_dir() or "__pycache__" in f.parts or f.suffix == ".pyc":
            continue
        out = dst / f.relative_to(src)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, out)
    if not reverted:
        return
    for commit, rel, after, before in REVERTS[repo]:
        if only is not None and commit != only:
            continue
        p = dst / rel
        s = p.read_text(encoding="utf-8")
        if s.count(after) != 1:
            raise RuntimeError(f"{repo}: revert of {commit} in {rel}: upstream text found {s.count(after)} times")
        p.write_text(s.replace(after, before), encoding="utf-8")


def make_workspace(dst: Path, cond):
    copy_repo(cond["repo"], dst)
    lg = LANGS[cond["lang"]]
    (dst / "CLAUDE.md").write_text(lg["md"], encoding="utf-8")
    hook = dst / ".claude" / "hooks" / "approve.py"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(L.APPROVE_HOOK, encoding="utf-8")
    settings = {"language": lg["setting"],
                "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
                    {"type": "command", "command": f"python3 '{hook}'"}]}]}}
    if cond.get("setting") == "lang_off":  # stage 6: CLAUDE.md and prompt only
        del settings["language"]
    (dst / ".claude" / "settings.json").write_text(json.dumps(settings, ensure_ascii=False, indent=2),
                                                   encoding="utf-8")


def prompt_for(cond):
    return LANGS[cond["lang"]]["prompt"].format(cmd=REPOS[cond["repo"]])


def make_env(python):
    """PATH with `python3` = the given interpreter (a wrapper script, so a venv keeps working),
    and Claude Code's auto-updater off. Returns (env, shim dir)."""
    shim = Path(tempfile.mkdtemp(prefix="langleak5_py_"))
    w = shim / "python3"
    w.write_text(f'#!/bin/sh\nexec "{python}" "$@"\n')
    w.chmod(0o755)
    env = dict(os.environ, PATH=f"{shim}{os.pathsep}{os.environ.get('PATH', '')}", DISABLE_AUTOUPDATER="1")
    return env, shim


# ---------------------------------------------------------------------------
# Self-check of the repositories
# ---------------------------------------------------------------------------
def run_suite(python, repo, work: Path):
    cmd = [python] + REPOS[repo].split()[1:]
    if "pytest" in cmd:
        cmd += ["-q", "-p", "no:cacheprovider"]
    p = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=900)
    out = p.stdout + p.stderr
    failing = sorted(set(re.findall(r"^(?:FAIL|ERROR): (\w+) ", out, re.M)
                         + re.findall(r"^(?:FAILED|ERROR) \S+::([\w\[\]\-.]+)", out, re.M)))
    return p.returncode, failing, "\n".join(out.splitlines()[-3:])


def selfcheck(python) -> int:
    ver = subprocess.run([python, "-c", "import sys, pytest; print(sys.version.split()[0], pytest.__version__)"],
                         capture_output=True, text=True)
    print(f"[selfcheck] python {python}: {ver.stdout.strip() or ver.stderr.strip()[-200:]}", flush=True)
    ok = ver.returncode == 0
    report = {}
    for repo in REPOS:
        commits = list(dict.fromkeys(c for c, *_ in REVERTS[repo]))
        res = {}
        for label, only, reverted in [("upstream", None, False), ("all", None, True)] + [(c, c, True) for c in commits]:
            with tempfile.TemporaryDirectory(prefix="langleak5_check_", ignore_cleanup_errors=True) as tmp:
                copy_repo(repo, Path(tmp), only=only, reverted=reverted)
                code, failing, tail = run_suite(python, repo, Path(tmp))
            res[label] = dict(exit=code, failing=failing)
            good = (code == 0) if label == "upstream" else (code != 0)
            ok &= good
            print(f"[selfcheck] {repo:15s} {label:16s} exit={code} failing={len(failing)} "
                  f"{'ok' if good else 'NOT OK'}  {' '.join(failing)[:160]}", flush=True)
            if not good:
                print("    " + tail.replace("\n", "\n    "), flush=True)
        report[repo] = res
    print(f"[selfcheck] {'OK' if ok else 'FAILED'}", flush=True)
    selfcheck.report = report
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# Running one session
# ---------------------------------------------------------------------------
def slug(path_name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", path_name)


def find_transcripts(work: Path, t0: float):
    tail = slug(work.name)
    pdir = CONFIG / "projects"
    out = []
    if pdir.is_dir():
        for d in pdir.iterdir():
            if d.is_dir() and d.name.endswith(tail):
                out += [f for f in d.glob("*.jsonl") if f.stat().st_mtime >= t0 - 5]
    return sorted(out, key=lambda f: f.stat().st_mtime)


ANSI = re.compile(rb"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[@-_]")


def _turn_finished(work, t0):
    files = find_transcripts(work, t0)
    if not files:
        return False
    f = files[-1]
    if time.time() - f.stat().st_mtime < 15:
        return False
    for line in reversed(f.read_text(encoding="utf-8", errors="replace").splitlines()):
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") in ("assistant", "user") and not ev.get("isSidechain"):
            msg = ev.get("message") or {}
            return ev["type"] == "assistant" and msg.get("stop_reason") == "end_turn"
    return False


def _stop(pid):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return
        for _ in range(50):
            try:
                if os.waitpid(pid, os.WNOHANG) != (0, 0):
                    return
            except ChildProcessError:
                return
            time.sleep(0.1)


def run_tui(claude, flags, prompt, work: Path, env, raw_path: Path, log):
    """Interactive UI in a pseudo-terminal: take the default choice on start-up dialogs (folder trust,
    notices), type the prompt once the input box is ready, send /exit when the turn is over.
    Same driver as tui/tui_auto.py (section 5 of the README)."""
    MIN_RUN, IDLE_DONE = 30, 45
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(work)
        os.execve(claude, [claude] + flags, dict(env, TERM="xterm-256color"))
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 160, 0, 0))
    t0 = last = time.time()
    sent_at, exited, last_enter, fresh, note = 0.0, 0.0, 0.0, b"", "ok"
    with open(raw_path, "wb") as raw:
        while True:
            now = time.time()
            r, _, _ = select.select([fd], [], [], 1.0)
            if r:
                try:
                    data = os.read(fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                if raw.tell() < 2_000_000:  # keep the first 2 MB of the terminal stream only
                    raw.write(data)
                last = now
                fresh = (fresh + ANSI.sub(b"", data))[-6000:]
            low = re.sub(rb"\s", b"", fresh.lower())  # the UI moves the cursor instead of printing spaces
            if not sent_at and b"entertoconfirm" in low and now - last > 2 and now - last_enter > 3:
                if b"trustthisfolder" in low:  # folder-trust dialog: the default is "No, exit"
                    log("folder-trust dialog, choosing 'Yes, I trust this folder'")
                    os.write(fd, b"\x1b[B")
                    time.sleep(0.5)
                else:
                    log("start-up dialog, pressing Enter (default choice)")
                os.write(fd, b"\r")
                last_enter, fresh = now, b""
                continue
            if not sent_at and now - last > 3 and now - t0 > 5 and (b"try\"" in low or b"shift+tabtocycle" in low
                                                                     or b"forshortcuts" in low or b"?forshortcuts" in low):
                os.write(fd, prompt.encode("utf-8"))
                time.sleep(1.0)
                os.write(fd, b"\r")
                sent_at, fresh = time.time(), b""
                continue
            if sent_at and not exited and now - sent_at > MIN_RUN:
                by_transcript = int(now) % 5 == 0 and _turn_finished(work, sent_at)
                if by_transcript or now - last > IDLE_DONE:
                    os.write(fd, b"/exit")
                    time.sleep(0.5)
                    os.write(fd, b"\r")
                    exited = now
                    note = "ok" if by_transcript else "ended on silence"
            if exited and now - exited > 30:
                break
            if not sent_at and now - t0 > 120:
                note = "input box never became ready"
                break
            if now - t0 > TIMEOUT:
                note = "timeout"
                break
    if not sent_at and note == "ok":
        note = "exited before the prompt"
    _stop(pid)
    os.close(fd)
    return note


def parse_transcript(path: Path, ulang: str) -> dict:
    """Same rule as langleak.parse_run, on a session transcript: main-thread text blocks before the
    last tool call are progress messages, text after it is the answer."""
    seq, model, error, prompt_seen, ended = [], None, None, False, False
    n_tools, last_was_denial, denials = 0, False, []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict) or ev.get("isSidechain") or ev.get("type") not in ("assistant", "user"):
            continue
        msg = ev.get("message") or {}
        content = msg.get("content")
        if ev.get("isApiErrorMessage"):
            error = json.dumps(content, ensure_ascii=False)[:200]
            continue
        if ev["type"] == "assistant":
            if msg.get("model") and msg["model"] != "<synthetic>":
                model = msg["model"]
            if msg.get("stop_reason") == "end_turn":
                ended = True
            for b in content if isinstance(content, list) else []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and b.get("text", "").strip():
                    seq.append(("text", b["text"], n_tools, last_was_denial))
                elif b.get("type") == "tool_use":
                    seq.append(("tool",))
                    n_tools += 1
        else:
            # every prompt names its test command ("python3 -m ...")
            if isinstance(content, str) and "python3 -m" in content and not ev.get("isMeta"):
                prompt_seen = True
            for b in content if isinstance(content, list) else []:
                if isinstance(b, dict) and b.get("type") == "text" and "python3 -m" in b.get("text", "") \
                        and not ev.get("isMeta"):
                    prompt_seen = True
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    last_was_denial = L.is_denial(b.get("content"))
                    if last_was_denial:
                        denials.append(n_tools)
    last_tool = max([i for i, e in enumerate(seq) if e[0] == "tool"], default=-1)
    interim = [(e[1], classify(e[1], ulang), e[2], e[3]) for i, e in enumerate(seq) if e[0] == "text" and i < last_tool]
    final = [e[1] for i, e in enumerate(seq) if e[0] == "text" and i > last_tool]
    if error is None and not prompt_seen:
        error = "prompt not in transcript"
    if error is None and not ended:
        error = "turn did not end"
    return {"tools": n_tools, "denials": denials, "model": model, "error": error,
            "interim": interim, "final": [(t, classify(t, ulang)) for t in final]}


HAN = re.compile(r"[一-鿿]")
KANA = re.compile(r"[぀-ヿ]")


def classify(text, ulang):
    """ko and ja: langleak.classify (ja with the corrected ASCII-only strip). zh: Han characters are the
    target script; kana or Hangul without Han, or more kana than Han, is "other"; same 8-letter floor and
    0.3 ratio."""
    if ulang != "zh":
        return L.classify(text, ulang)
    t = text
    for rx in L.STRIP_JA:
        t = rx.sub(" ", t)
    h, k, g, l = len(HAN.findall(t)), len(KANA.findall(t)), len(L.HANGUL.findall(t)), len(L.LATIN.findall(t))
    if (h == 0 and (k or g)) or k > h:
        return "other"
    if h == 0:
        return "empty" if l < 8 else "en"
    return "zh" if h / (h + l) >= 0.3 else "mixed"


def run_one(results: Path, cond, idx, args) -> dict:
    out_dir = results / cond["name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"run_{idx:02d}"
    env, shim = make_env(args.python)
    flags = ["--model", MODELS[cond["model"]], "--setting-sources", "project", "--permission-mode", "dontAsk",
             "--allowedTools", ALLOWED_TOOLS]
    prompt = prompt_for(cond)
    lines = []

    def log(m):
        lines.append(time.strftime("%H:%M:%S ") + m)

    for old in out_dir.glob(f"run_{idx:02d}.*"):  # a rerun of a failed run starts clean
        old.unlink()
    dt, note = 0.0, "not started"
    work = Path(tempfile.mkdtemp(prefix="langleak5_"))
    try:
        make_workspace(work, cond)
        t0 = time.time()
        if cond["mode"] == "headless":
            with open(f"{stem}.stream.jsonl", "w", encoding="utf-8") as fo, \
                    open(f"{stem}.stderr", "w", encoding="utf-8") as fe:
                try:
                    code = subprocess.run([args.claude, "-p", prompt, "--output-format", "stream-json", "--verbose"]
                                          + flags, cwd=work, stdout=fo, stderr=fe, timeout=TIMEOUT, env=env).returncode
                    note = "ok" if code == 0 else f"exit={code}"
                except subprocess.TimeoutExpired:
                    note = "timeout"
        else:
            note = run_tui(args.claude, flags, prompt, work, env, Path(f"{stem}.tty"), log)
        dt = time.time() - t0
        time.sleep(2)
        ts = find_transcripts(work, t0)
        if ts:
            with open(f"{stem}.transcript.jsonl", "w", encoding="utf-8") as fo:
                for f in ts:
                    fo.write(f.read_text(encoding="utf-8", errors="replace"))
    finally:
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(shim, ignore_errors=True)
    tp = Path(f"{stem}.transcript.jsonl")
    info = parse_transcript(tp, cond["lang"]) if tp.exists() else {"error": "no transcript", "model": None,
                                                                    "interim": [], "tools": 0, "denials": []}
    error = None if note in ("ok", "ended on silence") and not info["error"] else (info["error"] or note)
    if info.get("model") and not str(info["model"]).startswith(MODELS[cond["model"]]):
        error = f"model {info['model']}"
    status = {"condition": cond["name"], "run": idx, "seconds": round(dt, 1), "note": note, "error": error,
              "model": info.get("model"), "tools": info["tools"], "progress": len(info["interim"]),
              "finished": time.strftime("%Y-%m-%d %H:%M:%S")}
    Path(f"{stem}.status.json").write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
    if lines:
        Path(f"{stem}.driver.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  {cond['name']:34s} run {idx:02d}  {dt:5.0f}s  {note:16s} model={info.get('model')}  "
          f"tools={info['tools']}  progress={len(info['interim'])}  {'ERROR ' + str(error) if error else ''}",
          flush=True)
    return status


def done(results: Path, cond, idx) -> bool:
    p = results / cond["name"] / f"run_{idx:02d}.status.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))["error"] is None
    except (OSError, ValueError, KeyError):
        return False


def probe(args):
    """What python3 and pytest Claude Code's own Bash tool runs, in the run environment (haiku, headless)."""
    env, shim = make_env(args.python)
    with tempfile.TemporaryDirectory(prefix="langleak5_probe_") as tmp:
        cmd = [args.claude, "-p", "Run this exact command with the Bash tool and then reply with its output only: "
               "python3 -c \"import sys, pytest; print('PYVER', sys.version.split()[0], pytest.__version__)\"",
               "--output-format", "stream-json", "--verbose", "--setting-sources", "project",
               "--permission-mode", "dontAsk", "--allowedTools", "Bash(python3 *)", "--model", MODELS["haiku"]]
        out = subprocess.run(cmd, cwd=tmp, env=env, capture_output=True, text=True, timeout=300).stdout
    shutil.rmtree(shim, ignore_errors=True)
    m = re.search(r"PYVER (\d+\.\d+\.\d+) (\d[\w.]*)", out)
    return (m.group(1), m.group(2)) if m else None


def version(claude):
    return subprocess.run([claude, "--version"], capture_output=True, text=True).stdout.strip()


def cmd_run(args):
    args.claude = str(Path(shutil.which(args.claude) or args.claude).resolve())
    results = Path(args.resume)
    results.mkdir(parents=True, exist_ok=True)
    meta_p = results / "meta.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {
        "experiment": EXP, "seed": args.seed, "n": args.n, "claude_version": version(args.claude),
        "user_claude_md_present": (CONFIG / "CLAUDE.md").exists(), "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "python": args.python, "attempts": []}
    if version(args.claude) != meta["claude_version"]:
        print(f"Claude Code version changed: {meta['claude_version']} -> {version(args.claude)}; not running")
        sys.exit(3)
    if "selfcheck" not in meta:
        if selfcheck(args.python) != 0:
            print("self-check failed; not running")
            sys.exit(3)
        meta["selfcheck"] = selfcheck.report
    for m in sorted({MODELS[c["model"]] for c in conditions()}):  # exit 1 here usually means the usage limit; the launcher waits and retries
        try:
            res = json.loads(subprocess.run([args.claude, "-p", "ok", "--output-format", "json", "--model", m],
                                            capture_output=True, text=True, timeout=120,
                                            env=dict(os.environ, DISABLE_AUTOUPDATER="1")).stdout.strip().splitlines()[-1])
        except Exception as e:  # noqa: BLE001
            sys.exit(f"pre-check failed ({m}): {e}")
        if res.get("is_error"):
            sys.exit(f"pre-check error ({m}): {res.get('result')}")
    pv = probe(args)
    print(f"[probe] python3/pytest in Claude Code's Bash: {pv}", flush=True)
    if not pv or tuple(int(x) for x in pv[0].split(".")) < (3, 11):
        print("Claude Code's Bash does not run the requested python3 with pytest; not running")
        sys.exit(3)
    meta.setdefault("python_in_claude_bash", list(pv))
    meta["attempts"].append(time.strftime("%Y-%m-%d %H:%M:%S"))
    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in meta.items() if k != "selfcheck"}, ensure_ascii=False), flush=True)
    conds = conditions()
    errors_in_row = 0
    for i in range(1, meta["n"] + 1):
        order = conds[:]
        random.Random(meta["seed"] * 1000 + i).shuffle(order)
        for cond in order:
            if (results / "STOP").exists():
                print("STOP file found"); sys.exit(0)
            if done(results, cond, i):
                continue
            if version(args.claude) != meta["claude_version"]:
                print("Claude Code version changed during the batch; stopping"); sys.exit(3)
            if shutil.disk_usage(results).free < 1_000_000_000:
                print("less than 1 GB of free disk space; stopping"); sys.exit(3)
            st = run_one(results, cond, i, args)
            errors_in_row = errors_in_row + 1 if st["error"] else 0
            if errors_in_row >= 3:
                print("three errors in a row (usage limit?); stopping this attempt"); sys.exit(1)
    meta["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    analyze(results)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
def hypergeom_pmf(k, N, K, n):
    return L._comb(K, k) * L._comb(N - K, n - k) / L._comb(N, n)


def exact_stratified(strata):
    """Exact conditional test of a common odds ratio of 1 across 2x2 tables (a = TUI leaks, n1 = TUI runs,
    m = leaks, N = runs, per stratum): distribution of sum(a) given the margins, two-sided by summing
    the probabilities no larger than the observed one. Also the Mantel-Haenszel odds ratio."""
    dist = {0: 1.0}
    obs = 0
    num = den = 0.0
    for a, n1, m, N in strata:
        lo, hi = max(0, m - (N - n1)), min(m, n1)
        new = {}
        for s, p in dist.items():
            for k in range(lo, hi + 1):
                new[s + k] = new.get(s + k, 0.0) + p * hypergeom_pmf(k, N, m, n1)
        dist = new
        obs += a
        b, c = n1 - a, m - a
        d = (N - n1) - c
        num += a * d / N
        den += b * c / N
    p_obs = dist.get(obs, 0.0)
    p = min(1.0, sum(p for p in dist.values() if p <= p_obs * (1 + 1e-7)))
    mh = num / den if den else float("inf")
    return p, mh


def rows_for(results: Path):
    rows, msgs = [], []
    for cond in conditions():
        for st_p in sorted((results / cond["name"]).glob("run_*.status.json")):
            st = json.loads(st_p.read_text(encoding="utf-8"))
            if st["error"]:
                continue
            stem = str(st_p)[: -len(".status.json")]
            info = parse_transcript(Path(stem + ".transcript.jsonl"), cond["lang"])
            strict = [(i, t, lab) for i, (t, lab, _, _) in enumerate(info["interim"]) if L.is_strict_leak(t, lab)]
            anyleak = [i for i, (t, lab, _, _) in enumerate(info["interim"]) if lab in L.LEAK]
            mixed = [i for i, (t, lab, _, _) in enumerate(info["interim"]) if lab in L.LEAK + ("mixed",)]
            row = dict(cond, run=st["run"], model_seen=info["model"], progress=len(info["interim"]),
                       leak_strict=int(bool(strict)), leak_any=int(bool(anyleak)), leak_mixed=int(bool(mixed)),
                       first_strict=strict[0][0] + 1 if strict else "",
                       strict_msgs=len(strict), denials=len(info["denials"]),
                       final_non_target=sum(1 for _, lab in info["final"] if lab not in (cond["lang"], "empty")),
                       seconds=st["seconds"], note=st["note"])
            sp = Path(stem + ".stream.jsonl")
            if cond["mode"] == "headless" and sp.exists():
                s_info = L.parse_run(sp, "ko")
                s_strict = int(any(L.is_strict_leak(t, classify(t, cond["lang"])) for t, _, _, _ in s_info["interim"]))
                row["stream_agrees"] = int(s_strict == row["leak_strict"])
            rows.append(row)
            for i, (t, lab, _, _) in enumerate(info["interim"]):
                msgs.append(dict(name=cond["name"], run=st["run"], lang=cond["lang"], idx=i + 1, label=lab,
                                 strict=int(L.is_strict_leak(t, lab)), text=t))
    return rows, msgs


def analyze(results: Path):
    import csv
    global EXP
    try:
        EXP = json.loads((results / "meta.json").read_text())["experiment"]
    except (OSError, ValueError, KeyError):
        pass
    rows, msgs = rows_for(results)
    out = []

    def p(s=""):
        out.append(s)
        print(s, flush=True)

    p(f"experiment: {EXP}\nresults:    {results}\nruns used:  {len(rows)}")
    errs = [json.loads(f.read_text())["error"] for f in results.glob("*/run_*.status.json")]
    p(f"runs ended in an error and rerun (not used): {sum(1 for e in errs if e)}")
    stream = [r for r in rows if "stream_agrees" in r]
    if stream:
        p(f"headless runs, transcript vs stream-json strict label agree: {sum(r['stream_agrees'] for r in stream)}/{len(stream)}")
    tot = sum(r["leak_strict"] for r in rows)
    p(f"\nstrict leak runs overall: {tot}/{len(rows)}")

    def margin(key, levels):
        p(f"\nby {key}:")
        for lv in levels:
            rs = [r for r in rows if r[key] == lv]
            if not rs:
                continue
            k = sum(r["leak_strict"] for r in rs)
            lo, hi = L.wilson(k, len(rs))
            ka = sum(r["leak_any"] for r in rs)
            p(f"  {lv:15s} strict {k:3d}/{len(rs):3d} ({100*k/len(rs):3.0f}%, CI {100*lo:3.0f}-{100*hi:3.0f}%)"
              f"  any en/other {ka:3d}  progress msgs/run {sum(r['progress'] for r in rs)/len(rs):4.1f}")

    if EXP == "scope6":
        analyze6(rows, p, margin)
    else:
        analyze5(rows, p, margin, tot)
    p(f"\nfinal answers not in the target language: {sum(1 for r in rows if r['final_non_target'])} runs")
    p(f"leaking runs whose first strict leak is the first progress message: "
      f"{sum(1 for r in rows if r['first_strict'] == 1)}/{tot}")
    if rows:
        with open(results / "summary_runs.csv", "w", newline="", encoding="utf-8") as f:
            keys = sorted({k for r in rows for k in r})
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
        with open(results / "messages.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(msgs[0]) if msgs else ["name"])
            w.writeheader()
            w.writerows(msgs)
        blind_audit(results, msgs)
    (results / "analysis.txt").write_text("\n".join(out) + "\n", encoding="utf-8")


def analyze6(rows, p, margin):
    """Stage 6: `language` setting on vs off, stratified by repository (PREREG_scope6.md)."""
    margin("setting", ["lang_on", "lang_off"])
    margin("repo", ["jsonpointer", "more-itertools"])
    strata = []
    p("\nper repository (strict), lang_on vs lang_off, two-sided Fisher:")
    for rp in ("jsonpointer", "more-itertools"):
        on = [r for r in rows if r["repo"] == rp and r["setting"] == "lang_on"]
        off = [r for r in rows if r["repo"] == rp and r["setting"] == "lang_off"]
        if not on or not off:
            continue
        a, c = sum(r["leak_strict"] for r in on), sum(r["leak_strict"] for r in off)
        p(f"  {rp:15s} on {a}/{len(on)}  off {c}/{len(off)}  p = "
          f"{L.fisher_two_sided(a, len(on) - a, c, len(off) - c):.4f}")
        strata.append((a, len(on), a + c, len(on) + len(off)))
    pv, mh = exact_stratified(strata)
    ton = [r for r in rows if r["setting"] == "lang_on"]
    toff = [r for r in rows if r["setting"] == "lang_off"]
    p("\nprimary: `language` setting on vs off, strict outcome, exact conditional test stratified by repository")
    p(f"  on {sum(r['leak_strict'] for r in ton)}/{len(ton)}  off {sum(r['leak_strict'] for r in toff)}/{len(toff)}"
      f"  Mantel-Haenszel OR (on vs off) = {mh:.2f}  p = {pv:.4f}"
      f"{'' if sum(r['leak_strict'] for r in toff) >= 5 else '  [off leaked in fewer than 5 runs: not interpreted]'}")


def analyze5(rows, p, margin, tot):
    margin("mode", MODES)
    margin("model", MODELS)
    margin("lang", LANGS)
    margin("repo", REPOS)
    p("\nmodel x mode (strict):")
    for m in MODELS:
        cells = []
        for md in MODES:
            rs = [r for r in rows if r["model"] == m and r["mode"] == md]
            cells.append(f"{md} {sum(r['leak_strict'] for r in rs)}/{len(rs)}")
        p(f"  {m:8s} " + "   ".join(cells))
    p("\nmodel x lang (strict):")
    for m in MODELS:
        cells = []
        for lg in LANGS:
            rs = [r for r in rows if r["model"] == m and r["lang"] == lg]
            cells.append(f"{lg} {sum(r['leak_strict'] for r in rs)}/{len(rs)}")
        p(f"  {m:8s} " + "   ".join(cells))
    strata = []
    for m, lg, rp in itertools.product(MODELS, LANGS, REPOS):
        t = [r for r in rows if (r["model"], r["lang"], r["repo"], r["mode"]) == (m, lg, rp, "tui")]
        h = [r for r in rows if (r["model"], r["lang"], r["repo"], r["mode"]) == (m, lg, rp, "headless")]
        if t and h:
            a = sum(r["leak_strict"] for r in t)
            strata.append((a, len(t), a + sum(r["leak_strict"] for r in h), len(t) + len(h)))
    pv, mh = exact_stratified(strata)
    p("\nprimary: TUI vs headless, strict outcome, exact conditional test stratified by model x language x "
      f"repository ({len(strata)} strata)")
    p(f"  TUI {sum(r['leak_strict'] for r in rows if r['mode'] == 'tui')}/{sum(1 for r in rows if r['mode'] == 'tui')}"
      f"  headless {sum(r['leak_strict'] for r in rows if r['mode'] == 'headless')}/"
      f"{sum(1 for r in rows if r['mode'] == 'headless')}  Mantel-Haenszel OR = {mh:.2f}  p = {pv:.4f}"
      f"{'' if tot >= 10 else '  [fewer than 10 leaking runs overall: not interpreted]'}")


def blind_audit(results: Path, msgs):
    """Every strict-leak message plus an equal-sized random sample of the rest, shuffled, with no
    condition, mode or label: audit_blind.csv to fill in, audit_key.csv to join back."""
    import csv
    rnd = random.Random(5)
    leak = [m for m in msgs if m["strict"]]
    rest = [m for m in msgs if not m["strict"]]
    pick = leak + rnd.sample(rest, min(len(rest), len(leak)))
    rnd.shuffle(pick)
    with open(results / "audit_blind.csv", "w", newline="", encoding="utf-8") as f, \
            open(results / "audit_key.csv", "w", newline="", encoding="utf-8") as g:
        w, k = csv.writer(f), csv.writer(g)
        w.writerow(["id", "requested_language", "text", "your_label (target / en / mixed / other)"])
        k.writerow(["id", "name", "run", "idx", "label", "strict"])
        for m in pick:
            i = hashlib.sha1(f"{m['name']}{m['run']}{m['idx']}".encode()).hexdigest()[:8]
            w.writerow([i, m["lang"], m["text"], ""])
            k.writerow([i, m["name"], m["run"], m["idx"], m["label"], m["strict"]])


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("selfcheck")
    sc.add_argument("--python", required=True)
    r = sub.add_parser("run")
    r.add_argument("--claude", default="claude")
    r.add_argument("--python", required=True)
    r.add_argument("--seed", type=int, required=True)
    r.add_argument("--n", type=int, default=4)
    r.add_argument("--resume", required=True)
    r.add_argument("--experiment", default="scope5", choices=["scope5", "scope6"])
    a = sub.add_parser("analyze")
    a.add_argument("--dir", required=True)
    args = ap.parse_args()
    if args.cmd == "selfcheck":
        sys.exit(selfcheck(args.python))
    if args.cmd == "run":
        global EXP
        EXP = args.experiment
        cmd_run(args)
    else:
        analyze(Path(args.dir))


if __name__ == "__main__":
    main()
