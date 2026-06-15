"""
LLM client — Databricks Foundation Models via OpenAI-compatible endpoint.

Usage:
    client = get_client()
    text = chat(client, [{"role": "user", "content": "..."}])
"""
from __future__ import annotations

import os
from typing import Any

from .databricks import _access_token, _server_hostname

# Model served on the workspace — override via env
DEFAULT_MODEL = os.getenv(
    "DATABRICKS_LLM_MODEL",
    "databricks-meta-llama-3-3-70b-instruct",
)


def get_client():
    """Return an OpenAI client pointed at the Databricks serving endpoint."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "openai package required: pip install openai"
        ) from exc

    return OpenAI(
        api_key=_access_token(),
        base_url=f"https://{_server_hostname()}/serving-endpoints",
    )


def chat(
    client,
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 2048,
) -> str:
    """Single chat completion, returns the assistant text."""
    response = client.chat.completions.create(
        model=model or DEFAULT_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


def chat_json(
    client,
    messages: list[dict[str, str]],
    model: str | None = None,
    **kwargs: Any,
) -> Any:
    """Chat completion that parses the response as JSON.
    The prompt must instruct the model to return valid JSON.
    """
    import json
    import re

    text = chat(client, messages, model=model, **kwargs)
    # Strip markdown code fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text.strip())
    return json.loads(text)
