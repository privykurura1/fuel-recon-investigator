"""Power layer: talk to Meterless Nightshift (OpenAI-compatible), which routes to NVIDIA Nemotron.

Uses plain HTTP so we can keep Nightshift's compute receipt (the `meterless` field)
as evidence of which model really answered.
"""
import re
import time

import requests

from . import config


class LLMError(RuntimeError):
    pass


def chat(messages, model=None, temperature=0.2, attempts=4):
    """Send a chat request, retrying brief network/provider failures. Returns (text, receipt_dict)."""
    for attempt in range(1, attempts + 1):
        try:
            return _chat_once(messages, model, temperature)
        except LLMError as exc:
            retryable = getattr(exc, "retryable", False)
            if not retryable or attempt == attempts:
                raise
            wait = 5 * attempt
            print(f"   (Nightshift/provider hiccup, retrying in {wait}s: {str(exc)[:120]})")
            time.sleep(wait)


def _chat_once(messages, model, temperature):
    token = config.need("METERLESS_RUNTIME_TOKEN")
    model = model or config.METERLESS_MODEL
    try:
        r = requests.post(
            config.METERLESS_BASE_URL + "/chat/completions",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "meterless-app": config.APP_NAME,
                "meterless-scope": "user",
            },
            json={"model": model, "messages": messages, "temperature": temperature},
            timeout=config.LLM_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        err = LLMError(f"Cannot reach Nightshift at {config.METERLESS_BASE_URL}: {exc}")
        err.retryable = True
        raise err from exc
    if r.status_code != 200:
        err = LLMError(f"Nightshift returned {r.status_code}: {r.text[:300]}")
        # 5xx / rate limits are usually temporary. Nightshift's auto-routing sometimes picks a retired
        # or missing model (wrapped in a 502); a retry is routed again, usually to a working Nemotron.
        err.retryable = r.status_code in (429, 500, 502, 503, 504)
        raise err
    body = r.json()
    try:
        msg = body["choices"][0]["message"]
        text = msg.get("content") or ""
        if not text.strip():
            # Some reasoning models put everything in a separate reasoning field and leave content empty.
            text = msg.get("reasoning_content") or msg.get("reasoning") or ""
    except (KeyError, IndexError) as exc:
        raise LLMError(f"Unexpected reply shape: {str(body)[:300]}") from exc
    m = body.get("meterless") or {}
    receipt = {
        "receipt_id": m.get("receipt_id"),
        "requested_model": m.get("requested_model", model),
        "routed_model": m.get("routed_model", body.get("model")),
        "tokens": (body.get("usage") or {}).get("total_tokens"),
    }
    return strip_thinking(text), receipt


def strip_thinking(text: str) -> str:
    """Remove <think>...</think> blocks some reasoning models emit."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
