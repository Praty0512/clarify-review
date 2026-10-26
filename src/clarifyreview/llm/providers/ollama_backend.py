"""Local models through Ollama (https://ollama.com).

A no-quota path for development, demos and a second-model study. It is not a
replacement for the Gemini reviewer: 3-4B local models write weaker reviews, and
results from different providers must never be pooled (every run records its
`served_model`, which here includes the weights digest).

Things that differ from the other backends and are worth knowing:

Context window. Ollama silently truncates a prompt that exceeds `num_ctx`,
dropping the *start* of it - which is where the system prompt lives. So the
window is sized per request from the prompt, and a prompt that cannot fit within
OLLAMA_NUM_CTX_MAX is refused up front instead of being quietly mangled.

Structured output. `format` takes a JSON schema and constrains decoding, but
small models still produce the occasional invalid object, so a failed parse gets
up to two repair turns that show the model its own validation error.

Caching. The context goes first in the prompt, so the prefix KV cache is reused
across the sampling detector's repeated calls for one pull request.

Thinking. Thinking-capable models (qwen3) can spend the whole `num_predict`
budget reasoning and emit no answer. OLLAMA_THINK=off (default) sends
`think: false`; `on` enables it only when the caller asks for thinking; `auto`
leaves it to the model.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time

import httpx
from pydantic import BaseModel, ValidationError

from ...config import cost_usd, settings
from ..base import Backend, Result, Usage

log = logging.getLogger(__name__)

SAFETY_TOKENS = 512
CTX_STEP = 2048
MIN_CTX = 4096
CHARS_PER_TOKEN = 3  # deliberately pessimistic for code
# Extra generation budget when the model is allowed to think: the reasoning is
# billed against num_predict before the answer starts.
THINK_ALLOWANCE = 2000


class OllamaUnavailable(RuntimeError):
    """The server cannot be reached, or cannot serve the requested model."""


class OllamaModelNotFound(OllamaUnavailable):
    """The server is up but the model has not been pulled."""


class OllamaBackend(Backend):
    name = "ollama"

    MAX_ATTEMPTS = 3  # transport / 5xx retries per request
    MAX_REPAIRS = 2  # extra turns spent on an invalid structured answer
    BASE_BACKOFF_S = 2.0

    def __init__(self, client: httpx.Client | None = None, *, host: str | None = None,
                 num_ctx_max: int | None = None, num_predict_max: int | None = None,
                 think: str | None = None, keep_alive: str | None = None,
                 timeout_s: float | None = None) -> None:
        cfg = settings()
        self.host = self.normalise_host(host or cfg.ollama_host)
        self.num_ctx_max = num_ctx_max or cfg.ollama_num_ctx_max
        self.num_predict_max = num_predict_max or cfg.ollama_num_predict_max
        self.think = (think or cfg.ollama_think).lower()
        if self.think not in ("off", "on", "auto"):
            raise ValueError(f"OLLAMA_THINK must be off, on or auto; got {self.think!r}")
        self.keep_alive = keep_alive or cfg.ollama_keep_alive
        self.timeout_s = timeout_s or cfg.ollama_timeout_s
        self._api_key = cfg.ollama_api_key
        self._client = client or httpx.Client(timeout=self.timeout_s)
        self._digests: dict[str, str] | None = None
        self._no_think: set[str] = set()
        # Models that reason even when sent think:false (e.g. the always-thinking
        # qwen3 builds). They leak the reasoning into `content` and run out of
        # budget before answering, so they are called with thinking left on and
        # the reasoning separated into `message.thinking`.
        self._reasoners: set[str] = set()

    # ------------------------------------------------------------ core calls

    def structured(self, *, model, schema: type[BaseModel], system, cached_context,
                   instruction, max_tokens=8192, thinking=True, temperature=None):
        json_schema = self._schema(schema)
        user = (
            f"{cached_context}\n\n{instruction}\n\n"
            "Respond with a single JSON object that matches this JSON schema:\n"
            f"{json.dumps(json_schema, separators=(',', ':'))}\n"
            "Return only the JSON object."
        )
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
        usage = Usage()
        raw = ""
        error = ""
        for turn in range(self.MAX_REPAIRS + 1):
            repairing = turn > 0
            data = self._chat(
                model, messages, fmt=json_schema, max_tokens=max_tokens,
                thinking=thinking,
                temperature=(0.0 if temperature is None else temperature)
                if repairing else temperature,
            )
            usage.add(self._usage(model, data))
            raw = (data.get("message") or {}).get("content") or ""
            if data.get("done_reason") == "length":
                log.warning("%s hit num_predict before finishing (%d output tokens); "
                            "the answer is probably truncated", model,
                            data.get("eval_count") or 0)
            value, error = self._parse(raw, schema)
            if value is not None:
                usage.served_model = self._served(model)
                return Result(value=value, usage=usage)
            log.warning("%s returned invalid %s (turn %d/%d): %s", model,
                        schema.__name__, turn + 1, self.MAX_REPAIRS + 1, error[:200])
            messages = messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": (
                    f"That was not valid: {error[:500]}\n"
                    "Return only the corrected JSON object.")},
            ]
        usage.served_model = self._served(model)
        raise ValueError(
            f"{model} returned no valid {schema.__name__} after "
            f"{self.MAX_REPAIRS + 1} attempts. Last error: {error[:300]}. "
            f"Raw text: {raw[:300]!r}"
        )

    def text(self, *, model, system, cached_context, instruction,
             max_tokens=4000, thinking=False, temperature=None):
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": f"{cached_context}\n\n{instruction}"}]
        data = self._chat(model, messages, fmt=None, max_tokens=max_tokens,
                          thinking=thinking, temperature=temperature)
        usage = self._usage(model, data)
        usage.served_model = self._served(model)
        content = (data.get("message") or {}).get("content") or ""
        return Result(value=self._strip_think(content).strip(), usage=usage)

    def list_models(self) -> list[str]:
        return sorted(self._tags())

    # -------------------------------------------------------------- internals

    def _options(self, prompt_text: str, max_tokens: int,
                 temperature: float | None, extra_predict: int = 0) -> dict:
        predict = min(max_tokens, self.num_predict_max) + extra_predict
        est_prompt = -(-len(prompt_text) // CHARS_PER_TOKEN)
        need = est_prompt + predict + SAFETY_TOKENS
        if need > self.num_ctx_max:
            raise ValueError(
                f"prompt ~{est_prompt} tokens exceeds OLLAMA_NUM_CTX_MAX "
                f"({self.num_ctx_max}): with {predict} tokens reserved for the "
                f"answer the window would need ~{need}. Ollama would otherwise "
                "silently truncate the start of the prompt, including the system "
                "prompt. Raise OLLAMA_NUM_CTX_MAX if your hardware allows, or "
                "review a smaller change."
            )
        num_ctx = max(MIN_CTX, -(-need // CTX_STEP) * CTX_STEP)
        opts: dict = {"num_ctx": min(num_ctx, max(self.num_ctx_max, MIN_CTX)),
                      "num_predict": predict}
        if temperature is not None:
            opts["temperature"] = temperature
        # No `seed`: a fixed seed would make the sampling detector's eight
        # samples identical and defeat the instrument.
        return opts

    def _think_flag(self, model: str, thinking: bool) -> bool | None:
        if model in self._no_think or self.think == "auto" or model in self._reasoners:
            return None
        if self.think == "off":
            return False
        return bool(thinking)

    def _chat(self, model, messages, *, fmt, max_tokens, thinking, temperature) -> dict:
        prompt_text = "\n".join(m["content"] for m in messages)
        flag = self._think_flag(model, thinking)
        body: dict = {
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": self._options(prompt_text, max_tokens, temperature,
                                     THINK_ALLOWANCE if flag is not False else 0),
        }
        if fmt is not None:
            body["format"] = fmt
        if flag is not None:
            body["think"] = flag
        started = time.monotonic()
        try:
            data = self._timed(self._post("/api/chat", body, model), started)
            if (flag is False and fmt is None and data.get("done_reason") == "length"
                    and not (data.get("message") or {}).get("thinking")):
                # think:false was ignored: the reasoning landed in `content` and
                # used the whole budget. Switch this model to separated thinking.
                log.info("%s ignores think:false (reasoning leaked into the answer); "
                         "using separated thinking with a larger budget", model)
                self._reasoners.add(model)
                return self._chat(model, messages, fmt=fmt, max_tokens=max_tokens,
                                  thinking=thinking, temperature=temperature)
            return data
        except _BadRequest as exc:
            if "think" in body and "does not support thinking" in str(exc).lower():
                log.info("%s does not support thinking; retrying without it", model)
                self._no_think.add(model)
                body.pop("think")
                try:
                    return self._timed(self._post("/api/chat", body, model), started)
                except _BadRequest as exc2:
                    raise RuntimeError(f"Ollama rejected the request: {exc2}") from None
            raise RuntimeError(f"Ollama rejected the request: {exc}") from None

    @staticmethod
    def _timed(data: dict, started: float) -> dict:
        data["_wall_ms"] = int((time.monotonic() - started) * 1000)
        return data

    def _headers(self) -> dict:
        key = self._api_key
        return {"Authorization": f"Bearer {key}"} if key else {}

    def _hint(self) -> str:
        return (f"Is Ollama running at {self.host}? Start the app or run "
                "`ollama serve`; set OLLAMA_HOST if it listens elsewhere.")

    def _post(self, path: str, body: dict, model: str) -> dict:
        last: Exception | None = None
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                resp = self._client.post(self.host + path, json=body,
                                         headers=self._headers())
            except httpx.ConnectError as exc:
                raise OllamaUnavailable(f"cannot connect to Ollama. {self._hint()}") from exc
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = exc
                log.warning("Ollama request failed (attempt %d/%d): %s", attempt,
                            self.MAX_ATTEMPTS, type(exc).__name__)
            else:
                if resp.status_code == 200:
                    return resp.json()
                detail = self._error_text(resp)
                if resp.status_code == 404:
                    raise OllamaModelNotFound(
                        f"Ollama says: {detail}. Pull the model first with "
                        f"`ollama pull {model}`.")
                if resp.status_code >= 500:
                    last = RuntimeError(f"Ollama {resp.status_code}: {detail}")
                    log.warning("Ollama %s (attempt %d/%d): %s", resp.status_code,
                                attempt, self.MAX_ATTEMPTS, detail[:200])
                else:
                    raise _BadRequest(detail)
            if attempt < self.MAX_ATTEMPTS:
                delay = self.BASE_BACKOFF_S * (2 ** (attempt - 1))
                time.sleep(delay * (0.5 + random.random()))
        raise OllamaUnavailable(
            f"Ollama failed {self.MAX_ATTEMPTS} times in a row ({last}). "
            + self._hint()) from last

    @staticmethod
    def _error_text(resp: httpx.Response) -> str:
        try:
            err = resp.json().get("error")
            if err:
                return str(err)
        except Exception:  # noqa: BLE001 - body may not be JSON
            pass
        return resp.text[:300] or f"HTTP {resp.status_code}"

    def _tags(self) -> dict[str, str]:
        """name -> full digest, from GET /api/tags."""
        try:
            resp = self._client.get(self.host + "/api/tags", headers=self._headers())
        except httpx.ConnectError as exc:
            raise OllamaUnavailable(f"cannot connect to Ollama. {self._hint()}") from exc
        if resp.status_code != 200:
            raise OllamaUnavailable(
                f"GET /api/tags returned {resp.status_code}: {self._error_text(resp)}")
        out = {}
        for m in resp.json().get("models", []):
            name = m.get("name") or m.get("model")
            if name:
                out[name] = m.get("digest") or ""
        return out

    def _served(self, model: str) -> str:
        """`model@digest12`, so a silently re-pulled tag is visible in the log."""
        if self._digests is None or model not in self._digests:
            try:
                self._digests = self._tags()
            except Exception:  # noqa: BLE001 - provenance is best effort
                return model
        digest = self._digests.get(model) or self._digests.get(f"{model}:latest") or ""
        return f"{model}@{digest[:12]}" if digest else model

    @staticmethod
    def _usage(model: str, data: dict) -> Usage:
        inp = data.get("prompt_eval_count") or 0
        out = data.get("eval_count") or 0
        return Usage(
            input_tokens=inp,
            output_tokens=out,
            cache_read_tokens=0,
            cache_write_tokens=0,
            cost_usd=cost_usd(model, input_tokens=inp, output_tokens=out),
            calls=1,
            latency_ms=data.get("_wall_ms")
            or int((data.get("total_duration") or 0) / 1_000_000),
            served_model=model,
        )

    # ---------------------------------------------------------------- parsing

    @staticmethod
    def normalise_host(h: str) -> str:
        """Accept what OLLAMA_HOST holds in the wild ("0.0.0.0:11434", "host")."""
        h = (h or "").strip().rstrip("/")
        if not h:
            h = "127.0.0.1:11434"
        if "://" not in h:
            h = "http://" + h
        scheme, rest = h.split("://", 1)
        hostport, _, path = rest.partition("/")
        host, sep, port = hostport.rpartition(":")
        if not sep or not port.isdigit():
            host, port = hostport, ""
        if host in ("0.0.0.0", "::", "[::]", ""):
            host = "127.0.0.1"
        if not port and scheme == "http":
            port = "11434"
        out = f"{scheme}://{host}" + (f":{port}" if port else "")
        return out + (f"/{path}" if path else "")

    @staticmethod
    def _strip_think(text: str) -> str:
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        # An unterminated block means the budget ran out mid-thought.
        return re.sub(r"<think>.*\Z", "", text, flags=re.DOTALL)

    @classmethod
    def _parse(cls, text: str, schema: type[BaseModel]) -> tuple[BaseModel | None, str]:
        """Validate the first JSON object in `text`; the error is fed back to the model."""
        cleaned = cls._strip_think(text or "")
        cleaned = re.sub(r"```(?:json)?", "", cleaned)
        start = cleaned.find("{")
        if start < 0:
            return None, "no JSON object found in the reply"
        try:
            obj, _ = json.JSONDecoder().raw_decode(cleaned[start:])
        except json.JSONDecodeError as exc:
            return None, f"invalid JSON: {exc}"
        try:
            return schema.model_validate(obj), ""
        except ValidationError as exc:
            return None, str(exc)

    @staticmethod
    def _schema(schema: type[BaseModel]) -> dict:
        """The pydantic schema with `$ref`s inlined (Ollama's grammar wants a tree)."""
        raw = schema.model_json_schema()
        defs = raw.get("$defs", {})

        def walk(node, seen: tuple[str, ...]):
            if isinstance(node, dict):
                ref = node.get("$ref")
                if isinstance(ref, str) and ref.startswith("#/$defs/"):
                    key = ref.rsplit("/", 1)[1]
                    if key in seen:
                        raise ValueError(f"recursive schema {key!r} cannot be inlined")
                    extra = {k: v for k, v in node.items() if k != "$ref"}
                    return {**walk(defs[key], seen + (key,)), **walk(extra, seen)}
                return {k: walk(v, seen) for k, v in node.items() if k != "$defs"}
            if isinstance(node, list):
                return [walk(v, seen) for v in node]
            return node

        return walk(raw, ())


class _BadRequest(Exception):
    """A 4xx the request itself caused (other than 404)."""
