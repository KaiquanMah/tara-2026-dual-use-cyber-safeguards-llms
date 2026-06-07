import os
import json
import time
import requests
from .base import BaseRunner
from ..models import Prompt, Response

'''
Sends prompts to model via the direct OpenAI API.

Two modes:
  run_one(prompt)        POST /v1/chat/completions - single request, synchronous.

  run_batch(prompts)     1. Upload JSONL to /v1/files
                         2. Create batch job at /v1/batches (completion_window: 24h)
                         3. Poll every 10s until status is completed/failed/cancelled
                         4. Download results from /v1/files/{output_file_id}/content

Response parsing captures reasoning_content or reasoning from the message
object (for OpenAI reasoning models) and stores it in response.metadata.
'''

class OpenAIDirectRunner(BaseRunner):
    API_BASE = "https://api.openai.com/v1"

    def _headers(self):
        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing env var: {self.config.api_key_env}")
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _build_message(self, prompt: Prompt) -> dict:
        return {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt.text}],
            **self.config.default_params,
        }

    def _extract_msg_and_reasoning(self, choice: dict) -> tuple[str, dict]:
        msg = choice.get("message", {})
        text = msg.get("content") or ""
        meta = {}
        reasoning = msg.get("reasoning_content") or msg.get("reasoning")
        if reasoning:
            meta["reasoning"] = reasoning
        return text, meta

    def run_one(self, prompt: Prompt) -> Response:
        resp = requests.post(
            f"{self.API_BASE}/chat/completions",
            headers=self._headers(),
            json=self._build_message(prompt),
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        text, reason_meta = self._extract_msg_and_reasoning(choice)
        meta = {"provider": "openai", "access": "direct", **reason_meta}
        return Response(
            prompt_id=prompt.id,
            model=data["model"],
            text=text,
            finish_reason=choice.get("finish_reason", ""),
            usage=data.get("usage", {}),
            metadata=meta,
        )

    def run_batch(self, prompts: list[Prompt]) -> list[Response]:
        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing env var: {self.config.api_key_env}")

        jsonl_lines = []
        for p in prompts:
            body = self._build_message(p)
            jsonl_lines.append(json.dumps({
                "custom_id": p.id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": body,
            }))

        upload_resp = requests.post(
            "https://api.openai.com/v1/files",
            headers=self._headers(),
            files={"file": ("batch.jsonl", "\n".join(jsonl_lines), "application/jsonl")},
            data={"purpose": "batch"},
        )
        upload_resp.raise_for_status()
        file_id = upload_resp.json()["id"]

        batch_resp = requests.post(
            f"{self.API_BASE}/batches",
            headers=self._headers(),
            json={
                "input_file_id": file_id,
                "endpoint": "/v1/chat/completions",
                "completion_window": "24h",
            },
        )
        batch_resp.raise_for_status()
        batch_id = batch_resp.json()["id"]

        while True:
            status_resp = requests.get(
                f"{self.API_BASE}/batches/{batch_id}",
                headers=self._headers(),
            )
            status_resp.raise_for_status()
            batch = status_resp.json()
            if batch["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(10)

        if batch["status"] != "completed":
            raise RuntimeError(f"Batch {batch_id} finished with status: {batch['status']}")

        output_file_id = batch.get("output_file_id")
        if not output_file_id:
            raise RuntimeError("No output file in completed batch")

        result_resp = requests.get(
            f"{self.API_BASE}/files/{output_file_id}/content",
            headers=self._headers(),
        )
        result_resp.raise_for_status()

        results = []
        for line in result_resp.text.strip().split("\n"):
            if not line:
                continue
            result = json.loads(line)
            body = result.get("response", {}).get("body", {})
            choice = body.get("choices", [{}])[0]
            text, reason_meta = self._extract_msg_and_reasoning(choice)
            meta = {"provider": "openai", "access": "direct", "batch_id": batch_id, **reason_meta}
            results.append(Response(
                prompt_id=result["custom_id"],
                model=body.get("model", self.config.model),
                text=text,
                finish_reason=choice.get("finish_reason", ""),
                usage=body.get("usage", {}),
                metadata=meta,
            ))
        return results
