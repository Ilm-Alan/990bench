"""Tool-using model loop with full trajectory logging.

Models are named `provider/model`. Providers are called through their OpenAI-compatible
chat-completions endpoint, so there is one message format.
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Callable

import httpx

PROVIDERS = {
    "ollama": ("https://ollama.com/v1", "OLLAMA_API_KEY"),
}
MAX_STEPS = 250


def client_for(spec: str) -> tuple[httpx.Client, str]:
    provider, model = spec.split("/", 1)
    base, env = PROVIDERS[provider]
    client = httpx.Client(base_url=base, headers={"Authorization": f"Bearer {os.environ[env]}"}, timeout=300)
    return client, model


def _args(raw: object) -> dict[str, object]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {"_invalid_json": str(raw)}
    return parsed if isinstance(parsed, dict) else {"_invalid_json": str(raw)}


ToolResult = str | tuple[str, list[bytes]]


def _post(client: httpx.Client, body: dict[str, object]) -> httpx.Response:
    """POST with retries for transient server errors; 429 quota errors are not retried."""
    for attempt in range(4):
        resp = client.post("/chat/completions", json=body)
        if resp.status_code < 500 or attempt == 3:
            return resp
        time.sleep(15 * (attempt + 1))
    return resp


EVICTED = "[This page image was removed from the conversation to save space. View the page again if you need it.]"


def _evict_images(messages: list[dict[str, object]], keep: int) -> None:
    """Replace all but the newest `keep` images with a text note."""
    seen = 0
    for msg in reversed(messages):
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for i in range(len(content) - 1, -1, -1):
            if content[i].get("type") == "image_url":
                seen += 1
                if seen > keep:
                    content[i] = {"type": "text", "text": EVICTED}


def run_loop(
    client: httpx.Client,
    model: str,
    system: str,
    prompt: str,
    specs: list[dict[str, object]],
    call: Callable[[str, dict[str, object]], ToolResult],
    max_steps: int = MAX_STEPS,
    deadline_s: float = 3600,
    keep_images: int | None = None,
    max_prompt_tokens: int | None = None,
) -> dict[str, object]:
    """Drive one model through a tool loop until it calls `submit`, or a limit is hit.

    A tool may return (text, [png bytes]); the images follow the tool results as one user message.
    With `keep_images`, only the most recent that many images stay in the conversation; older ones
    are replaced by a note, so the agent has to keep its own notes on long assignments.
    `max_prompt_tokens` stops a run whose cumulative prompt tokens pass the budget (a failure).
    `infra_error` marks runs stopped by the provider (quota, server, network), which are excluded
    from scores rather than counted as failures.
    """
    messages: list[dict[str, object]] = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    steps: list[dict[str, object]] = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    final: dict[str, object] | None = None
    error, infra = None, False
    start = time.monotonic()
    for _ in range(max_steps):
        if time.monotonic() - start > deadline_s:
            error = f"wall-clock limit {deadline_s}s"
            break
        if max_prompt_tokens is not None and usage["prompt_tokens"] > max_prompt_tokens:
            error = f"prompt-token budget {max_prompt_tokens:,}"
            break
        try:
            resp = _post(client, {"model": model, "messages": messages, "tools": specs})
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            error = f"http {exc.response.status_code}: {exc.response.text[:500]}"
            infra = exc.response.status_code == 429 or exc.response.status_code >= 500
            break
        except httpx.HTTPError as exc:
            error, infra = f"network: {exc!r}", True
            break
        body = resp.json()
        for k in usage:
            usage[k] += (body.get("usage") or {}).get(k, 0) or 0
        msg = body["choices"][0]["message"]
        messages.append({k: v for k, v in msg.items() if v is not None})
        calls = msg.get("tool_calls") or []
        if not calls:
            steps.append({"type": "text", "content": msg.get("content") or ""})
            messages.append({"role": "user", "content": "Continue using the tools. Call the submit tool when you are done."})
            continue
        images: list[tuple[str, bytes]] = []
        for c in calls:
            name, args = c["function"]["name"], _args(c["function"].get("arguments"))
            if name == "submit":
                final = args
                steps.append({"type": "submit", "args": args})
                break
            t0 = time.monotonic()
            result = call(name, args)
            text, pngs = (result, []) if isinstance(result, str) else result
            images += [(text, png) for png in pngs]
            steps.append({"type": "tool", "name": name, "args": args, "seconds": round(time.monotonic() - t0, 1),
                          "result_chars": len(text), "images": len(pngs), "result": text[:2000]})
            messages.append({"role": "tool", "tool_call_id": c.get("id", ""), "content": text})
        if final is not None:
            break
        if images:
            content: list[dict[str, object]] = []
            for text, png in images:
                content.append({"type": "text", "text": text})
                content.append({"type": "image_url",
                                "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}})
            messages.append({"role": "user", "content": content})
            if keep_images is not None:
                _evict_images(messages, keep_images)
    else:
        error = f"step limit {max_steps}"
    return {
        "final": final,
        "error": None if final is not None else error,
        "infra_error": final is None and infra,
        "tool_calls": sum(1 for s in steps if s["type"] == "tool"),
        "seconds": round(time.monotonic() - start, 1),
        "usage": usage,
        "steps": steps,
    }

