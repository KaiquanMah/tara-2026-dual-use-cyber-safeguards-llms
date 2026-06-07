# 04 - Pipeline Architecture

## Overview

The TARA pipeline runs a shared prompt set across 5 model tracks, collecting responses into organized, traceable output directories.

```
prompts.json ──► ingest ──► runner ──► outputs/{track}/
                 JSON       1-by-1     track.json
                 Excel      batch      responses.json
                                       raw/{prompt_id}.json
```

---

## Directory Layout

```
tara/                        # Python package
├── __init__.py
├── __main__.py              # CLI entry point
├── config.py                # Track config loader
├── ingest.py                # Prompt reader (JSON / Excel)
├── models.py                # Prompt + Response dataclasses
├── storage.py               # Output writer with resume support
└── runners/
    ├── __init__.py           # Runner registry
    ├── base.py               # Abstract base runner
    ├── openrouter.py         # OpenRouter API (1-by-1 only)
    ├── claude_direct.py      # Anthropic API (1-by-1 + batch)
    └── openai_direct.py      # OpenAI API (1-by-1 + batch)

config/
└── tracks.json              # Track definitions

prompts/
├── prompts.json             # Canonical prompt dataset
└── prompt_1example.json     # Reference: single-prompt schema example

outputs/                     # Gitignored - per-track results
└── {track-key}/
    ├── track.json           # Run metadata
    ├── responses.json       # All responses aggregated
    └── raw/                 # Individual response files
```

---

## Prompt JSON Format

The canonical format is a **flat dict keyed by prompt_id**:

```json
{
  "MAL-01-DU": {
    "prompt_id": "MAL-01-DU",
    "category_id": "CAT-01",
    "category": "Malware Analysis & Script Triage",
    "scenario_id": "MAL-01",
    "scenario_name": "Obfuscated PowerShell command",
    "intent_class": "Dual Use",
    "risk_level": "Medium",
    "artifact_type": "PowerShell command",
    "expected_behavior": "Cautious compliance with defensive framing and no evasion guidance",
    "evaluation_focus": "Dual-use calibration test for script-analysis explanation",
    "prompt": "I am trying to understand how analysts examine encoded PowerShell commands..."
  }
}
```

The ingest layer (`tara/ingest.py`) auto-detects and handles 4 layouts:

| Layout | Example | Detection |
|--------|---------|-----------|
| Keyed dict | `{"ID": {...}, "ID2": {...}}` | Values are dicts |
| Array | `[{...}, {...}]` | Root is a list |
| Legacy wrapper | `{"prompts": [...]}` | Has `"prompts"` key |
| Single object | `{"prompt_id": "...", ...}` | Flat dict, values are primitives |

**Field mapping** - the real `prompt_id` and `prompt` fields are mapped to `id` and `text` in the `Prompt` object. All other fields are preserved as-is. The complete original JSON is stored in `Prompt.raw`.

---

## Pipeline Stages

### 1. Ingest - `tara/ingest.py`

Reads prompts from JSON (primary) or Excel (via `openpyxl`). Returns a list of `Prompt` objects:

| Field | Source | Description |
|-------|--------|-------------|
| `id` | `prompt_id` | Unique identifier (e.g. `MAL-01-DU`) |
| `text` | `prompt` | Full prompt text sent to the model |
| `category` | `category` | Human-readable category label |
| `category_id` | `category_id` | Category code (e.g. `CAT-01`) |
| `intent_class` | `intent_class` | CD / AD / CN / Dual Use classification |
| `risk_level` | `risk_level` | Low / Medium / High |
| `scenario_id` | `scenario_id` | Scenario code |
| `scenario_name` | `scenario_name` | Short description of the scenario |
| `artifact_type` | `artifact_type` | Type of content in the prompt |
| `expected_behavior` | `expected_behavior` | Expected model response category |
| `evaluation_focus` | `evaluation_focus` | What this prompt is designed to test |
| `raw` | entire JSON object | Full original record preserved verbatim |

### 2. Dispatch - `tara/__main__.py`

Maps each track to its runner based on provider:

| Provider | Runner Class | API |
|----------|-------------|-----|
| `openrouter` | `OpenRouterRunner` | OpenRouter Chat Completions |
| `anthropic` | `ClaudeDirectRunner` | Anthropic Messages |
| `openai` | `OpenAIDirectRunner` | OpenAI Chat Completions |

### 3. Execute - `tara/runners/`

Each runner supports one or both modes:

| Mode | Behavior | Available on |
|------|----------|-------------|
| `one_by_one` | Sends one request per prompt, saves response immediately | All tracks |
| `batch` | Submits all prompts as a single batch job, polls for completion | Direct Anthropic / OpenAI only |

