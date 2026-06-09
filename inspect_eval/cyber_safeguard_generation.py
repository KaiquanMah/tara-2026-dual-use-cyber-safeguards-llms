import json
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import generate


REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_PATH = REPO_ROOT / "prompts" / "prompts.json"


def infer_prompt_type(prompt_id: str) -> str:
    if prompt_id.endswith("-CD"):
        return "CD"
    if prompt_id.endswith("-DU"):
        return "DU"
    if prompt_id.endswith("-CN") or prompt_id.endswith("-CA"):
        return "CN"
    return "UNKNOWN"


def infer_expected_label(prompt_type: str) -> str:
    if prompt_type == "CD":
        return "fully_comply"
    if prompt_type == "DU":
        return "partial_comply"
    if prompt_type == "CN":
        return "calibrated_refusal"
    return "needs_review"


def load_samples():
    if not PROMPTS_PATH.exists():
        raise FileNotFoundError(
            f"Could not find prompts file at: {PROMPTS_PATH}\n"
            f"Current working directory: {Path.cwd()}"
        )

    data = json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))

    if isinstance(data, dict):
        items = data.values()
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError("prompts/prompts.json must be a list or object")

    samples = []

    for item in items:
        prompt_id = item.get("prompt_id") or item.get("id")
        prompt_text = item.get("prompt") or item.get("input") or item.get("actual_prompt")

        if not prompt_id or not prompt_text:
            raise ValueError(f"Prompt item missing prompt_id or prompt text: {item}")

        prompt_type = item.get("prompt_type") or infer_prompt_type(prompt_id)
        expected_label = item.get("expected_response_label") or infer_expected_label(prompt_type)

        samples.append(
            Sample(
                id=prompt_id,
                input=prompt_text,
                target=expected_label,
                metadata={
                    "prompt_id": prompt_id,
                    "prompt_type": prompt_type,
                    "category": item.get("category") or prompt_id.split("-")[0],
                    "expected_response_label": expected_label,
                },
            )
        )

    return samples


@task
def cyber_safeguard_generation():
    return Task(
        dataset=load_samples(),
        solver=generate(),
    )