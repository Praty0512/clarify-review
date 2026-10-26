# Running ClarifyReview on local models (Ollama)

`CLARIFYREVIEW_PROVIDER=ollama` runs every LLM call (review, questions, oracle,
judge, sampling detector) against a local [Ollama](https://ollama.com) server.
No API key, no quota, no per-token cost.

**What this is for:** development, demos, offline use, and a *second-model study*.
**What it is not:** a replacement for the Gemini reviewer. 3-4B local models write
weaker reviews. Results produced with Ollama must never be pooled with Gemini
results; every run records `served_model` (here `name@<12-char weights digest>`)
so the two are separable in the database.

## Setup

```
ollama pull qwen3:4b-instruct-2507-q4_K_M   # reviewer + sampling detector, ~2.5 GB
ollama pull llama3.2:3b    # question / oracle / judge, ~2 GB
```

Then in `.env` (or the environment):

```
CLARIFYREVIEW_PROVIDER=ollama
```

Check it end to end with one command (no database writes):

```
.venv\Scripts\python.exe -m experiments.ollama_smoke
```

It lists pulled models, runs one structured review of `examples/ambiguous.diff`
and one text call, and prints the served model, tokens, latency and whether the
JSON validated against `ReviewOutput`. The first call includes loading the model
into memory and is slow; run it twice to see warm latency.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Server URL. `0.0.0.0:11434` (as Ollama itself accepts) is normalised to `127.0.0.1`. |
| `OLLAMA_NUM_CTX_MAX` | `16384` | Largest context window ever requested. A prompt that would need more is refused with an error. |
| `OLLAMA_NUM_PREDICT_MAX` | `4096` | Cap on generated tokens per call (the reviewer asks for 16000; local models do not need it). |
| `OLLAMA_THINK` | `off` | `off` always sends `think:false`; `on` thinks only when the caller asks for thinking; `auto` leaves it to the model. |
| `OLLAMA_KEEP_ALIVE` | `10m` | How long a model stays loaded after a call. |
| `OLLAMA_TIMEOUT_S` | `600` | Per-request timeout. Local generation on a 4 GB GPU is slow. |
| `OLLAMA_API_KEY` | unset | Only if a proxy in front of Ollama requires a bearer token. |

Per-role overrides work as for other providers, e.g.
`CLARIFYREVIEW_MODEL_REVIEW=gemma3:4b`. Defaults never use `:latest`; pin the tag
you actually pulled.

## Why these models (16 GB RAM, RTX 3050 4 GB VRAM, little disk)

* **qwen3:4b-instruct-2507-q4_K_M** for review and sampling: a non-thinking
  build, so it honours `think:false` (a structured review takes about 6 s). The
  plain `qwen3:4b` build is not used by default because it ignores `think:false`
  and reasons in `content`, which is about 4x slower. Qwen3-4B gives the strongest instruction-following and
  JSON adherence that fits in 4 GB VRAM. Its KV cache is about 74 KB/token at
  `q8_0`, so a 16k window is roughly 1.2 GB on top of ~2.5 GB of weights.
* **llama3.2:3b** for question, oracle and judge: a different model family from
  the reviewer, so the judge does not score its own output, and a weaker oracle
  volunteers less unasked-for information (the leakage failure mode Study A must
  defend against).
* Optional alternatives: `gemma3:4b`, `qwen2.5-coder:3b`, `qwen2.5-coder:7b` (the
  last will spill to CPU on 4 GB VRAM).
* Avoid 7B+ models and R1-style distills on this hardware: they spill to system
  RAM and become unusably slow, and distills spend their token budget on thinking.

## Server tuning (set before starting Ollama)

```
OLLAMA_FLASH_ATTENTION=1      # needed for a quantised KV cache
OLLAMA_KV_CACHE_TYPE=q8_0     # halves KV memory vs f16
OLLAMA_MAX_LOADED_MODELS=1    # 4 GB VRAM holds one model at a time
OLLAMA_MODELS=D:\ollama\models  # move weights to a drive with space
```

On Windows set these as user environment variables and restart the Ollama app.

## Behaviour worth knowing

* **Model swaps are slow.** Review and question use different models, so a run
  alternates between them and pays a load (several seconds) at each switch. The
  context window is also sized per request, and a change of `num_ctx` reloads the
  model, so calls with very different prompt or output sizes can reload too.
  Running with the same model for all roles (`CLARIFYREVIEW_MODEL_*=qwen3:4b-instruct-2507-q4_K_M`)
  avoids swaps at the cost of the judge scoring its own family.
* **No silent truncation.** Ollama drops the *start* of a prompt that exceeds the
  window, which is where the system prompt is. The backend estimates the prompt
  (about 3 characters per token), sizes `num_ctx` to fit, and raises
  `prompt ~N tokens exceeds OLLAMA_NUM_CTX_MAX` instead of truncating.
* **Structured output** uses Ollama's `format` (JSON schema, constrained
  decoding). Invalid objects get up to two repair turns showing the model its
  validation error; if all fail, a `ValueError` carries the raw text.
* **Thinking.** qwen3 can spend all of `num_predict` reasoning and return an
  empty answer, which would silently ruin judging. Hence `OLLAMA_THINK=off`. If
  you turn it on, expect longer calls and watch for `done_reason: length` warnings.
* **Models that ignore `think:false`.** The plain `qwen3:4b` build (no longer the default) always
  reasons: with `think:false` it still produces its chain of thought, but as plain
  `content`, which hits the token cap before any answer (the sampling detector
  then gets "We are given a pull request..." instead of an intent sentence).
  The backend detects this (a free-text reply that stops at the length cap with
  no separate `thinking` field), remembers the model, and from then on leaves
  thinking on so Ollama splits the reasoning into `message.thinking`, with an
  extra 2000-token budget for it. Correct but about 4x slower, so it is kept only as a
  fallback; the default `qwen3:4b-instruct-2507-q4_K_M` avoids the problem.
* **Caching.** The PR context is placed first in every prompt, so Ollama's prefix
  cache is reused across the sampling detector's eight calls. Reported
  `cache_read_tokens` is 0 because Ollama does not expose it; the input-token
  count is `prompt_eval_count`, which is smaller on a cache hit.
* **No seed.** The backend never sets `seed`; a fixed seed would make the eight
  samples identical and defeat the uncertainty detector.
* **Digest pinning.** `served_model` is `<tag>@<digest>`. If you re-pull a tag
  and the weights change, the digest changes, and the database shows it.
* **Outages.** If the server is down or a model is not pulled, calls raise
  `OllamaUnavailable` with the fix. `experiments.run_matrix` stops at the first
  such failure (`--no-stop-on-unavailable` to keep going; `--resume` to continue)
  and `experiments.judge` stops too.

## Running the experiments locally

```
set CLARIFYREVIEW_PROVIDER=ollama
.venv\Scripts\python.exe -m experiments.run_matrix --instances data/instances.v2.jsonl --db data/study_ollama.db --limit 3
```

Use a separate `--db` so local results stay apart from the Gemini study.
