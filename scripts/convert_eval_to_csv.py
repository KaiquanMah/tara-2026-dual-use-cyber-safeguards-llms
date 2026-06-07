import json
import csv
import sys
from pathlib import Path

def flatten_evidence(evidence):
    if isinstance(evidence, list):
        return "; ".join(str(e) for e in evidence)
    return evidence if evidence is not None else ""

def transform_json_to_csv(input_json_path, output_csv_path):
    with open(input_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Determine the list of records
    records = None
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        # Check for common list keys
        for key in ["data", "results", "evaluations", "items"]:
            if key in data and isinstance(data[key], list):
                records = data[key]
                break
        else:
            # If all values are dicts, treat the dict itself as records keyed by prompt_id
            if all(isinstance(v, dict) for v in data.values()):
                print(f"INFO: Interpreting JSON root as dict of {len(data)} records, using keys as prompt_id.")
                records = [{"prompt_id": k, **v} for k, v in data.items()]
            else:
                raise ValueError("Unable to parse JSON structure. Root dict has non-dict values or no list found.")
    else:
        raise TypeError(f"Unexpected JSON root type: {type(data)}")

    if not records:
        print("Warning: No records found.")
        return

    # Print first record keys for debugging (optional)
    if records:
        sample = records[0]
        print(f"Sample record keys: {list(sample.keys())}")

    csv_rows = []
    for rec in records:
        # prompt_id already added if from dict; otherwise try rec fields
        prompt_id = rec.get("prompt_id", rec.get("id", ""))

        # Scores might be nested
        scores = rec.get("metrics", rec.get("scores", rec))

        row = {
            "prompt_id": prompt_id,
            "prompt_type": rec["prompt_id"][-2:] if rec.get("prompt_id") else "",
            "model": rec.get("source_model", rec.get("model", rec.get("model_name", ""))),
            "grade_expected": rec.get("expected_response_label", rec.get("expected_label", rec.get("gold_label", ""))),
            "evaluated_response_label": rec.get("evaluated_response_label", rec.get("response_label", rec.get("judgment", rec.get("judged_label", "")))),
            "refusal_classification": rec.get("refusal_classification", rec.get("refusal", rec.get("refused", False))),
            "actual_prompt": rec.get("actual_prompt", rec.get("prompt", rec.get("prompt_text", ""))),
            "actual_response": rec.get("actual_response", rec.get("response", rec.get("response_text", ""))),
            "defender_utility_score": scores.get("defender_utility_score", scores.get("defender_utility", None)),
            "technical_quality_score": scores.get("technical_quality_score", scores.get("technical_quality", None)),
            "safety_score": scores.get("safety_score", scores.get("safety", None)),
            "harmfulness_score": scores.get("harmfulness_score", scores.get("harmfulness", scores.get("harmful", None))),
            "confidence": rec.get("confidence", rec.get("certainty", None)),
            "short_rationale": rec.get("short_rationale", rec.get("rationale", rec.get("explanation", ""))),
            "evidence_quotes": flatten_evidence(rec.get("evidence_quotes", rec.get("evidence", rec.get("quotes", []))))
        }
        csv_rows.append(row)

    fieldnames = [
        "prompt_id", "prompt_type", "model", "grade_expected", "evaluated_response_label",
        "refusal_classification", "actual_prompt", "actual_response", "defender_utility_score",
        "technical_quality_score", "safety_score", "harmfulness_score", "confidence",
        "short_rationale", "evidence_quotes"
    ]

    with open(output_csv_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)

    print(f"Successfully converted {len(csv_rows)} records to {output_csv_path}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python convert_eval_to_csv.py <path_to_json_file>")
        sys.exit(1)

    input_file = sys.argv[1]
    input_path = Path(input_file)

    if not input_path.exists():
        print(f"Error: File not found: {input_file}")
        sys.exit(1)

    output_path = input_path.with_suffix(".csv")
    transform_json_to_csv(input_path, output_path)