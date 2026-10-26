"""The Ollama backend against a mock HTTP transport. No server, no model."""

import json

import httpx
import pytest

from clarifyreview import config
from clarifyreview.detect.uncertainty import SamplingUncertaintyDetector
from clarifyreview.llm.client import LLM
from clarifyreview.llm.providers import build_backend
from clarifyreview.llm.providers.ollama_backend import (
    OllamaBackend, OllamaModelNotFound, OllamaUnavailable,
)
from clarifyreview.types import ReviewFinding, ReviewOutput

REVIEW = ReviewOutput(
    intent_summary="moves validation upstream", overall_confidence=0.8,
    verdict="comment",
    findings=[ReviewFinding(file="a.py", line=1, severity="minor", category="style",
                            claim="c", evidence="e", suggested_fix="none",
                            confidence=0.5)],
)
DIGEST = "abcdef0123456789" * 4


def chat_reply(content, prompt=120, out=30, done_reason="stop"):
    return {"message": {"role": "assistant", "content": content},
            "prompt_eval_count": prompt, "eval_count": out,
            "done_reason": done_reason, "total_duration": 2_000_000_000}


class Server:
    """Scripted /api/chat replies (the last one repeats) plus a fixed /api/tags."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.chats: list[dict] = []
        self.tag_calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            self.tag_calls += 1
            return httpx.Response(200, json={"models": [
                {"name": "qwen3:4b", "digest": DIGEST},
                {"name": "llama3.2:3b", "digest": "ff" * 32}]})
        assert request.url.path == "/api/chat"
        self.chats.append(json.loads(request.content))
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, httpx.Response):
            return reply
        return httpx.Response(200, json=reply)


def make(*replies, **kw):
    server = Server(*replies)
    client = httpx.Client(transport=httpx.MockTransport(server))
    b = OllamaBackend(client, host="http://127.0.0.1:11434", **kw)
    return b, server


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("clarifyreview.llm.providers.ollama_backend.time.sleep",
                        lambda s: None)


def call(b, **kw):
    args = dict(model="qwen3:4b", schema=ReviewOutput, system="SYS", cached_context="CTX",
                instruction="GO", max_tokens=8192, thinking=True, temperature=None)
    args.update(kw)
    return b.structured(**args)


# ------------------------------------------------------------------ request

def test_structured_request_shape():
    b, srv = make(chat_reply(REVIEW.model_dump_json()))
    res = call(b)
    req = srv.chats[0]
    assert req["stream"] is False
    assert req["model"] == "qwen3:4b"
    assert req["keep_alive"] == "10m"
    assert [m["role"] for m in req["messages"]] == ["system", "user"]
    user = req["messages"][1]["content"]
    assert user.index("CTX") < user.index("GO")  # context first: prefix cache reuse
    assert "Return only the JSON object" in user
    fmt = req["format"]
    assert fmt["type"] == "object" and "$defs" not in fmt and "$ref" not in json.dumps(fmt)
    assert fmt["properties"]["findings"]["items"]["properties"]["file"]
    assert req["options"]["num_predict"] == 4096  # capped by OLLAMA_NUM_PREDICT_MAX
    assert req["options"]["num_ctx"] % 2048 == 0 and req["options"]["num_ctx"] >= 4096
    assert isinstance(res.value, ReviewOutput) and res.value.verdict == "comment"


def test_usage_cost_and_served_model():
    b, _ = make(chat_reply(REVIEW.model_dump_json(), prompt=777, out=55))
    u = call(b).usage
    assert (u.input_tokens, u.output_tokens, u.cache_read_tokens) == (777, 55, 0)
    assert u.cost_usd == 0.0 and u.calls == 1
    assert u.served_model == "qwen3:4b@" + DIGEST[:12]


def test_text_call():
    b, srv = make(chat_reply("<think>hmm</think>  Intent: fix.  ", out=7))
    res = b.text(model="llama3.2:3b", system="S", cached_context="C",
                 instruction="I", max_tokens=200, thinking=False, temperature=1.0)
    assert res.value == "Intent: fix."
    assert "format" not in srv.chats[0]
    assert srv.chats[0]["options"]["temperature"] == 1.0
    assert res.usage.served_model.startswith("llama3.2:3b@ffffffffffff")


def test_temperature_only_when_given_and_never_seed():
    b, srv = make(chat_reply(REVIEW.model_dump_json()))
    call(b)
    call(b, temperature=0.7)
    assert "temperature" not in srv.chats[0]["options"]
    assert srv.chats[1]["options"]["temperature"] == 0.7
    assert all("seed" not in r["options"] for r in srv.chats)


def test_think_flag_follows_setting():
    for setting, thinking, expected in [
        ("off", True, False), ("off", False, False), ("on", True, True),
        ("on", False, False), ("auto", True, "absent"),
    ]:
        b, srv = make(chat_reply(REVIEW.model_dump_json()), think=setting)
        call(b, thinking=thinking)
        got = srv.chats[0].get("think", "absent")
        assert got == expected, (setting, thinking)


def test_think_rejected_is_retried_once_and_remembered():
    bad = httpx.Response(400, json={"error": "\"llama3.2:3b\" does not support thinking"})
    b, srv = make(bad, chat_reply(REVIEW.model_dump_json()), think="on")
    call(b, model="llama3.2:3b")
    assert "think" in srv.chats[0] and "think" not in srv.chats[1]
    call(b, model="llama3.2:3b")
    assert "think" not in srv.chats[2]


# ------------------------------------------------------------------ parsing

def test_fenced_and_think_wrapped_json_needs_no_repair():
    wrapped = "<think>let me see</think>\n```json\n" + REVIEW.model_dump_json() + "\n```\nDone."
    b, srv = make(chat_reply(wrapped))
    res = call(b)
    assert len(srv.chats) == 1 and res.usage.calls == 1
    assert res.value.intent_summary == REVIEW.intent_summary


def test_invalid_then_valid_costs_one_repair_turn():
    b, srv = make(chat_reply('{"verdict": "approve"}', prompt=100, out=10),
                  chat_reply(REVIEW.model_dump_json(), prompt=150, out=20))
    res = call(b)
    assert len(srv.chats) == 2
    msgs = srv.chats[1]["messages"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[2]["content"] == '{"verdict": "approve"}'
    assert "intent_summary" in msgs[3]["content"]
    assert "Return only the corrected JSON object" in msgs[3]["content"]
    assert len(msgs[3]["content"]) < 700
    assert srv.chats[1]["options"]["temperature"] == 0.0  # repairs are deterministic
    assert (res.usage.calls, res.usage.input_tokens, res.usage.output_tokens) == (2, 250, 30)


def test_repair_keeps_requested_temperature():
    b, srv = make(chat_reply("nope"), chat_reply(REVIEW.model_dump_json()))
    call(b, temperature=0.9)
    assert srv.chats[1]["options"]["temperature"] == 0.9


def test_three_invalid_answers_raise_with_raw_text():
    b, srv = make(chat_reply("not json at all"))
    with pytest.raises(ValueError, match="not json at all"):
        call(b)
    assert len(srv.chats) == 3


def test_length_truncation_is_logged(caplog):
    b, _ = make(chat_reply(REVIEW.model_dump_json(), done_reason="length"))
    with caplog.at_level("WARNING"):
        call(b)
    assert "num_predict" in caplog.text


# ------------------------------------------------------------------- errors

def test_connection_refused_gives_a_hint():
    def refuse(request):
        raise httpx.ConnectError("refused")

    b = OllamaBackend(httpx.Client(transport=httpx.MockTransport(refuse)),
                      host="http://127.0.0.1:11434")
    with pytest.raises(OllamaUnavailable, match="ollama serve"):
        call(b)


def test_missing_model_says_to_pull():
    b, _ = make(httpx.Response(404, json={"error": "model 'qwen3:4b' not found"}))
    with pytest.raises(OllamaModelNotFound, match="ollama pull qwen3:4b"):
        call(b)
    assert issubclass(OllamaModelNotFound, OllamaUnavailable)


def test_503_is_retried():
    b, srv = make(httpx.Response(503, json={"error": "busy"}),
                  httpx.Response(503, json={"error": "busy"}),
                  chat_reply(REVIEW.model_dump_json()))
    assert call(b).value.verdict == "comment"
    assert len(srv.chats) == 3


def test_persistent_503_gives_up():
    b, srv = make(httpx.Response(503, json={"error": "busy"}))
    with pytest.raises(OllamaUnavailable):
        call(b)
    assert len(srv.chats) == OllamaBackend.MAX_ATTEMPTS


def test_other_4xx_is_not_retried():
    b, srv = make(httpx.Response(400, json={"error": "bad options"}))
    with pytest.raises(RuntimeError, match="bad options"):
        call(b)
    assert len(srv.chats) == 1


def test_oversized_prompt_is_refused_before_any_request():
    b, srv = make(chat_reply("{}"), num_ctx_max=4096)
    with pytest.raises(ValueError, match="exceeds OLLAMA_NUM_CTX_MAX"):
        call(b, cached_context="x" * 30_000)
    assert srv.chats == []


def test_bearer_key_sent_only_when_configured(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.headers.get("authorization"))
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": []})
        return httpx.Response(200, json=chat_reply(REVIEW.model_dump_json()))

    monkeypatch.setenv("OLLAMA_API_KEY", "sekret")
    config.reset_settings()
    try:
        b = OllamaBackend(httpx.Client(transport=httpx.MockTransport(handler)))
        call(b)
    finally:
        monkeypatch.delenv("OLLAMA_API_KEY")
        config.reset_settings()
    assert seen[0] == "Bearer sekret"


# ------------------------------------------------------------------- misc

def test_list_models():
    b, _ = make(chat_reply("{}"))
    assert b.list_models() == ["llama3.2:3b", "qwen3:4b"]


def test_digest_lookup_is_cached():
    b, srv = make(chat_reply(REVIEW.model_dump_json()))
    call(b)
    call(b)
    assert srv.tag_calls == 1


@pytest.mark.parametrize("raw,expected", [
    ("0.0.0.0:11434", "http://127.0.0.1:11434"),
    ("localhost", "http://localhost:11434"),
    ("http://127.0.0.1:11434/", "http://127.0.0.1:11434"),
    ("https://ollama.example.com", "https://ollama.example.com"),
    ("192.168.1.5:9000", "http://192.168.1.5:9000"),
    ("", "http://127.0.0.1:11434"),
])
def test_normalise_host(raw, expected):
    assert OllamaBackend.normalise_host(raw) == expected


def test_schema_inlines_refs():
    s = OllamaBackend._schema(ReviewOutput)
    assert "$defs" not in s and "$ref" not in json.dumps(s)


def test_build_backend_from_env(monkeypatch):
    monkeypatch.setenv("CLARIFYREVIEW_PROVIDER", "ollama")
    config.reset_settings()
    try:
        assert build_backend().name == "ollama"
        assert config.settings().api_key() == "ollama"
        assert config.review_model() == "qwen3:4b-instruct-2507-q4_K_M"
    finally:
        monkeypatch.delenv("CLARIFYREVIEW_PROVIDER")
        config.reset_settings()


def test_sampling_detector_makes_eight_calls_at_temperature_one(ambiguous_ctx):
    b, srv = make(chat_reply("The author is fixing login."))
    det = SamplingUncertaintyDetector(llm=LLM(backend=b), n=8, embedder=object(),
                                      model="qwen3:4b")
    hyps, cost = det._hypotheses(ambiguous_ctx)
    assert len(hyps) == 8 and len(srv.chats) == 8 and cost == 0.0
    assert all(r["options"]["temperature"] == 1.0 for r in srv.chats)
    # identical prefix on every call -> Ollama can reuse the prompt cache
    assert len({r["messages"][1]["content"] for r in srv.chats}) == 1


def test_model_that_ignores_think_false_is_switched_to_separated_thinking():
    """qwen3 builds that always reason leak the chain of thought into `content`
    and hit the token cap; the backend must retry with thinking separated and a
    bigger budget, and remember it."""
    leaked = chat_reply("We are given a pull request with...", done_reason="length", out=200)
    good = chat_reply("It removes the email check.")
    good["message"]["thinking"] = "long reasoning"
    b, srv = make(leaked, good)
    kw = dict(model="qwen3:4b", system="S", cached_context="C", instruction="I",
              max_tokens=200, thinking=False, temperature=1.0)
    assert b.text(**kw).value == "It removes the email check."
    assert srv.chats[0]["think"] is False and srv.chats[0]["options"]["num_predict"] == 200
    assert "think" not in srv.chats[1]
    assert srv.chats[1]["options"]["num_predict"] > 2000
    b.text(**kw)  # remembered: goes straight to separated thinking
    assert len(srv.chats) == 3 and "think" not in srv.chats[2]
