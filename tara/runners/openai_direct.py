import os
import json
import time
import requests
from .base import BaseRunner
from ..models import Prompt, Response

"""
Sends prompts to model via the direct OpenAI API.

Two modes:
  run_one(prompt)     POST /v1/responses - single request, synchronous.
  run_batch(prompts)  Uses OpenAI Batch API with endpoint /v1/responses.

This version is intended for GPT-5.x / TAC-style models that use the Responses API.
"""


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

    def _auth_headers(self):
        """Headers without Content-Type, used for multipart file upload."""
        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing env var: {self.config.api_key_env}")
        return {
            "Authorization": f"Bearer {api_key}",
        }

    def _build_body(self, prompt: Prompt) -> dict:
        """
        Build Responses API request body.

        Converts older Chat Completions params where possible:
          max_tokens -> max_output_tokens
        """
        params = dict(self.config.default_params or {})

        if "max_tokens" in params:
            params["max_output_tokens"] = params.pop("max_tokens")

        # Avoid sending null values
        params = {k: v for k, v in params.items() if v is not None}

        return {
            "model": self.config.model,
            "input": prompt.text,
            **params,
        }

    def _extract_response_text(self, data: dict) -> str:
        """
        Extract text from Responses API response body.
        """
        if data.get("output_text"):
            return data["output_text"]

        chunks = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in ("output_text", "text") and content.get("text"):
                    chunks.append(content["text"])

        return "\n".join(chunks)

    def _extract_reasoning_metadata(self, data: dict) -> dict:
        """
        Best-effort extraction of reasoning metadata if present.
        Does not expose private chain-of-thought; only stores fields returned by API.
        """
        meta = {}
        reasoning_items = []

        for item in data.get("output", []):
            if item.get("type") == "reasoning":
                reasoning_items.append(item)

        if reasoning_items:
            meta["reasoning_items"] = reasoning_items

        return meta

    def _raise_with_body(self, resp: requests.Response):
        if not resp.ok:
            print("OpenAI error status:", resp.status_code)
            print("OpenAI error body:", resp.text)
            resp.raise_for_status()

    def run_one(self, prompt: Prompt) -> Response:
        resp = requests.post(
            f"{self.API_BASE}/responses",
            headers=self._headers(),
            json=self._build_body(prompt),
        )
        self._raise_with_body(resp)

        data = resp.json()
        text = self._extract_response_text(data)
        reason_meta = self._extract_reasoning_metadata(data)

        meta = {
            "provider": "openai",
            "access": "direct",
            "response_id": data.get("id"),
            "status": data.get("status"),
            **reason_meta,
        }

        return Response(
            prompt_id=prompt.id,
            model=data.get("model", self.config.model),
            text=text,
            finish_reason=data.get("status", ""),
            usage=data.get("usage", {}),
            metadata=meta,
        )

    def run_batch(self, prompts: list[Prompt]) -> list[Response]:
        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing env var: {self.config.api_key_env}")

        jsonl_lines = []
        for p in prompts:
            body = self._build_body(p)
            jsonl_lines.append(json.dumps({
                "custom_id": p.id,
                "method": "POST",
                "url": "/v1/responses",
                "body": body,
            }))

        upload_resp = requests.post(
            f"{self.API_BASE}/files",
            headers=self._auth_headers(),
            files={
                "file": (
                    "batch.jsonl",
                    "\n".join(jsonl_lines).encode("utf-8"),
                    "application/jsonl",
                )
            },
            data={"purpose": "batch"},
        )
        self._raise_with_body(upload_resp)
        file_id = upload_resp.json()["id"]

        batch_resp = requests.post(
            f"{self.API_BASE}/batches",
            headers=self._headers(),
            json={
                "input_file_id": file_id,
                "endpoint": "/v1/responses",
                "completion_window": "24h",
            },
        )
        self._raise_with_body(batch_resp)
        batch_id = batch_resp.json()["id"]

        print(f"Created OpenAI batch: {batch_id}")

        while True:
            status_resp = requests.get(
                f"{self.API_BASE}/batches/{batch_id}",
                headers=self._headers(),
            )
            self._raise_with_body(status_resp)
            batch = status_resp.json()

            print(f"Batch {batch_id} status: {batch['status']}")

            if batch["status"] in ("completed", "failed", "cancelled", "expired"):
                break

            time.sleep(10)

        if batch["status"] != "completed":
            raise RuntimeError(f"Batch {batch_id} finished with status: {batch['status']}")

        output_file_id = batch.get("output_file_id")
        if not output_file_id:
            raise RuntimeError("No output file in completed batch")

        result_resp = requests.get(
            f"{self.API_BASE}/files/{output_file_id}/content",
            headers=self._auth_headers(),
        )
        self._raise_with_body(result_resp)

        results = []

        for line in result_resp.text.strip().split("\n"):
            if not line:
                continue

            result = json.loads(line)
            custom_id = result.get("custom_id")

            response = result.get("response", {})
            body = response.get("body", {})

            if result.get("error"):
                results.append(Response(
                    prompt_id=custom_id,
                    model=self.config.model,
                    text="",
                    finish_reason="error",
                    usage={},
                    metadata={
                        "provider": "openai",
                        "access": "direct",
                        "batch_id": batch_id,
                        "error": result.get("error"),
                    },
                ))
                continue

            text = self._extract_response_text(body)
            reason_meta = self._extract_reasoning_metadata(body)

            meta = {
                "provider": "openai",
                "access": "direct",
                "batch_id": batch_id,
                "response_id": body.get("id"),
                "status": body.get("status"),
                **reason_meta,
            }

            results.append(Response(
                prompt_id=custom_id,
                model=body.get("model", self.config.model),
                text=text,
                finish_reason=body.get("status", ""),
                usage=body.get("usage", {}),
                metadata=meta,
            ))

        return results