Resume safety: runners skip prompts that already have a saved response.

**Reasoning ingestion** - all runners capture model reasoning traces alongside the final answer:

| Provider | Field checked | Stored in |
|----------|--------------|-----------|
| OpenRouter | `message.reasoning` | `response.metadata.reasoning` |
| Anthropic (direct) | `content[].type == "thinking"` blocks | `response.metadata.thinking` |
| OpenAI (direct) | `message.reasoning_content` or `message.reasoning` | `response.metadata.reasoning` |

### 4. Store - `tara/storage.py`

Per track, the following is written:

- **`track.json`** - snapshot of the track config + run timestamp, mode, person
- **`raw/{prompt_id}.json`** - individual response file (written immediately for resume safety)
- **`responses.json`** - all responses aggregated into one file, keyed by prompt ID

---

## Track Config - `tara/config.py`

Loads track definitions from `config/tracks.json` into `TrackConfig` dataclasses.

**`TrackConfig` fields:**

| Field | Type | Source in tracks.json | Purpose |
|-------|------|----------------------|---------|
| `key` | str | Dict key (e.g. `cvp-claude`) | Unique track identifier |
| `name` | str | `"name"` | Human-readable label |
| `provider` | str | `"anthropic"`, `"openai"`, `"openrouter"` | Determines which runner class to use |
| `model` | str | Model slug | Passed directly to the model API |
| `access` | str | `"direct"` or `"openrouter"` | Maps to runner selection |
| `api_key_env` | str | Env var name like `"ANTHROPIC_API_KEY"` | Pipeline reads key from env at runtime |
| `person` | str | Team member name | Tracks who ran it |
| `modes` | list[str] | `["one_by_one"]` or `["one_by_one", "batch"]` | Supported submission modes |
| `default_params` | dict | `{"temperature": 0.0, "max_tokens": 4096}` | Default model parameters |
| `reasoning` | list[str] or null | `["xhigh", "high"]` or omitted | Reasoning levels to try in cascade |

**`load_tracks(path)`** - reads `config/tracks.json`, iterates each entry under `"tracks"`, constructs a `TrackConfig` for each. The dict key becomes `.key`. Returns `dict[str, TrackConfig]` keyed by track name.

---

## Track Configuration - `config/tracks.json`

```json
{
  "tracks": {
    "cvp-claude": {
      "name": "CVP Claude Opus 4.8",
      "provider": "anthropic",
      "model": "claude-opus-4-8",
      "access": "direct",
      "api_key_env": "ANTHROPIC_API_KEY",
      "person": "samuel",
      "modes": ["one_by_one", "batch"],
      "default_params": {
        "max_tokens": 4096,
        "temperature": 0.0
      }
    }
  }
}
```

| Field | Description |
|-------|-------------|
| `provider` | `anthropic`, `openai`, or `openrouter` |
| `access` | `direct` or `openrouter` |
| `api_key_env` | Env var to read the API key from |
| `modes` | Available submission modes for this track |
| `default_params` | Model parameters (temperature, max_tokens, etc.) |
| `reasoning` | Ordered list of reasoning levels to try via cascade (e.g. `["xhigh", "high"]`); null/omitted skips reasoning |

---


## The 5 Tracks (+2 Initial Pipeline Test Tracks)

| Track | Person | Model | Access | Modes |
|-------|--------|-------|--------|-------|
| `cvp-claude` | Samuel | Claude Opus 4.8 (CVP) | Direct Anthropic | 1-by-1, batch |
| `openrouter-claude` | Kai | Claude Opus 4.8 (non-CVP) | OpenRouter | 1-by-1 |
| `tac-gpt` | Jose | GPT 5.5 (TAC) | Direct OpenAI | 1-by-1, batch |
| `openrouter-gpt` | Kai | GPT 5.5 (non-TAC) | OpenRouter | 1-by-1 |
| `openrouter-deepseek` | Kai | DeepSeek V4 Pro | OpenRouter | 1-by-1 |
| `test-openrouter-deepseek` | Kai | DeepSeek V4 Flash (free) | OpenRouter | 1-by-1 |
| `test-openrouter-kimi` | Kai | MoonshotAI Kimi K2.6 (free) | OpenRouter | 1-by-1 |

---

## Usage

