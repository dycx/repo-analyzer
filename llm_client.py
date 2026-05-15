"""OpenAI-compatible API client for LLM analysis.

Works with any OpenAI-compatible endpoint:
- LM Studio (local, no auth): --base-url http://127.0.0.1:1234/v1
- Remote Qwen: --base-url https://your-server/v1 --api-key sk-xxx
- OpenAI: --base-url https://api.openai.com/v1 --api-key sk-xxx
"""

import json as _json

import httpx


def _parse_sse_response(text: str) -> dict:
    """Parse Server-Sent Events (SSE) stream into a single JSON object.

    Many OpenAI-compatible servers return SSE even for non-streaming requests::

        data: {"id":"...","choices":[{"message":{"content":"..."}}]}
        data: {"id":"...","choices":[{"delta":{"content":"more"}}]}
        data: [DONE]

    This extracts the last ``data:`` line that is valid JSON and not ``[DONE]``,
    then merges all ``delta.content`` chunks if the response was streamed.
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
            obj = _json.loads(payload)
        except _json.JSONDecodeError:
            continue
        last_json = obj
        # Collect streamed delta content
        choices = obj.get("choices", [])
        if choices:
            delta = choices[0].get("delta", {})
            if "content" in delta and delta["content"]:
                chunks.append(delta["content"])

    if last_json is None:
        raise ValueError(f"No valid JSON found in SSE response: {text[:500]}")

    # If we collected streamed chunks, assemble them
    if chunks:
        last_json.setdefault("choices", [{}])
        last_json["choices"][0].setdefault("message", {})
        last_json["choices"][0]["message"]["content"] = "".join(chunks)

    return last_json


def _extract_content(data: dict) -> str:
    """Extract assistant message content from a chat completion response."""
    return data["choices"][0]["message"]["content"]


def _is_sse(text: str) -> bool:
    """Detect whether a response body is SSE-formatted."""
    return text.lstrip().startswith("data:")


class LLMClient:
    """Thin wrapper around OpenAI-compatible chat completions API."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:1234/v1",
        model: str = "qwen3.5-35b-a3b",
        api_key: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 8192,
        timeout: float = 300.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        """Build HTTP headers, including auth when api_key is set."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _post_chat(self, payload: dict) -> dict:
        """POST to /chat/completions and return parsed JSON.

        Handles both plain JSON and SSE-formatted responses transparently.
        """
        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        text = resp.text
        if _is_sse(text):
            return _parse_sse_response(text)
        return resp.json()

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
            "temperature": temperature or self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
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
            "temperature": temperature or self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
        })
        return _extract_content(data)

    def health_check(self) -> bool:
        """Check if the LLM endpoint is reachable."""
        try:
            resp = httpx.get(
                f"{self.base_url}/models",
                headers=self._headers(),
                timeout=5,
            )
            return resp.status_code == 200
        except Exception:
            return False
