"""Language-model client for any OpenAI-compatible chat API, with an automatic backup.

The agent sends requests in the common `/v1/chat/completions` format, which Ollama, the team PC's
gateway (agent/llm_gateway.py), Groq, Google's Gemma API and OpenRouter all accept. Two endpoints can be
configured: the primary (the team PC running the SARP model) and a backup (a free hosted API). If the
primary fails before its first word, the backup answers; if both are down, the chat engine shows
offline answers from past counsellor conversations.

Settings (environment variables):
    SARP_LLM_BASE_URL     primary endpoint (default http://127.0.0.1:11434/v1, local Ollama)
    SARP_LLM_API_KEY      key for the primary (the gateway key; leave empty for local Ollama)
    SARP_LLM_MODEL        model on the primary (default gemma3:4b; the fine-tuned model's name later)
    SARP_LLM_FALLBACK_BASE_URL, SARP_LLM_FALLBACK_API_KEY, SARP_LLM_FALLBACK_MODEL   optional backup
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_MODEL = "gemma3:4b"
# ngrok's free plan shows a browser warning page unless this header is present; other APIs ignore it.
EXTRA_HEADERS = {"ngrok-skip-browser-warning": "1"}
log = logging.getLogger("sarp.llm")  # warnings appear in Vercel's runtime logs
# Reasoning that some models write into the reply itself (e.g. Gemma 4 on Google's API uses <thought>).
THOUGHT_TAGS = ("thought", "think", "thinking", "reasoning")


def strip_thoughts(chunks: Iterator[str]) -> Iterator[str]:
    """Drop <thought>...</thought> (and similar) blocks from a stream, even when a tag is split across chunks."""
    opens = [f"<{t}>" for t in THOUGHT_TAGS]
    keep = max(len(t) for t in opens) + 2  # enough to hold a tag cut in half
    buffer, closing = "", None
    for chunk in chunks:
        buffer += chunk
        while True:
            if closing:  # inside a thought block: discard up to its closing tag
                end = buffer.lower().find(closing)
                if end < 0:
                    buffer = buffer[-keep:]
                    break
                buffer, closing = buffer[end + len(closing):].lstrip(), None
                continue
            lower = buffer.lower()
            hits = [(lower.find(t), t) for t in opens if lower.find(t) >= 0]
            if hits:
                start, tag = min(hits)
                if buffer[:start]:
                    yield buffer[:start]
                buffer, closing = buffer[start + len(tag):], tag.replace("<", "</")
                continue
            # No full tag: send everything except a tail that might be the start of one.
            cut = buffer.rfind("<")
            safe = len(buffer) if cut < 0 or len(buffer) - cut > keep else cut
            if buffer[:safe]:
                yield buffer[:safe]
            buffer = buffer[safe:]
            break
    if buffer and not closing:
        yield buffer


@dataclass
class Endpoint:
    name: str
    base_url: str
    model: str
    api_key: str = ""
    transport: httpx.BaseTransport | None = None  # tests inject a mock transport
    _checked_at: float = field(default=0.0, repr=False)
    _ok: bool = field(default=False, repr=False)
    _problem: str | None = field(default=None, repr=False)  # why it is down, shown to counsellors

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")

    @property
    def is_local_ollama(self) -> bool:
        url = urlparse(self.base_url)
        return url.hostname in ("127.0.0.1", "localhost") and url.port == 11434

    def _client(self, timeout: httpx.Timeout | float) -> httpx.Client:
        headers = dict(EXTRA_HEADERS)
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return httpx.Client(transport=self.transport, timeout=timeout, headers=headers)

    def available(self, max_age: float = 30.0) -> bool:
        """True when the endpoint answers and offers the configured model (cached for max_age seconds)."""
        if time.time() - self._checked_at < max_age:
            return self._ok
        self._checked_at = time.time()
        self._ok, self._problem = False, None
        try:
            with self._client(5.0) as client:
                response = client.get(f"{self.base_url}/models")
            if response.status_code in (401, 403):
                self._problem = f"HTTP {response.status_code}: the key was refused"
                return False
            response.raise_for_status()
            ids = {str(m.get("id", "")) for m in response.json().get("data", [])}
            m = self.model
            self._ok = not ids or any(i in (m, f"{m}:latest") or i.endswith("/" + m) for i in ids)
            if not self._ok:
                self._problem = f"model {m} is not offered there"
        except httpx.HTTPStatusError as error:
            self._problem = f"HTTP {error.response.status_code}"
        except httpx.TimeoutException:
            self._problem = "no answer within 5 s"
        except httpx.HTTPError as error:
            self._problem = f"not reachable ({type(error).__name__})"
        except ValueError:
            self._problem = "unexpected reply (not an AI endpoint?)"
        return self._ok

    def mark_down(self, problem: str | None = None) -> None:
        self._ok, self._checked_at = False, time.time()
        self._problem = problem or self._problem

    def provider_options(self) -> dict | None:
        """Extra request fields for specific providers."""
        if "generativelanguage.googleapis.com" in self.base_url and self.model.startswith("gemma"):
            # Gemma 4 on Google's API thinks before answering unless told otherwise; "minimal" turns it off.
            return {"extra_body": {"google": {"thinking_config": {"thinking_level": "minimal",
                                                                  "include_thoughts": False}}}}
        return None

    def stream_chat(self, messages: list[dict], temperature: float = 0.4, max_tokens: int = 700) -> Iterator[str]:
        # If the provider rejects a request (400), retry with the system message folded into the first turn
        # (some hosted Gemma APIs refuse system messages) and then without provider-specific options.
        variants = [messages] + ([_fold_system(messages)] if messages and messages[0]["role"] == "system" else [])
        options = [self.provider_options()]
        if options[0]:
            options.append(None)
        error: httpx.HTTPStatusError | None = None
        for extra in options:
            for msgs in variants:
                try:
                    yield from strip_thoughts(self._stream(msgs, temperature, max_tokens, extra))
                    return
                except httpx.HTTPStatusError as rejected:
                    if rejected.response.status_code != 400:
                        raise
                    error = rejected
        raise error

    def _stream(self, messages: list[dict], temperature: float, max_tokens: int,
                extra: dict | None = None) -> Iterator[str]:
        payload = {"model": self.model, "messages": messages, "stream": True,
                   "temperature": temperature, "max_tokens": max_tokens, **(extra or {})}
        with self._client(httpx.Timeout(120, connect=5)) as client:
            with client.stream("POST", f"{self.base_url}/chat/completions", json=payload) as response:
                if response.status_code >= 400:
                    response.read()
                    response.raise_for_status()
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    if chunk.get("error"):
                        raise RuntimeError(str(chunk["error"]))
                    for choice in chunk.get("choices") or []:
                        text = (choice.get("delta") or {}).get("content") or ""
                        if text:
                            yield text

    def describe(self) -> dict:
        problem = self._problem
        if not self._ok and self.is_local_ollama and os.environ.get("VERCEL"):
            problem = "SARP_LLM_BASE_URL is not set in Vercel"
        return {"name": self.name, "model": self.model, "host": urlparse(self.base_url).hostname,
                "available": self._ok, "problem": None if self._ok else problem}


def _fold_system(messages: list[dict]) -> list[dict]:
    system, rest = messages[0]["content"], [dict(m) for m in messages[1:]]
    for m in rest:
        if m["role"] == "user":
            m["content"] = f"{system}\n\n---\n\n{m['content']}"
            return rest
    return [{"role": "user", "content": system}] + rest


class LLMRouter:
    """Tries the primary endpoint, then the backup. Same interface the chat engine already uses."""

    def __init__(self, endpoints: list[Endpoint]):
        self.endpoints = endpoints
        self.last_used: str | None = None

    @classmethod
    def from_env(cls) -> LLMRouter:
        env = os.environ.get
        endpoints = [Endpoint("primary", env("SARP_LLM_BASE_URL") or DEFAULT_BASE_URL,
                              env("SARP_LLM_MODEL") or DEFAULT_MODEL, env("SARP_LLM_API_KEY", ""))]
        if env("SARP_LLM_FALLBACK_BASE_URL") and env("SARP_LLM_FALLBACK_MODEL"):
            endpoints.append(Endpoint("backup", env("SARP_LLM_FALLBACK_BASE_URL"), env("SARP_LLM_FALLBACK_MODEL"),
                                      env("SARP_LLM_FALLBACK_API_KEY", "")))
        return cls(endpoints)

    @property
    def model(self) -> str:
        for e in self.endpoints:
            if e._ok:
                return e.model
        return self.endpoints[0].model

    def available(self, max_age: float = 30.0) -> bool:
        return any(e.available(max_age) for e in self.endpoints)

    def describe(self) -> list[dict]:
        # Check each endpoint: available() above stops at the first one that works, which would leave the
        # backup unchecked (and wrongly shown as down) whenever the team PC is up.
        for e in self.endpoints:
            e.available()
        return [e.describe() for e in self.endpoints]

    def stream_chat(self, messages: list[dict], temperature: float = 0.4) -> Iterator[str]:
        problems = []
        for endpoint in self.endpoints:
            if not endpoint.available():
                problems.append(f"{endpoint.name} unreachable ({endpoint._problem or 'no reason'})")
                continue
            started = False
            try:
                for chunk in endpoint.stream_chat(messages, temperature):
                    if not started:
                        started, self.last_used = True, endpoint.name
                    yield chunk
                if started:
                    return
                problems.append(f"{endpoint.name} sent an empty reply")
            except Exception as error:
                detail = ""
                if isinstance(error, httpx.HTTPStatusError):
                    detail = f" HTTP {error.response.status_code}: {error.response.text[:200]}"
                log.warning("%s model %s failed: %s%s", endpoint.name, endpoint.model, type(error).__name__, detail)
                endpoint.mark_down(f"reply failed ({type(error).__name__}{detail[:80]})")
                if started:
                    raise  # failed mid-reply: the chat engine adds a "cut short" note
                problems.append(f"{endpoint.name}: {type(error).__name__}")
        log.warning("No language model reachable: %s", "; ".join(problems))
        raise RuntimeError("No language model reachable (" + "; ".join(problems) + ")")

    def warm_up(self) -> None:
        """Load the model into GPU memory when the primary is Ollama on this machine."""
        primary = self.endpoints[0]
        if not primary.is_local_ollama:
            return
        try:
            root = primary.base_url.rsplit("/v1", 1)[0]
            httpx.post(f"{root}/api/generate", json={"model": primary.model, "prompt": "", "keep_alive": "30m"},
                       timeout=120)
        except httpx.HTTPError:
            pass


# Kept for code that imported the old name.
OllamaClient = LLMRouter.from_env
