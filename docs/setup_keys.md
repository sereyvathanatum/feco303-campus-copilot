# Keys and run modes

Every key is optional. Without keys the copilot runs in `offline` mode with stub models, a stub decider,
and recorded API fixtures; every demo turn and every test still runs.

| Mode | Keys | What runs live |
|---|---|---|
| `offline` | none | nothing; stubs and fixtures |
| `nim` | `NVIDIA_API_KEY` and/or `GEMINI_API_KEY` | chat and vision model, NIM embeddings; stub decider |
| `full` | the above + the `laya` package installed | everything, with public APIs live or cached |

The decision model needs no key. `pip install laya` puts Laya in the process (`LAYA_MODE=local`, the
default) and the checkpoints download from Hugging Face on first use; `pip install "laya[serve]"` plus a
running `laya-serve` answers over HTTP instead (`LAYA_MODE=http`, `LAYA_BASE_URL`). `LAYA_MODE=off` keeps
the stub decider.

`python -m campus_copilot.cli check` prints the mode, the `.env` file found, each key's state (set, missing,
or placeholder, never the value), the model IDs, and a reachability probe per service.

## The `.env` file

1. Copy the template: `python -m campus_copilot.cli init-env` (never overwrites an existing `.env`).
2. Replace the placeholder values. A placeholder counts as a missing key.
3. `.env` is listed in `.gitignore`. Keys live in `.env` only: never in source files, notebooks,
   screenshots, traces, or commits. The pre-commit hook and CI reject a file that holds a key-shaped string.

| Variable | Where it comes from | Used for |
|---|---|---|
| `NVIDIA_API_KEY` | https://build.nvidia.com/ (free key) | NIM chat and vision (`google/gemma-4-31b-it`) |
| `NVIDIA_NEMOTRON_API_KEY` | optional second NIM key | NIM small model, embeddings, reranker; falls back to `NVIDIA_API_KEY` |
| `GEMINI_API_KEY` | https://aistudio.google.com/apikey (free tier) | Gemma 4 through Google AI Studio |
| `COPILOT_CHAT_PROVIDER` | `nim` (default) or `google` | which chat provider goes first; the other is the fallback |
| `LAYA_MODE` | `local` (default), `http`, or `off` | where the Laya decision model runs |
| `LAYA_API_KEY` | only when `laya-serve` runs behind a bearer token | the `Authorization` header sent in `http` mode |
| `HF_TOKEN` | https://huggingface.co/settings/tokens | optional: published tokenizers for chunk sizing |

## Provider fallback

The chat client tries the selected provider first, then the other provider, then the stub model. A reply
from the stub carries the label `STUB (<provider> unavailable)` in the trace and in the UI. A provider that
times out is skipped for five minutes, so later turns do not wait again. Google AI Studio runs Gemma 4 with
thinking always on, so its requests use a larger token budget and a longer timeout (`GOOGLE_TIMEOUT`, 120 s).

## A leaked key

1. Revoke the key in the provider console at once and create a new one.
2. Put the new key in `.env` only.
3. Remove the old key from any file, notebook, or screenshot; run `python scripts/check_secrets.py`.
4. If the key reached a git commit, treat the whole history as exposed: rewriting history does not make a
   pushed key safe again; revocation does.
