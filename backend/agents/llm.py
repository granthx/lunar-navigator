"""Optional LLM access via two providers (stdlib + google-genai).

Provider priority (first available wins):
  1. Anthropic  — set ANTHROPIC_API_KEY.  Uses claude-sonnet-5-5 by default.
  2. Gemini     — set GEMINI_API_KEY (or GOOGLE_API_KEY).
                  Uses gemini-2.0-flash by default (override with LUNAR_LLM_MODEL).

If neither key is set, or every call fails, functions return None and callers
use their deterministic fallbacks.  The live paths are exercised by fake-transport
unit tests; the real network path requires a key.
"""
from __future__ import annotations

import json
import os
import urllib.request

# ------------------------------------------------------------------ Anthropic
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-5-5"

# ------------------------------------------------------------------ Gemini
GEMINI_DEFAULT_MODEL = "gemini-2.0-flash"


def _anthropic_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY", "")


def _gemini_key() -> str:
    return os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")


def llm_available() -> bool:
    """True when at least one LLM provider key is set."""
    return bool(_anthropic_key() or _gemini_key())


# ---------------------------------------------------------------- transports

def _default_transport(url: str, headers: dict, body: bytes) -> bytes:
    """Default HTTP transport (Anthropic-style: POST, raw bytes response)."""
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=40) as resp:  # noqa: S310 - fixed https URL
        return resp.read()


def _gemini_complete(system: str, user: str, max_tokens: int) -> str | None:
    """Call Gemini via google-genai SDK. Returns text or None on any failure."""
    try:
        import google.genai as genai  # optional dependency

        key = _gemini_key()
        client = genai.Client(api_key=key)
        model = os.environ.get("LUNAR_LLM_MODEL", GEMINI_DEFAULT_MODEL)
        # Prepend the system instruction as the first user turn (Gemini SDK style)
        full_prompt = f"{system}\n\n{user}"
        response = client.models.generate_content(
            model=model,
            contents=full_prompt,
            config=genai.types.GenerateContentConfig(max_output_tokens=max_tokens)
            if hasattr(genai, "types") else None,
        )
        text = response.text.strip() if response.text else None
        return text or None
    except Exception:  # noqa: BLE001 - any failure -> deterministic fallback
        return None


# ------------------------------------------------------------------ public API

def complete(system: str, user: str, max_tokens: int = 700, transport=None) -> str | None:
    """Try Anthropic first, then Gemini; return None if both fail or no key."""
    # --- Anthropic path --------------------------------------------------
    key = _anthropic_key()
    if key:
        body = json.dumps({
            "model": os.environ.get("LUNAR_LLM_MODEL", ANTHROPIC_DEFAULT_MODEL),
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }).encode()
        headers = {"content-type": "application/json", "x-api-key": key,
                   "anthropic-version": ANTHROPIC_VERSION}
        try:
            raw = (transport or _default_transport)(ANTHROPIC_URL, headers, body)
            data = json.loads(raw)
            parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
            text = "".join(parts).strip()
            if text:
                return text
        except Exception:  # noqa: BLE001 - fall through to Gemini
            pass

    # --- Gemini path (no custom transport; always uses SDK) ---------------
    if _gemini_key() and transport is None:
        return _gemini_complete(system, user, max_tokens)

    return None
