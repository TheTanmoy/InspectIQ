"""Provider-agnostic LLM client using plain HTTP (requests) — no vendor SDKs needed.

Usage:
    from core.llm import chat, chat_stream, chat_json
    reply = chat([{"role": "user", "content": "Hi"}], system="You are helpful.")
    for token in chat_stream(messages): print(token, end="")
    data = chat_json(messages, schema_hint='{"summary": str, "risks": [str]}')
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Iterator

import requests

from app.core import config

Message = dict  # {"role": "user"|"assistant"|"system", "content": str}
log = logging.getLogger("inspectiq.llm")
_local = threading.local()


def last_model() -> str:
    """Model that answered the most recent call on this thread (primary or fallback)."""
    return getattr(_local, "model", config.LLM_MODEL)


# ---- token usage (FinOps): accumulated per thread between reset_usage() and get_usage()
def reset_usage():
    _local.usage = {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0, "requests": 0, "estimated": False}


def get_usage() -> dict:
    if not hasattr(_local, "usage"):
        reset_usage()
    return dict(_local.usage)


def _add_usage(inp: int = 0, out: int = 0, thinking: int = 0, estimated: bool = False):
    if not hasattr(_local, "usage"):
        reset_usage()
    u = _local.usage
    u["input_tokens"] += int(inp or 0)
    u["output_tokens"] += int(out or 0)
    u["thinking_tokens"] += int(thinking or 0)
    u["requests"] += 1
    u["estimated"] = u["estimated"] or estimated


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)  # ~4 characters per token - used only when a provider reports no usage


class LLMError(RuntimeError):
    pass


# ---------------------------------------------------------------- public API
def chat(messages: list[Message], system: str | None = None, **opts) -> str:
    """Return the full reply as a string."""
    return "".join(_dispatch(messages, system, stream=False, **opts))


def chat_stream(messages: list[Message], system: str | None = None, **opts) -> Iterator[str]:
    """Yield reply text chunk by chunk (falls back to one chunk if the provider can't stream)."""
    yield from _dispatch(messages, system, stream=True, **opts)


def chat_json(messages: list[Message], system: str | None = None, schema_hint: str = "", retries: int = 2, **opts) -> dict | list:
    """Ask for JSON and parse it robustly. Great for structured output (tables, scores, extracted fields)."""
    sys_prompt = (system or "") + (
        "\n\nRespond with ONLY valid JSON, no markdown fences, no commentary."
        + (f"\nFollow this shape: {schema_hint}" if schema_hint else "")
    )
    last_err = None
    for _ in range(retries + 1):
        raw = chat(messages, system=sys_prompt.strip(), **opts)
        try:
            return _extract_json(raw)
        except ValueError as e:
            last_err = e
            messages = messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "That was not valid JSON. Reply again with only the JSON."},
            ]
    raise LLMError(f"Model did not return valid JSON: {last_err}")


def health_check() -> str:
    return chat([{"role": "user", "content": "Reply with exactly: OK"}], max_tokens=10)


# ---------------------------------------------------------------- internals
def _dispatch(messages, system, stream, **opts) -> Iterator[str]:
    """Try the primary model; if it fails before producing any text, retry once on LLM_FALLBACK_MODEL."""
    primary = opts.get("model", config.LLM_MODEL)
    fallback = config.LLM_FALLBACK_MODEL if "model" not in opts else ""
    models = [primary] + ([fallback] if fallback and fallback != primary else [])
    for i, model in enumerate(models):
        has_next = i < len(models) - 1
        started = False
        try:
            for chunk in _dispatch_one(messages, system, stream, model, fast_fail=has_next, **opts):
                started = True
                _local.model = model
                yield chunk
            _local.model = model
            return
        except LLMError as e:
            if started or not has_next:
                raise
            log.warning("LLM model %s failed (%s) - falling back to %s", model, str(e).split("key=")[0][:160],
                        models[i + 1])


def _dispatch_one(messages, system, stream, model, fast_fail=False, **opts) -> Iterator[str]:
    before = get_usage()["requests"]
    out = []
    for chunk in _dispatch_raw(messages, system, stream, model, fast_fail, **opts):
        out.append(chunk)
        yield chunk
    if get_usage()["requests"] == before:  # provider gave no usage numbers -> estimate from text length
        prompt = (system or "") + "".join(str(m.get("content", "")) for m in messages)
        _add_usage(_estimate_tokens(prompt), _estimate_tokens("".join(out)), estimated=True)


def _dispatch_raw(messages, system, stream, model, fast_fail=False, **opts) -> Iterator[str]:
    provider = config.LLM_PROVIDER
    params = {
        "temperature": opts.get("temperature", config.LLM_TEMPERATURE),
        "max_tokens": opts.get("max_tokens", config.LLM_MAX_TOKENS),
        "model": model,
        # with a fallback waiting: one attempt and a shorter timeout, so users are not kept waiting
        "attempts": 1 if fast_fail else 3,
        "timeout": config.LLM_PRIMARY_TIMEOUT if fast_fail else config.LLM_TIMEOUT,
    }
    handler = {
        "openai": _openai,
        "azure": _openai,
        "anthropic": _anthropic,
        "gemini": _gemini,
        "mock": _mock,
    }.get(provider)
    if handler is None:
        raise LLMError(f"Unknown LLM_PROVIDER '{provider}'. Use openai|azure|anthropic|gemini|mock.")
    yield from handler(messages, system, stream, params)


