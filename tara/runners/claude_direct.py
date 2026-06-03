import os
import json
import time
import requests
from .base import BaseRunner
from ..models import Prompt, Response

'''
Sends prompts to model via the direct Anthropic API (POST /v1/messages).

Two modes:
  run_one(prompt)        POST /v1/messages - single request, synchronous.

  run_batch(prompts)     1. POST /v1/messages/batches with all prompts as JSONL
                         2. Poll every 5s until processing_status == "ended"
                         3. Read results from batch response

Content handling (Anthropic content blocks):
  Anthropic's extended thinking returns content as a list of typed blocks:
    {"type": "thinking", "thinking": "..."}    - reasoning trace
    {"type": "text", "text": "..."}           - final answer
  _extract_text_and_thinking() iterates all blocks, concatenates text and
  thinking separately. Thinking is stored in response.metadata.thinking.
'''

class ClaudeDirectRunner(BaseRunner):
    API_BASE = "https://api.anthropic.com/v1"

    def _headers(self):
        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing env var: {self.config.api_key_env}")
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    def _build_message(self, prompt: Prompt) -> dict:
        params = dict(self.config.default_params)
        params.setdefault("max_tokens", 4096)
        return {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt.text}],
            **params,
        }

    def _extract_text_and_thinking(self, content_blocks: list[dict]) -> tuple[str, str]:
        text_parts = []
        thinking_parts = []
        for block in content_blocks:
            t = block.get("type", "")
            if t == "text":
                text_parts.append(block.get("text", ""))
            elif t == "thinking":
                thinking_parts.append(block.get("thinking", ""))
        return "\n".join(text_parts), "\n".join(thinking_parts)

    def _build_metadata(self, data: dict, batch_id: str | None = None) -> dict:
        meta = {"provider": "anthropic", "access": "direct"}
        if batch_id:
            meta["batch_id"] = batch_id
        content_blocks = data.get("content", [])
        _, thinking = self._extract_text_and_thinking(content_blocks)
        if thinking:
            meta["thinking"] = thinking
        return meta

    def run_one(self, prompt: Prompt) -> Response:
        resp = requests.post(
            f"{self.API_BASE}/messages",
            headers=self._headers(),
            json=self._build_message(prompt),
        )
        resp.raise_for_status()
        data = resp.json()
        text, _ = self._extract_text_and_thinking(data.get("content", []))
        return Response(
            prompt_id=prompt.id,
            model=data["model"],
            text=text,
            finish_reason=data.get("stop_reason", ""),
            usage=data.get("usage", {}),
            metadata=self._build_metadata(data),
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
                "params": body,
            }))

        upload_resp = requests.post(
            f"{self.API_BASE}/messages/batches",
            headers=self._headers(),
            json={"requests": [json.loads(line) for line in jsonl_lines]},
        )
        upload_resp.raise_for_status()
        batch_id = upload_resp.json()["id"]

        while True:
            status_resp = requests.get(
                f"{self.API_BASE}/messages/batches/{batch_id}",
                headers=self._headers(),
            )
            status_resp.raise_for_status()
            batch = status_resp.json()
            if batch["processing_status"] == "ended":
                break
            time.sleep(5)

        results = []
        for result in batch.get("results", []):
            data = result.get("response", {})
            text, _ = self._extract_text_and_thinking(data.get("content", []))
            results.append(Response(
                prompt_id=result["custom_id"],
                model=data.get("model", self.config.model),
                text=text,
                finish_reason=data.get("stop_reason", ""),
                usage=data.get("usage", {}),
                metadata=self._build_metadata(data, batch_id),
            ))
        return results
