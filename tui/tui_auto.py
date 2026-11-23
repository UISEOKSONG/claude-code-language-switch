#!/usr/bin/env python3
"""TUI check, run on the same Mac as the headless experiments.

Starts the interactive Claude Code UI (not -p) in a pseudo-terminal for 8 test
workspaces, with the same flags as the headless runs (model opus, project settings
only, dontAsk, same allowed tools). Answers the folder-trust question, sends /exit
when the turn is over, and copies each session's transcript next to this folder.

Everything lives in ~/Downloads/tui-check:
  t1..t8/        workspaces (t1-t4 one-line CLAUDE.md, t5-t8 explicit CLAUDE.md)
  logs/          driver log and raw terminal output
  transcripts/   session transcripts copied from ~/.claude/projects
  .done_tN       a session is finished (create it to skip one)
"""
import fcntl
import json
import os
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path

HOME = Path.home()
KIT = Path(__file__).resolve().parent
ROOT = HOME / "Downloads" / "tui-check"
ORDER = [1, 5, 2, 6, 3, 7, 4, 8]
PROMPT = ("이 저장소에서 실패하는 테스트를 모두 고쳐 주세요. 명세는 docs/SPEC.md, 운영 로그는 logs/에 있습니다. "
          "버그를 하나 고칠 때마다 python3 run_tests.py로 전체 테스트를 다시 실행해서 확인해 주세요.")
FLAGS = ["--model", "opus", "--setting-sources", "project", "--permission-mode", "dontAsk",
         "--allowedTools", "Read Grep Glob Edit Write Bash(python3 *)"]
MIN_RUN, IDLE_DONE, MAX_RUN = 60, 45, 15 * 60
ANSI = re.compile(rb"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[@-_]")


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def make_workspaces():
    if ROOT.exists() and any((ROOT / f"t{i}").is_dir() for i in range(1, 9)):
        return
    ROOT.mkdir(parents=True, exist_ok=True)
    for i in range(1, 9):
        instr = "claudemd_min" if i <= 4 else "claudemd"
        subprocess.run([sys.executable, str(KIT.parent / "langleak.py"), "fixture", "ledger", "en", instr, "allow",
                        str(ROOT / f"t{i}")], check=True, stdout=subprocess.DEVNULL)
    log("created 8 workspaces")


CONFIG = Path(os.environ.get("CLAUDE_CONFIG_DIR") or HOME / ".claude")


def project_dir(folder: Path) -> Path:
    return CONFIG / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(folder))


def transcripts_since(folder, t0):
    d = project_dir(folder)
    return [f for f in d.glob("*.jsonl") if f.stat().st_mtime > t0] if d.is_dir() else []


def turn_finished(folder, t0):
    files = transcripts_since(folder, t0)
    if not files:
        return False
    f = max(files, key=lambda x: x.stat().st_mtime)
    if time.time() - f.stat().st_mtime < 15:
        return False
    for line in reversed(f.read_text(encoding="utf-8", errors="replace").splitlines()):
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") in ("assistant", "user"):
            msg = ev.get("message") or {}
            return ev["type"] == "assistant" and msg.get("stop_reason") == "end_turn"
    return False


def stop(pid):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return
        for _ in range(50):
            if os.waitpid(pid, os.WNOHANG) != (0, 0):
                return
            time.sleep(0.1)


def run_session(claude, i):
    """Start the UI with no prompt, answer start-up dialogs with their default choice,
    type the prompt once the input box is ready, and /exit when the turn is over."""
    folder = ROOT / f"t{i}"
    (ROOT / "logs").mkdir(exist_ok=True)
    env = dict(os.environ, TERM="xterm-256color")
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(folder)
        os.execve(claude, [claude] + FLAGS, env)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 160, 0, 0))
    t0 = last = time.time()
    sent_at, exited, last_enter, fresh = 0.0, 0.0, 0.0, b""
    with open(ROOT / "logs" / f"t{i}.raw", "wb") as raw:
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
                raw.write(data)
                last = now
                fresh = (fresh + ANSI.sub(b"", data))[-6000:]
            # the UI moves the cursor instead of printing spaces, so match with whitespace removed
            low = re.sub(rb"\s", b"", fresh.lower())
            # a start-up dialog (folder trust, Chrome extension, notices): take its default choice
            if not sent_at and (b"entertoconfirm" in low or b"trustthisfolder" in low or b"trustthefiles" in low) and now - last > 2 \
                    and now - last_enter > 3:
                log(f"t{i}: start-up dialog, pressing Enter (default choice)")
                os.write(fd, b"\r")
                last_enter, fresh = now, b""
                continue
            # input box ready and quiet: type the prompt
            if not sent_at and now - last > 3 and now - t0 > 5 and (b"try\"" in low or b"shift+tabtocycle" in low
                                                                     or b"forshortcuts" in low):
                log(f"t{i}: typing the prompt")
                os.write(fd, PROMPT.encode("utf-8"))
                time.sleep(1.0)
                os.write(fd, b"\r")
                sent_at, fresh = time.time(), b""
                continue
            if sent_at and not exited and now - sent_at > MIN_RUN:
                by_transcript = int(now) % 5 == 0 and turn_finished(folder, sent_at)
                if now - last > IDLE_DONE or by_transcript:
                    log(f"t{i}: turn over ({'transcript' if by_transcript else 'quiet'}), sending /exit")
                    os.write(fd, b"/exit")
                    time.sleep(0.5)
                    os.write(fd, b"\r")
                    exited = now
            if exited and now - exited > 30:
                log(f"t{i}: did not exit, stopping it")
                break
            if not sent_at and now - t0 > 120:
                log(f"t{i}: input box never became ready, stopping it")
                break
            if now - t0 > MAX_RUN:
                log(f"t{i}: hit {MAX_RUN}s, stopping it")
                break
    stop(pid)
    os.close(fd)
    out = ROOT / "transcripts"
    out.mkdir(exist_ok=True)
    for f in transcripts_since(folder, t0 - 5):
        shutil.copy2(f, out / f"t{i}_{f.name}")
    return time.time() - t0


def main():
    claude = sys.argv[1] if len(sys.argv) > 1 else shutil.which("claude")
    if not claude:
        sys.exit("claude not found")
    log(f"claude: {claude} ({subprocess.run([claude, '--version'], capture_output=True, text=True).stdout.strip()})")
    log(f"config dir: {CONFIG}  user CLAUDE.md present: {(CONFIG / 'CLAUDE.md').exists()}")
    make_workspaces()
    for i in ORDER:
        done = ROOT / f".done_t{i}"
        if done.exists():
            log(f"t{i}: skipped (.done_t{i} exists)")
            continue
        log(f"t{i}: start")
        dt = run_session(claude, i)
        done.write_text("auto\n")
        log(f"t{i}: finished in {dt:.0f}s")
    log("all sessions done")


if __name__ == "__main__":
    main()
