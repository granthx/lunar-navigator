"""Optional LLM access via the Anthropic Messages API (stdlib only).

If ANTHROPIC_API_KEY is not set, or any call fails, functions return None and
callers use their deterministic fallbacks. The sandbox this project was built in
had no API key, so the live path is covered only by a fake-transport unit test.
"""
from __future__ import annotations

import json
import os
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


def llm_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _default_transport(url: str, headers: dict, body: bytes) -> bytes:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=40) as resp:  # noqa: S310 - fixed https URL
        return resp.read()


def complete(system: str, user: str, max_tokens: int = 700, transport=None) -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    body = json.dumps({
        "model": os.environ.get("LUNAR_LLM_MODEL", "claude-sonnet-5-5"),
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode()
    headers = {"content-type": "application/json", "x-api-key": key,
               "anthropic-version": API_VERSION}
    try:
        raw = (transport or _default_transport)(API_URL, headers, body)
        data = json.loads(raw)
        parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        text = "".join(parts).strip()
        return text or None
    except Exception:  # noqa: BLE001 - any failure -> deterministic fallback
        return None
