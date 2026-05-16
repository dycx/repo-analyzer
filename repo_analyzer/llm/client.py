"""OpenAI-compatible API client for LLM analysis.

Works with any OpenAI-compatible endpoint:
- LM Studio (local, no auth): --base-url http://127.0.0.1:1234/v1
- Remote server: --base-url https://your-server/v1 --api-key sk-xxx
"""

from __future__ import annotations

import json
import logging
import time

import httpx

logger = logging.getLogger("repo_analyzer.llm")


def _parse_sse_response(text: str) -> dict:
    """Parse Server-Sent Events stream into a single JSON object.

    Many OpenAI-compatible servers return SSE even for non-streaming requests::

        data: {"id":"...","choices":[{"message":{"content":"..."}}]}
        data: {"id":"...","choices":[{"delta":{"content":"more"}}]}
        data: [DONE]
    """
    chunks: list[str] = []
    last_json: dict | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        last_json = obj
        choices = obj.get("choices", [])
        if choices:
            delta = choices[0].get("delta", {})
            if "content" in delta and delta["content"]:
                chunks.append(delta["content"])

    if last_json is None:
        raise ValueError(f"No valid JSON found in SSE response: {text[:500]}")

    if chunks:
        last_json.setdefault("choices", [{}])
        last_json["choices"][0].setdefault("message", {})
        last_json["choices"][0]["message"]["content"] = "".join(chunks)

    return last_json


def _extract_content(data: dict) -> str:
    """Extract assistant message content from a chat completion response.

    Handles reasoning models (qwen3, etc.) that put output in
    'reasoning_content' instead of 'content'.
    """
    msg = data["choices"][0]["message"]
    content = msg.get("content", "")
    reasoning = msg.get("reasoning_content", "")

    if not content and reasoning:
        return reasoning
    return content or ""


def _is_sse(text: str) -> bool:
    return text.lstrip().startswith("data:")


class LLMClient:
    """Thin wrapper around OpenAI-compatible chat completions API.

    Features:
    - Persistent httpx.Client for connection reuse
    - SSE response auto-detection and parsing
    - Reasoning model support (qwen3 reasoning_content)
    - Exponential backoff retry
    - Context manager protocol
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:1234/v1",
        model: str = "qwen3.5-35b-a3b",
        api_key: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 16384,
        timeout: float = 300.0,
        max_retries: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = httpx.Client(
            timeout=self.timeout,
            headers=self._headers(),
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _post_chat(self, payload: dict) -> dict:
        """POST to /chat/completions and return parsed JSON."""
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = self._client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                )
                resp.raise_for_status()
                text = resp.text
                if _is_sse(text):
                    return _parse_sse_response(text)
                return resp.json()
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_err = e
                if attempt < self.max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        "Retry %d/%d: %s, waiting %ds",
                        attempt + 1, self.max_retries, type(e).__name__, wait,
                    )
                    time.sleep(wait)
            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500 and attempt < self.max_retries - 1:
                    last_err = e
                    wait = 2 ** attempt
                    logger.warning(
                        "Retry %d/%d: HTTP %d, waiting %ds",
                        attempt + 1, self.max_retries, e.response.status_code, wait,
                    )
                    time.sleep(wait)
                else:
                    raise

        if last_err is None:
            raise RuntimeError("All retry attempts exhausted before any request was made")
        raise last_err

    def chat(
        self,
        system: str,
        user: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Send a chat completion request and return the assistant message."""
        data = self._post_chat({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
        })
        return _extract_content(data)

    def chat_messages(
        self,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Send raw messages list (for multi-turn)."""
        data = self._post_chat({
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
        })
        return _extract_content(data)

    def health_check(self) -> bool:
        """Check if the LLM endpoint is reachable."""
        try:
            resp = self._client.get(f"{self.base_url}/models")
            return resp.status_code == 200
        except Exception:
            return False

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "LLMClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
