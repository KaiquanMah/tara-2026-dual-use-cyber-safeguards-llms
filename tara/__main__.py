import argparse
import sys
import json
from datetime import datetime, timezone, timedelta

UTC8 = timezone(timedelta(hours=8))
from pathlib import Path

from dotenv import load_dotenv

from .config import load_tracks
from .ingest import load_prompts
from .storage import Storage
from .runners import get_runner

'''
Entry point - python -m tara <command> [options]

Functions in this file:
  main()               Parse args, dispatch to list-tracks / run / run-all
  cmd_list_tracks()    Print a table of all tracks from config/tracks.json
  cmd_run_track()      Full orchestration for one track (load → run → save)
  cmd_run_all()        Loop cmd_run_track over every track in config

What cmd_run_track() does, step by step:

  1. LOAD CONFIG ──► reads config/tracks.json, picks the right runner
                       (OpenRouterRunner / ClaudeDirectRunner / OpenAIDirectRunner)
  2. LOAD PROMPTS ──► reads prompts/prompts.json → list of Prompt objects
  3. RESUME CHECK ──► checks outputs/{track}/raw/ - skips prompts that already
                       have a response file (so you can re-run without duplicating)
  4. SEND PROMPTS ──► for each new prompt:
                       runner.run_one(prompt) → single HTTP request to model API
                       - or in batch mode: runner.run_batch(prompts) → one job,
                         poll until done, collect all Response objects
  5. SAVE RESULTS ──► per-track output directory:
                       outputs/{track}/raw/{prompt_id}.json   (individual)
                       outputs/{track}/responses.json        (aggregated)
                       outputs/{track}/track.json            (run metadata)

Key inputs / outputs by file:
  config/tracks.json                 Input  - track definitions
  prompts/prompts.json               Input  - the prompt dataset
  outputs/{track}/raw/{id}.json      Output - one file per prompt response
  outputs/{track}/responses.json     Output - all responses keyed by prompt_id
  outputs/{track}/track.json         Output - who ran it, when, what config
'''


class Tee:
    '''Duplicates every print() call to both the terminal and a log file.
    Swap sys.stdout with a Tee instance; all writes go to both.
    
    1. **How does Tee work?** - It captures `sys.stdout`, which is where all `print()` output goes. 
       When `print()` is called, Python internally calls `sys.stdout.write()` and `sys.stdout.flush()`. 
       Since `sys.stdout` is replaced with a `Tee` instance, each `print()` call triggers 
       `Tee.write()` which writes to both the original stdout (terminal) and the log file.
    2. **Auto-create?** - `open(path, "a")` creates the file if it doesn't exist. 
       Append mode never truncates, it just writes at the end.
    3. **Where are write/flush/close used?** - `write()` and `flush()` are called implicitly by Python's `print()` function. 
       Every `print()` goes through `sys.stdout.write()` then `sys.stdout.flush()`. 
       `close()` exists but is never called - it's dead code right now (the file handle is only closed when the process exits, which auto-closes it anyway).


    1. **How it works:** `print()` internally calls `sys.stdout.write()` then `sys.stdout.flush()`. 
       By replacing `sys.stdout` with a `Tee` instance, every `print()` in the file (lines 69-75, 78-80, etc.) 
       automatically goes through `Tee.write()` → writes to both terminal + file. No call sites need changing.
    2. **Auto-create?** Yes - `open(path, "a")` creates the file if it doesn't exist. 
       Append mode never truncates.
    3. **write / flush / close:** `write` and `flush` are called **implicitly** by Python internals whenever `print()` runs. 
       You won't find explicit calls to them in the code - that's the whole trick. 
       `close` is dead code (only runs if someone calls it manually; the OS closes the handle on exit anyway).
    '''

    def __init__(self, log_path: Path):
        self.file = open(log_path, "a", encoding="utf-8")
        self.stdout = sys.stdout

    def write(self, text):
        self.stdout.write(text)
        self.file.write(text)

    def flush(self):
        self.stdout.flush()
        self.file.flush()

    def close(self):
        self.file.close()


def cmd_list_tracks(args):
    tracks = load_tracks(args.config)
    print(f"{'Track Key':<25} {'Name':<35} {'Provider':<12} {'Person':<10} {'Modes'}")
    print("-" * 95)
    for key, t in sorted(tracks.items()):
        print(f"{key:<25} {t.name:<35} {t.provider:<12} {t.person:<10} {', '.join(t.modes)}")


