import argparse
import json
from pathlib import Path

from inspect_ai.log import read_eval_log_samples


def content_to_text(content):
    """
    Convert Inspect message content to text.
    Handles simple strings and structured content blocks.
    """
    if content is None:
        return ""

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("text"):
                    parts.append(item["text"])
                elif item.get("content"):
                    parts.append(str(item["content"]))
        return "\n".join(parts)

    return str(content)


def extract_input(sample):
    """
    Try common Inspect EvalSample shapes.
    """
    if getattr(sample, "input", None):
        return content_to_text(sample.input)

    messages = getattr(sample, "messages", None)
    if messages:
        for msg in messages:
            role = getattr(msg, "role", None)
            content = getattr(msg, "content", None)
            if role == "user":
                return content_to_text(content)

    return ""


def extract_completion(sample):
    """
    Try common Inspect EvalSample output/message shapes.
    """
    output = getattr(sample, "output", None)

    if output:
        completion = getattr(output, "completion", None)
        if completion:
            return content_to_text(completion)

        message = getattr(output, "message", None)
        if message:
            return content_to_text(getattr(message, "content", None))

        choices = getattr(output, "choices", None)
        if choices:
            first = choices[0]
            message = getattr(first, "message", None)
            if message:
                return content_to_text(getattr(message, "content", None))

    messages = getattr(sample, "messages", None)
    if messages:
        for msg in reversed(messages):
            role = getattr(msg, "role", None)
            content = getattr(msg, "content", None)
            if role == "assistant":
                return content_to_text(content)

    return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inspect-log", required=True)
    parser.add_argument("--source-model", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    log_path = Path(args.inspect_log)

    if not log_path.exists():
        raise FileNotFoundError(f"Inspect log not found: {log_path}")

    exported = {}

    samples = list(
        read_eval_log_samples(
            log_path,
            resolve_attachments=True,
            format="auto",
        )
    )

    for sample in samples:
        metadata = getattr(sample, "metadata", {}) or {}

        sample_id = (
            getattr(sample, "id", None)
            or metadata.get("prompt_id")
            or getattr(sample, "uuid", None)
        )

        if not sample_id:
            print("Skipping sample with no id")
            continue

        exported[str(sample_id)] = {
            "prompt_id": str(sample_id),
            "source_model": args.source_model,
            "actual_prompt": extract_input(sample),
            "actual_response": extract_completion(sample),
            "prompt_type": metadata.get("prompt_type"),
            "category": metadata.get("category"),
            "expected_response_label": metadata.get("expected_response_label"),
        }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(
        json.dumps(exported, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Exported {len(exported)} responses to {output_path}")

    empty_responses = [
        prompt_id
        for prompt_id, row in exported.items()
        if not row.get("actual_response")
    ]

    if empty_responses:
        print("Warning: some samples had empty actual_response:")
        for prompt_id in empty_responses[:10]:
            print(f"- {prompt_id}")
        if len(empty_responses) > 10:
            print(f"... and {len(empty_responses) - 10} more")


if __name__ == "__main__":
    main()