def _post(url, headers, body, stream, attempts=3, timeout=None):
    """POST with simple retry on 429/5xx."""
    for attempt in range(attempts):
        last = attempt == attempts - 1
        try:
            r = requests.post(url, headers=headers, json=body, stream=stream,
                              timeout=timeout or config.LLM_TIMEOUT, verify=config.VERIFY_SSL)
        except requests.RequestException as e:
            if last:
                raise LLMError(f"Network error calling LLM: {e}") from e
            time.sleep(2 ** attempt)
            continue
        if r.status_code in (429, 500, 502, 503, 504) and not last:
            time.sleep(2 ** attempt)
            continue
        if r.status_code >= 400:
            raise LLMError(f"LLM HTTP {r.status_code}: {r.text[:500]}")
        return r
    raise LLMError("LLM request failed after retries")


def _sse_lines(resp) -> Iterator[str]:
    for line in resp.iter_lines(decode_unicode=True):
        if line and line.startswith("data:"):
            data = line[5:].strip()
            if data and data != "[DONE]":
                yield data


# --- OpenAI-compatible (OpenAI, Azure OpenAI, Groq, Together, vLLM, Ollama, most org gateways)
def _openai(messages, system, stream, p):
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    body = {"messages": msgs, "temperature": p["temperature"], "max_tokens": p["max_tokens"], "stream": stream}

    if config.LLM_PROVIDER == "azure":
        base = config.LLM_BASE_URL.rstrip("/")
        url = f"{base}/openai/deployments/{p['model']}/chat/completions?api-version={config.AZURE_API_VERSION}"
        headers = {"api-key": config.LLM_API_KEY, "Content-Type": "application/json"}
    else:
        base = (config.LLM_BASE_URL or "https://api.openai.com/v1").rstrip("/")
        url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
        headers = {"Authorization": f"Bearer {config.LLM_API_KEY}", "Content-Type": "application/json"}
        body["model"] = p["model"]

    resp = _post(url, headers, body, stream, p["attempts"], p["timeout"])
    if not stream:
        try:
            usage = resp.json().get("usage") or {}
            if usage:
                _add_usage(usage.get("prompt_tokens"), usage.get("completion_tokens"),
                           (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0))
        except ValueError:
            pass
    if not stream:
        yield resp.json()["choices"][0]["message"]["content"] or ""
        return
    for data in _sse_lines(resp):
        try:
            choices = json.loads(data).get("choices") or []
            delta = choices[0].get("delta", {}).get("content") if choices else None
        except (json.JSONDecodeError, IndexError):
            continue
        if delta:
            yield delta


# --- Anthropic Messages API
def _anthropic(messages, system, stream, p):
    base = (config.LLM_BASE_URL or "https://api.anthropic.com").rstrip("/")
    body = {"model": p["model"], "max_tokens": p["max_tokens"], "temperature": p["temperature"],
            "messages": [m for m in messages if m["role"] != "system"], "stream": stream}
    if system:
        body["system"] = system
    headers = {"x-api-key": config.LLM_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    resp = _post(f"{base}/v1/messages", headers, body, stream, p["attempts"], p["timeout"])
    if not stream:
        j = resp.json()
        if j.get("usage"):
            _add_usage(j["usage"].get("input_tokens"), j["usage"].get("output_tokens"))
        yield "".join(b.get("text", "") for b in j.get("content", []))
        return
    for data in _sse_lines(resp):
        evt = json.loads(data)
        if evt.get("type") == "content_block_delta":
            yield evt["delta"].get("text", "")


# --- Google Gemini (generativelanguage API)
def _gemini(messages, system, stream, p):
    base = (config.LLM_BASE_URL or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                for m in messages if m["role"] != "system"]
    body = {"contents": contents,
            "generationConfig": {"temperature": p["temperature"], "maxOutputTokens": p["max_tokens"]}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    method = "streamGenerateContent?alt=sse" if stream else "generateContent"
    sep = "&" if "?" in method else "?"
    url = f"{base}/models/{p['model']}:{method}{sep}key={config.LLM_API_KEY}"
    resp = _post(url, {"Content-Type": "application/json"}, body, stream, p["attempts"], p["timeout"])

    def text_of(obj):
        cands = obj.get("candidates") or []
        if not cands:
            return ""
        return "".join(part.get("text", "") for part in cands[0].get("content", {}).get("parts", []))

    def add(um):
        if um:  # thinking tokens are billed as output tokens
            _add_usage(um.get("promptTokenCount"), um.get("candidatesTokenCount"), um.get("thoughtsTokenCount", 0))

    if not stream:
        j = resp.json()
        add(j.get("usageMetadata"))
        yield text_of(j)
        return
    last_um = None
    for data in _sse_lines(resp):
        evt = json.loads(data)
        last_um = evt.get("usageMetadata") or last_um  # cumulative - keep the final one
        yield text_of(evt)
    add(last_um)


# --- Mock: lets you build the whole UI before you get the key
def _mock(messages, system, stream, p):
    last = messages[-1]["content"] if messages else ""
    if system and "JSON" in system:
        reply = json.dumps({"summary": f"Mock summary of: {last[:60]}", "items": ["alpha", "beta"], "score": 7})
    else:
        reply = (f"**[MOCK MODE]** You said: _{last[:200]}_\n\n"
                 "Set `LLM_PROVIDER` and `LLM_API_KEY` in `.env` to talk to a real model.")
    if not stream:
        yield reply
        return
    for word in reply.split(" "):
        time.sleep(0.02)
        yield word + " "


def _extract_json(text: str):
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=-1)
    end = max(text.rfind("}"), text.rfind("]"))
    if start != -1 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError("No JSON found in model output")
