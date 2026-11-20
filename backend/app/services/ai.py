"""Single gateway for every LLM call: rate limit, timing, error handling and the LLM call log."""
from __future__ import annotations

import time

from app.core import audit, config
from app.core.guardrails import RateLimiter
from app.core.llm import LLMError, chat, chat_json, get_usage, last_model, reset_usage

limiter = RateLimiter(config.LLM_RATE_LIMIT_PER_MIN)


class RateLimited(Exception):
    pass


def is_mock() -> bool:
    return config.LLM_PROVIDER == "mock"


def call(purpose: str, user: dict, messages: list[dict], system: str, *, as_json: bool = False,
         schema_hint: str = "", temperature: float | None = None, guard_meta: dict | None = None):
    """Returns (result, meta). result is None when the call failed; meta explains why."""
    if not limiter.allow(user["username"]):
        raise RateLimited(f"Rate limit reached ({config.LLM_RATE_LIMIT_PER_MIN} AI calls per minute). Try again shortly.")
    t0 = time.perf_counter()
    reset_usage()
    meta = {"provider": config.LLM_PROVIDER, "model": config.LLM_MODEL, "prompt_version": config.PROMPT_VERSION}
    temp = config.LLM_TEMPERATURE if temperature is None else temperature
    try:
        if as_json:
            result = chat_json(messages, system=system, schema_hint=schema_hint, temperature=temp)
        else:
            result = chat(messages, system=system, temperature=temp)
        meta.update(ok=True, error="", model=last_model())
    except LLMError as e:
        msg = str(e)
        if "content_filter" in msg or "safety" in msg.lower() or "blocked" in msg.lower():
            msg = "The provider's safety filter blocked this request. " + msg[:200]
        result = None
        meta.update(ok=False, error=msg)
    meta["latency_ms"] = int((time.perf_counter() - t0) * 1000)
    meta["usage"] = get_usage()
    audit.log_llm_call(user["username"], purpose, meta["provider"], meta["model"], meta["prompt_version"],
                       meta["latency_ms"], meta["ok"], guard_meta, meta["error"], usage=meta["usage"])
    return result, meta
