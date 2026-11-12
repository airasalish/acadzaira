"""LLM client, cache and usage log (docs/PLAN.md §5).

One call shape for every role: a versioned system prompt from prompts/ (instructions only),
a user message built by code (the data, with student comments inside <untrusted_comment>),
and a JSON schema the reply must match. The LLM only ever returns observations.

Cache: one JSON file keyed "<subject_id>|<role>". An entry is reused only if its prompt
version, model and request hash all match, so a new prompt version or model recomputes.
Modes:
  live    cache hit → stored response; miss → real API call, stored, usage logged
  offline cache hit only; a miss is returned as an error (→ faculty_review, never dropped)
  fake    deterministic stub responses, separate cache file; for plumbing tests only
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from engine import config

_lock = threading.Lock()
_cache: dict[str, dict] | None = None
_cache_path = config.CACHE_PATH
MODE = "live"   # set by engine/run.py: live | offline | fake


@dataclass
class LLMResult:
    data: dict | None
    error: str | None = None
    cached: bool = False
    model: str | None = None


def set_mode(mode: str) -> None:
    global MODE, _cache, _cache_path
    MODE = mode
    _cache = None
    _cache_path = config.CACHE_PATH.with_name("fake_cache.json") if mode == "fake" else config.CACHE_PATH


def _load_cache() -> dict:
    global _cache
    if _cache is None:
        _cache = json.loads(_cache_path.read_text(encoding="utf-8")) if _cache_path.exists() else {}
    return _cache


def _save_cache() -> None:
    _cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _cache_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(_cache, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_cache_path)


def load_prompt(role: str) -> tuple[str, str]:
    """(version, system prompt text) from prompts/<role>.<version>.md. Saved by the candidate."""
    version = config.PROMPT_VERSIONS[role]
    path = config.PROMPTS_DIR / f"{role}.{version}.md"
    if MODE == "fake" and not path.exists():
        return version, f"[fake mode placeholder for {role}.{version}]"
    if not path.exists():
        raise FileNotFoundError(f"prompt file {path.relative_to(config.ROOT)} is missing (the candidate saves it)")
    return version, path.read_text(encoding="utf-8")


def _model_for(role: str) -> str | None:
    return {"gemini": config.MODEL_A, "groq": config.MODEL_B}.get(config.PROVIDERS[role])


def _log_usage(role: str, subject_id: str, model: str, inp: int, out: int) -> None:
    price = config.PRICES.get(model)
    if price is not None:
        cost = round(inp / 1e6 * price[0] + out / 1e6 * price[1], 6)
    else:
        cost = 0.0 if config.FREE_TIER else None
    line = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "role": role,
            "subject_id": subject_id, "model": model, "input_tokens": inp, "output_tokens": out,
            "cost_usd": cost}
    config.USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _lock, config.USAGE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")


# ---------------------------------------------------------------- providers

_clients: dict[str, Any] = {}


def _client(provider: str):
    import os
    from openai import OpenAI  # lazily, so offline/fake runs need no network setup

    if provider not in _clients:
        ep = config.PROVIDER_ENDPOINTS[provider]
        key = os.environ.get(ep["key_env"])
        if not key:
            raise RuntimeError(f"{ep['key_env']} is not set (.env)")
        _clients[provider] = OpenAI(base_url=ep["base_url"], api_key=key, max_retries=config.MAX_RETRIES,
                                    timeout=config.CALL_TIMEOUT)
    return _clients[provider]


def _call_openai_compatible(role: str, model: str, system: str, user: str, schema: dict,
                            provider: str | None = None) -> tuple[str, int, int]:
    """Chat Completions on the provider's OpenAI-compatible endpoint, JSON output.

    Free-tier models differ in what they accept, so we try progressively plainer requests:
      1. strict json_schema + reasoning effort   2. strict json_schema   3. json_object with the
    schema written into the system prompt. Whatever comes back is still validated by
    engine/validate.py, so a weaker mode can never slip an invalid shape through.
    """
    from openai import BadRequestError

    provider = provider or config.PROVIDERS[role]
    client = _client(provider).with_options(max_retries=0)   # pacing is handled in call_json
    schema_fmt = {"type": "json_schema", "json_schema": {"name": role, "schema": schema, "strict": True}}
    effort = config.REASONING_EFFORT.get(role)
    attempts = []
    if effort:
        attempts.append((schema_fmt, effort, system))
    attempts.append((schema_fmt, None, system))
    attempts.append(({"type": "json_object"}, None,
                     system + "\n\nReturn one JSON object matching this JSON Schema exactly:\n" + json.dumps(schema)))
    last: Exception | None = None
    for fmt, eff, sys_text in attempts:
        kwargs: dict[str, Any] = dict(
            model=model, temperature=config.TEMPERATURE, max_tokens=config.MAX_TOKENS[role],
            response_format=fmt,
            messages=[{"role": "system", "content": sys_text}, {"role": "user", "content": user}],
        )
        if eff:
            kwargs["reasoning_effort"] = eff
        try:
            resp = client.chat.completions.create(**kwargs)
        except BadRequestError as e:   # unsupported parameter/format on this model → plainer request
            last = e
            continue
        choice = resp.choices[0]
        if choice.finish_reason == "length":
            raise RuntimeError("hit max_tokens before finishing")
        usage = resp.usage
        return (choice.message.content or ""), getattr(usage, "prompt_tokens", 0), getattr(usage, "completion_tokens", 0)
    raise RuntimeError(f"{provider} rejected every request form: {last}")


# ---------------------------------------------------------------- public entry

def call_json(role: str, subject_id: str, user: str, schema: dict,
              fake: Callable[[], dict] | None = None) -> LLMResult:
    """Return the parsed JSON observation for (subject_id, role), or an error string.
    Never raises for API/validation problems: the caller routes errors to faculty_review."""
    try:
        version, system = load_prompt(role)
    except FileNotFoundError as e:
        return LLMResult(None, str(e))
    # Candidates in order: the role's own provider, then an optional fallback (config.ROLE_FALLBACK).
    # A cached answer from any candidate is reused, so earlier results from the primary provider
    # are kept. A live call tries each candidate that is not cache-only, in order.
    if MODE == "fake":
        cands = [("fake", "fake")]
    else:
        cands = [(config.PROVIDERS[role], _model_for(role))]
        fb = getattr(config, "ROLE_FALLBACK", {}).get(role)
        if fb:
            cands.append(tuple(fb))
        cands = [(pv, m) for pv, m in cands if m]
    # One failure message for every mode. It is quoted in the classify prompt, so it is part of that
    # request's hash: if it differed between a live and a cached run, results would not reproduce.
    unavailable = f"no {role} result available for {subject_id}"
    if not cands:
        return LLMResult(None, unavailable)
    req_hash = hashlib.sha256(json.dumps([system, user, schema], sort_keys=True).encode("utf-8")).hexdigest()[:16]
    key = f"{subject_id}|{role}"

    with _lock:
        entry = _load_cache().get(key)
    if entry and entry.get("prompt_version") == version and entry.get("request_hash") == req_hash \
            and entry.get("model") in [m for _, m in cands]:
        res = _parse(entry["response"], cached=True)
        res.model = entry.get("model")
        return res

    live = [(pv, m) for pv, m in cands if MODE == "fake" or pv not in config.CACHE_ONLY_PROVIDERS]
    if MODE == "offline" or not live:
        return LLMResult(None, unavailable)

    text = model = None
    for n, (provider, cand_model) in enumerate(live):
        last = n == len(live) - 1
        for attempt in range(config.RATE_LIMIT_RETRIES + 1):
            try:
                if MODE == "fake":
                    text, inp, out = json.dumps(fake() if fake else {}), 0, 0
                else:
                    t0 = time.time()
                    text, inp, out = _call_openai_compatible(role, cand_model, system, user, schema, provider=provider)
                    _log_usage(role, subject_id, cand_model, inp, out)
                    print(f"   {role:8s} {subject_id} {time.time() - t0:5.1f}s in={inp} out={out} [{cand_model}]", flush=True)
                model = cand_model
                break
            except Exception as e:  # API errors become routed errors, never silent drops
                # a rate limit, a timeout or a dropped connection is worth another try
                rate_limited = type(e).__name__ in ("RateLimitError", "APITimeoutError", "APIConnectionError")
                # A rate limit on the last candidate is worth waiting out; on an earlier one, move on.
                if rate_limited and last and attempt < config.RATE_LIMIT_RETRIES:
                    hdr = getattr(getattr(e, "response", None), "headers", {}) or {}
                    try:
                        wait = float(hdr.get("retry-after", config.RATE_LIMIT_WAIT))
                    except (TypeError, ValueError):
                        wait = config.RATE_LIMIT_WAIT
                    time.sleep(min(max(wait, 3.0), 90.0) + 1.0)
                    continue
                print(f"   {role:8s} {subject_id} FAILED on {cand_model}: {type(e).__name__}", flush=True)
                break
        if model is not None:
            break
    if model is None:
        return LLMResult(None, unavailable)
    if MODE != "fake" and config.CALL_SPACING:
        time.sleep(config.CALL_SPACING)

    with _lock:
        _load_cache()[key] = {"prompt_version": version, "model": model, "request_hash": req_hash, "response": text}
        _save_cache()
    res = _parse(text, cached=False)
    res.model = model
    return res


def _parse(text: str, cached: bool) -> LLMResult:
    text = text.strip()
    if text.startswith("```"):   # some models fence JSON even in JSON mode
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return LLMResult(None, f"response is not JSON: {e}", cached)
    if not isinstance(data, dict):
        return LLMResult(None, "response JSON is not an object", cached)
    return LLMResult(data, None, cached)
