#!/usr/bin/env python3
"""
cvp_logger.py - Semi-automated capture for the CVP arm (claude.ai, Opus 4.8).

Usage:
    python3 cvp_logger.py

For each target prompt it:
  1. Prints the prompt text (with its ID) for you to paste into a NEW claude.ai chat.
  2. Waits for you to paste the full response back (terminate with a line: ###).
  3. Asks for a finish classification (complete / refused / partial).
  4. Optionally captures the reasoning trace (terminate with: ###).
  5. Writes a schema-matched JSON row to outputs/cvp-claude/responses.json.

Resumable: skips prompt_ids already logged.

Run discipline (enforced by you, not the script):
  - claude.ai, Opus 4.8 selected, memory OFF, web search OFF
  - ONE fresh chat per prompt
  - For CN prompts: log one clean response, do NOT iterate or push further
"""

import json
import datetime
import pathlib

PROMPTS_FILE = "prompts.json"
OUT_FILE = "outputs/cvp-claude/responses.json"
MODEL = "claude-opus-4-8 (claude.ai, CVP)"

# intent_class strings EXACTLY as they appear in prompts.json
RUN_INTENT_CLASSES = {"Clearly Defensive", "Dual Use"}

# CN sample: 3 prompts spanning malware-dev / agent-misuse / ransomware
CN_SAMPLE_IDS = {"MAL-02-CN", "AGENT-02-CN", "TI-02-CN"}


def load_prompts():
    with open(PROMPTS_FILE) as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get("prompts", [])


def multiline_input(terminator="###"):
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == terminator:
            break
        lines.append(line)
    return "\n".join(lines)


def capture():
    prompts = load_prompts()

    targets = [p for p in prompts if p["intent_class"] in RUN_INTENT_CLASSES]
    targets += [p for p in prompts if p["prompt_id"] in CN_SAMPLE_IDS]
    # preserve file order, dedupe
    seen = set()
    ordered = []
    for p in prompts:
        if p["prompt_id"] in {t["prompt_id"] for t in targets} and p["prompt_id"] not in seen:
            ordered.append(p)
            seen.add(p["prompt_id"])
    targets = ordered

    outpath = pathlib.Path(OUT_FILE)
    out = []
    if outpath.exists():
        out = json.loads(outpath.read_text())
    done_ids = {r["prompt_id"] for r in out}

    print(f"Target prompts: {len(targets)} "
          # count how many of each intent class in the targets, for user reference
          f"({sum(1 for p in targets if p['intent_class']=='Clearly Defensive')} CD, "
          f"{sum(1 for p in targets if p['intent_class']=='Dual Use')} DU, "
          f"{sum(1 for p in targets if p['intent_class']=='Concerning')} CN)")
    print(f"Already logged: {len(done_ids)}\n")

    for i, p in enumerate(targets, 1):
        pid = p["prompt_id"]
        if pid in done_ids:
            print(f"[{i}/{len(targets)}] skip {pid} (already logged)")
            continue

        print("\n" + "=" * 72) # separator for readability in the terminal
        print(f"[{i}/{len(targets)}]  {pid}  |  {p['category']}  |  {p['intent_class']}  |  risk={p.get('risk_level','?')}")
        print("=" * 72)
        print(p["prompt"])
        print("=" * 72)
        print(">> NEW claude.ai chat (Opus 4.8, memory off). Paste prompt above.")
        print(">> Paste the FULL response below. End with a newline containing only: ###")
        response_text = multiline_input()

        finish = input("finish? [complete/refused/partial] (default complete): ").strip() or "complete"

        print(">> Reasoning trace? Paste it (or just type ### to skip). End with: ###")
        trace = multiline_input()

        out.append({
            "prompt_id": pid,
            "category": p["category"],
            "intent_class": p["intent_class"],
            "risk_level": p.get("risk_level", ""),
            "expected_behavior": p.get("expected_behavior", ""),
            "model": MODEL,
            "response_text": response_text,
            "finish_reason": finish,
            "reasoning_trace": trace,
            "timestamp": datetime.datetime.utcnow().isoformat(),
        })
        outpath.parent.mkdir(parents=True, exist_ok=True)
        outpath.write_text(json.dumps(out, indent=2))
        print(f"[saved] {pid}  ({len(out)} total logged)")

    print(f"\nDone. {len(out)} responses in {OUT_FILE}")


if __name__ == "__main__":
    capture()
