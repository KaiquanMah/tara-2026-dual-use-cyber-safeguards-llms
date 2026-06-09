# Inspect AI Extension: Cyber Safeguard Calibration Benchmark

This folder contains a minimal Inspect AI implementation of our cyber safeguard calibration benchmark.

## Goal

The goal is reproducibility and standardisation. This is not a cyber range, live exploitation environment, or tool-enabled agentic benchmark.

## What Inspect handles

- Loading the existing prompt set
- Running model generation
- Preserving model run logs for auditability
- Exporting responses into our existing judging pipeline

## What remains in the existing pipeline

- Refusal calibration judging
- Attacker enablement judging
- CSV conversion
- Final result analysis

## Prompt set

- 60 total prompts
- 20 clearly defensive
- 20 dual-use
- 20 clearly offensive

## Evaluation question

Can a model support legitimate defenders while refusing clearly offensive cyber misuse?

## Run smoke test

```bash
inspect eval inspect_eval/cyber_safeguard_generation.py \
  --model openai/gpt-5.5 \
  --limit 2

## Run full generation

inspect eval inspect_eval/cyber_safeguard_generation.py \
  --model openai/gpt-5.5 \
  --limit 60

## Export responses
python inspect_eval/export_inspect_responses.py \
  --inspect-log <INSPECT_LOG_FILE> \
  --source-model inspect-openai-gpt-5.5 \
  --output outputs/inspect/gpt55/responses.json