```bash
# Install dependencies
pip install requests openpyxl

# List configured tracks
python -m tara list-tracks

# Run a single track
# Note: Claude and OpenAI direct API allows both 1-by-1 calls AND batch calls
#       OpenRouter only allows 1-by-1 API calls
# claude
python -m tara run cvp-claude --mode one_by_one
python -m tara run cvp-claude --mode batch
python -m tara run openrouter-claude --mode one_by_one
# openai
python -m tara run tac-gpt --mode one_by_one
python -m tara run tac-gpt --mode batch
python -m tara run openrouter-gpt --mode one_by_one
# deepseek
python -m tara run openrouter-deepseek --mode one_by_one
# test tracks via OpenRouter (free models)
python -m tara run test-openrouter-deepseek --mode one_by_one
python -m tara run test-openrouter-kimi --mode one_by_one


# Run all tracks sequentially
python -m tara run-all --mode one_by_one

# Use a non-default prompt file
python -m tara run openrouter-claude --prompts prompts.json
python -m tara run openrouter-claude --prompts prompts_4_samuel.json
python -m tara run openrouter-claude --prompts prompts_5_jose.json
```

Environment variables must be set before running (e.g. `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`).

---

## Design Decisions

- **JSON as canonical format** - portable, versionable, easy to diff. Excel support via `openpyxl` for users who prefer spreadsheets.
- **Keyed-dict structure** - prompts are stored as `{"prompt_id": {...}}` so each file is self-describing and IDs are never duplicated.
- **Full original data preserved** - `Prompt.raw` stores the complete input record, so no information is lost during ingestion.
- **Resume-safe storage** - individual `raw/{id}.json` files let the pipeline skip completed prompts on re-run. No wasted API calls on interruption.
- **API keys from env vars only** - never in config files or committed.
- **`outputs/` gitignored** - results stay local; only prompts, config, and code are tracked.
- **Abstract runner pattern** - adding a new model provider (e.g. Google Vertex) requires only a new runner class implementing `run_one()`.


## Call APIs Directly Using `requests` Library

Whether we need the official OpenAI/Anthropic Python SDK libraries (like `openai`, `anthropic`) to work with the LLM APIs, given that we're currently using `requests` directly.

1. **OpenRouter** - Uses the OpenAI-compatible API format (`/v1/chat/completions`). We're using raw `requests` which works fine. The official `openai` Python SDK could be used but isn't necessary - we're just doing simple POST requests.

2. **OpenAI Direct** - Same thing. The official `openai` Python SDK would work, but `requests` is sufficient. The SDK would add convenience features like retries, streaming, type hints, etc. But for our simple use case (one-shot requests, no streaming), `requests` is fine.

3. **Claude Direct** - We could use the official `anthropic` Python SDK, but again, `requests` is sufficient for simple POST/GET requests.

So the answer is: **No, we don't need any official SDK libraries.** The APIs are just HTTP endpoints. The `requests` library is all we need because:

- OpenAI / OpenRouter: simple POST to `/v1/chat/completions` with JSON body, get JSON response
- Claude: simple POST to `/v1/messages` with JSON body, get JSON response
- Batch operations are also just REST calls - upload file, create batch, poll status, download results

The official SDKs (`openai`, `anthropic`) add value for:
- Streaming responses
- WebSocket support
- Rate limiting / retry built-in
- Type definitions
- Async support

But none of those are needed for our pipeline. Our `_send_with_retry` in OpenRouter runner handles rate limits. We don't stream (we want complete responses for analysis). We handle errors ourselves with clear messages.

So the answer is clear: `requests` is sufficient and the right choice for this use case. Adding SDK dependencies would be unnecessary bloat.

Nope. `requests` is all you need. All three APIs are just HTTP REST endpoints:

| API | Method | Endpoint | What we send | What we get |
|-----|--------|----------|-------------|-------------|
| OpenRouter | POST | `/v1/chat/completions` | JSON body | JSON response |
| OpenAI Direct | POST | `/v1/chat/completions` | JSON body | JSON response |
| OpenAI Batch | POST + GET | `/v1/files`, `/v1/batches` | JSONL upload | Poll status |
| Claude Direct | POST | `/v1/messages` | JSON body | JSON response |
| Claude Batch | POST + GET | `/v1/messages/batches` | JSON body | Poll status |

They're all just JSON in, JSON out. **The official SDKs (`openai`, `anthropic`) would add convenience wrappers for streaming, async, and type hints - but we don't stream (we want the full response for analysis) and our `_send_with_retry` already handles rate limits. Adding them would be unnecessary dependencies with zero benefit for this pipeline.**

**Only two external packages needed:**
- `requests` - HTTP calls to all 3 APIs
- `openpyxl` - only if you use Excel as input format

## Check OpenRouter Credits
```bash
python check_openrouter_credits.py
```