def cmd_run_track(args):
    tracks = load_tracks(args.config)
    if args.track not in tracks:
        print(f"Unknown track '{args.track}'. Available: {list(tracks.keys())}")
        sys.exit(1)

    track = tracks[args.track]
    if track.provider == "openrouter":
        runner_key = "openrouter"
    elif track.provider == "anthropic":
        runner_key = "claude_direct"
    elif track.provider == "openai":
        runner_key = "openai_direct"
    else:
        raise ValueError(f"Unknown provider: {track.provider}")

    RunnerClass = get_runner(runner_key)
    runner = RunnerClass(track)

    prompts = load_prompts(args.prompts)
    storage = Storage(args.output_dir, track)

    existing = storage.load_existing()
    to_run = [p for p in prompts if p.id not in existing]

    if not to_run:
        print(f"All {len(prompts)} prompts already have responses. Nothing to do.")
        responses = list(existing.values())
    else:
        print(f"Track: {track.name} ({track.key})")
        print(f"Person: {track.person}")
        print(f"Model: {track.model} via {track.access}")
        print(f"Prompts: {len(to_run)} to run, {len(existing)} already done")
        print(f"Mode: {args.mode}")
        print()

        responses = list(existing.values())

        if args.mode == "batch":
            batch_responses = runner.run_batch(to_run)
            for r in batch_responses:
                storage.save_response(r)
            responses.extend(batch_responses)
        else:
            for i, p in enumerate(to_run, 1):
                preview = p.text[:80].replace("\n", " ").strip()
                print(f"  [{i}/{len(to_run)}] {p.id}: {preview}...")
                print(f"    → sending...", end=" ", flush=True)
                r = runner.run_one(p)
                storage.save_response(r)
                responses.append(r)
                recv_preview = r.text[:80].replace("\n", " ").strip()
                print(f"done ({len(r.text)} chars, finish={r.finish_reason})")
                if r.model:
                    print(f"    model: {r.model}")
            print()

    storage.save_responses_aggregated(responses)
    storage.save_track_metadata(track, {
        "timestamp": datetime.now(UTC8).isoformat(),
        "mode": args.mode,
        "total_prompts": len(prompts),
        "completed": len(responses),
    })

    print(f"Saved {len(responses)} responses to outputs/{track.key}/")


def cmd_run_all(args):
    tracks = load_tracks(args.config)
    for track_key in tracks:
        print(f"\n{'='*60}")
        print(f"Running track: {track_key}")
        print(f"{'='*60}")
        args.track = track_key
        cmd_run_track(args)


def main():
    load_dotenv()

    # Tee all print() output to logs/yyyymm.log as well as the terminal
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"{datetime.now(UTC8).strftime('%Y%m')}.log"
    tee = Tee(log_file)
    sys.stdout = tee
    cmd_line = " ".join(sys.argv)
    print(f"\n@ $ {cmd_line}")

    parser = argparse.ArgumentParser(description="TARA - Evaluation Pipeline")
    parser.add_argument("--config", default="config/tracks.json",
                        help="Track config file (default: config/tracks.json)")
    parser.add_argument("--prompts", default="prompts/prompts.json",
                        help="Prompt dataset file (default: prompts/prompts.json)")
    parser.add_argument("--output-dir", default="outputs",
                        help="Output directory (default: outputs)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    p_list = subparsers.add_parser("list-tracks", help="List configured tracks")

    p_run = subparsers.add_parser("run", help="Run a single track")
    p_run.add_argument("track", help="Track key (e.g., cvp-claude)")
    p_run.add_argument("--mode", choices=["one_by_one", "batch"], default="one_by_one")

    p_all = subparsers.add_parser("run-all", help="Run all tracks")
    p_all.add_argument("--mode", choices=["one_by_one", "batch"], default="one_by_one")

    args = parser.parse_args()

    if args.command == "list-tracks":
        cmd_list_tracks(args)
    elif args.command == "run":
        cmd_run_track(args)
    elif args.command == "run-all":
        cmd_run_all(args)


if __name__ == "__main__":
    main()
