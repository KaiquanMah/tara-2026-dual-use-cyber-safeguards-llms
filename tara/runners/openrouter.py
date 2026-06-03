import os
import json
import random
import time
import requests
from .base import BaseRunner
from ..models import Prompt, Response

'''
Sends prompts to model via the OpenRouter API (POST /chat/completions).

Key behaviors:
  1. Reasoning cascade - tries each level in config.reasoning (e.g. ["xhigh", "high"]).
     If the model rejects a level with a reasoning-related error, it moves to the next.
     Non-reasoning errors (auth, rate limit) raise immediately - no retry.

  2. Response parsing - captures the model's final answer (msg.content) plus
     any reasoning trace (msg.reasoning) stored in response.metadata.

  3. Rate limiting - 1s delay between successful requests to stay under
     OpenRouter's free-tier limits.

  4. Error parsing - extracts the human-readable error message from OpenRouter's
     JSON error body, rather than showing a raw HTTP status code.



**`run_one(prompt)`** - the main entry point. Does:

1. **Reasoning loop** - iterates through each level in `config.reasoning` (e.g. `["xhigh", "high"]`). 
   For each level, calls `_build_payload` which constructs the HTTP body with `reasoning: {level: "xhigh"}` if a level is set.
2. **Sends POST** to `https://openrouter.ai/api/v1/chat/completions`
3. **Success path** - if `resp.ok` and no error in body, calls `_build_response` to construct a `Response` object, then sleeps 1s (rate limit), returns it
4. **Error path** - if the response is an error, calls `_parse_error` to extract the human-readable message from OpenRouter's JSON body, then checks `_is_reasoning_error`:
   - Yes → `continue` to try the next reasoning level
   - No → raises immediately with the error message
5. **All levels exhausted** - raises with the last error showing all levels tried

**Helper methods:**

| Method | What it does |
|--------|-------------|
| `_build_payload(prompt, level)` | Assembles the POST body - model, messages, default_params, plus optional `reasoning: {level}` |
| `_build_response(prompt, data)` | Parses the API response into a `Response` object - extracts final answer from `choices[0].message.content`, reasoning trace from `message.reasoning` |
| `_parse_error(resp)` | Tries to extract the `error.message` string from OpenRouter's JSON error body; falls back to raw text |
| `_is_reasoning_error(body)` | Heuristic check - looks for "reasoning" combined with "not support", "unsupported", "invalid", or "level" in the error message |



The 1s delay is **preventive** - it spaces successful requests 1s apart to avoid hitting rate limits in the first place.
But I also added actual **rate limit retry** logic now (`_send_with_retry` on line 42). Here's the full picture of what happens:

1. **Preventive**: 1s sleep after every successful request (line 77) keeps the sustained rate under OpenRouter's free-tier limit

2. **Detect & retry**: `_send_with_retry` wraps each POST in a loop of up to 5 attempts. If OpenRouter returns **429 (Too Many Requests)**, it:
   - Reads `Retry-After` from the response body or headers
   - Falls back to **5s** if no retry hint is given
   - Sleeps and retries

3. **Non-429 errors** (401 auth, 400 bad request, 500 server error, reasoning rejection) → returned immediately, no retry

So the flow for a rate-limited request looks like:
```
send POST → 429 → sleep 5s → retry → 429 → sleep 8s → retry → 200 → done
```
'''

class OpenRouterRunner(BaseRunner):
    API_BASE = "https://openrouter.ai/api/v1"
    RATE_LIMIT_DELAY = 1.0
    MAX_RETRIES = 6

    def _get_rate_limit_delay(self) -> float:
        if self.config.rate_limit_delay is not None:
            return self.config.rate_limit_delay
        return self.RATE_LIMIT_DELAY

    def run_one(self, prompt: Prompt) -> Response:
        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing env var: {self.config.api_key_env}")

        levels = self.config.reasoning or [None]
        last_error = None
        prompt_start = time.time()

        for level in levels:
            payload = self._build_payload(prompt, level)
            resp = self._send_with_retry(payload, api_key)

            if resp.ok:
                try:
                    data = resp.json()
                except requests.JSONDecodeError as e:
                    preview = resp.text[:500].replace("\n", " ").strip()
                    raise RuntimeError(
                        f"OpenRouter returned status {resp.status_code} "
                        f"with non-JSON body ({resp.headers.get('content-type', '?')}): "
                        f"{preview}"
                    )
                if "error" not in data:
                    response = self._build_response(prompt, data)
                    total = time.time() - prompt_start
                    print(f" ({total:.0f}s)", end="", flush=True)
                    time.sleep(self._get_rate_limit_delay())
                    return response

            error_body = self._parse_error(resp)
            if level is not None and self._is_reasoning_error(error_body):
                last_error = error_body
                continue

            raise RuntimeError(
                f"OpenRouter API error ({resp.status_code}): {error_body}"
            )

        raise RuntimeError(
            f"All reasoning levels {levels} exhausted. "
            f"Last error: {last_error}"
        )

    def _send_with_retry(self, payload: dict, api_key: str) -> requests.Response:
        for attempt in range(self.MAX_RETRIES):
            resp = requests.post(
                f"{self.API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if resp.status_code != 429:
                return resp
            if attempt < self.MAX_RETRIES - 1:
                retry_after = self._parse_retry_after(resp, attempt)
                time.sleep(retry_after)
        error_body = self._parse_error(resp)
        raise RuntimeError(
            f"OpenRouter API error ({resp.status_code}) after {self.MAX_RETRIES} "
            f"attempts: {error_body}"
        )

    def _parse_retry_after(self, resp: requests.Response, attempt: int) -> float:
        try:
            body = resp.json()
            err = body.get("error", {})
            retry = err.get("retry_after") or err.get("Retry-After")
            if retry:
                return float(retry)
        except Exception:
            pass
        retry_header = resp.headers.get("Retry-After")
        if retry_header:
            return float(retry_header)
        return min(5 * (2 ** attempt) + random.uniform(0, 1), 120)

    def _build_payload(self, prompt: Prompt, level: str | None) -> dict:
        payload = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt.text}],
            **self.config.default_params,
        }
        if level is not None:
            payload["reasoning"] = {"level": level}
        return payload

    def _build_response(self, prompt: Prompt, data: dict) -> Response:
        choice = data["choices"][0]
        msg = choice["message"]
        metadata = {
            "provider": "openrouter",
            "model_slug": data.get("model", ""),
        }
        reasoning = msg.get("reasoning")
        if reasoning:
            metadata["reasoning"] = reasoning

        content = msg.get("content")
        refusal = msg.get("refusal")
        if content is None:
            metadata["refused"] = True
            metadata["raw_finish_reason"] = choice.get("finish_reason", "")
            text = refusal or ""
        else:
            text = content

        return Response(
            prompt_id=prompt.id,
            model=data.get("model", self.config.model),
            text=text,
            finish_reason=choice.get("finish_reason", ""),
            usage=data.get("usage", {}),
            metadata=metadata,
        )

    def _parse_error(self, resp: requests.Response) -> str:
        try:
            body = resp.json()
            err = body.get("error", {})
            msg = err.get("message", "")
            raw = err.get("metadata", {}).get("raw", "")
            if raw:
                return f"{msg}: {raw}"
            return msg or json.dumps(body)
        except Exception:
            return resp.text

    def _is_reasoning_error(self, error_body: str) -> bool:
        lowered = error_body.lower()
        return "reasoning" in lowered and (
            "not support" in lowered
            or "unsupported" in lowered
            or "invalid" in lowered
            or "level" in lowered
        )
