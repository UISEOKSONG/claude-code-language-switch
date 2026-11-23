"""Score TUI-check transcripts (~/.claude/projects jsonl) with the langleak classifier,
and list which memory/instruction files the session loaded."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import langleak as L  # noqa: E402


def analyze(path: Path):
    seq, n_tools, last_denial, memory = [], 0, False, set()
    model = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        s = json.dumps(ev, ensure_ascii=False)
        for m in re.findall(r'"(/[^"]*?(?:CLAUDE|AGENTS)\.md)"', s):
            memory.add(m)
        if ev.get("isSidechain"):
            continue
        msg = ev.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if ev.get("type") == "assistant":
            model = msg.get("model") or model
            if isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text" and b.get("text", "").strip():
                        seq.append(("text", b["text"], n_tools, last_denial))
                    elif b.get("type") == "tool_use":
                        seq.append(("tool",))
                        n_tools += 1
        elif ev.get("type") == "user" and isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    last_denial = L.is_denial(b.get("content"))
    last_tool = max([i for i, e in enumerate(seq) if e[0] == "tool"], default=-1)
    interim = [(e[1], L.classify(e[1]), e[2], e[3]) for i, e in enumerate(seq) if e[0] == "text" and i < last_tool]
    final = [L.classify(e[1]) for i, e in enumerate(seq) if e[0] == "text" and i > last_tool]
    msgs = [m for m in interim if m[1] != "empty"]
    leaks = [m for m in msgs if m[1] in L.LEAK]
    return dict(model=model, tools=n_tools, msgs=len(msgs), leaks=len(leaks), final=final,
                leak_text=[(m[2], m[3], m[0].strip().replace("\n", " ")[:100]) for m in leaks],
                memory=sorted(memory))


if __name__ == "__main__":
    for p in sys.argv[1:]:
        r = analyze(Path(p))
        print(Path(p).name[:3], "model", r["model"], "tools", r["tools"], "progress msgs", r["msgs"],
              "non-Korean", r["leaks"], "final", r["final"])
        print("   memory files:", r["memory"])
        for t in r["leak_text"]:
            print("   leak @tool", t[0], "after denial" if t[1] else "", "|", t[2])
