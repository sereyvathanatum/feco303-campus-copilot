# Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `No module named campus_copilot` (or `dotenv`, `gradio`, …) | the virtual environment is not active, so `python` is the system interpreter | `source .venv/bin/activate` (PowerShell: `.venv\Scripts\Activate.ps1`) in every new terminal; the prompt shows `(.venv)` |
| PowerShell: `Activate.ps1 cannot be loaded because running scripts is disabled` | the default execution policy blocks scripts | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then activate again |
| `cli check` says `offline` although keys are in `.env` | the `.env` still holds placeholder values, or it sits in another folder | edit the values; `cli check` prints the `.env` path it found; `COPILOT_ENV_FILE` points to a different file |
| Answers carry `STUB (google, nim unavailable)` | every live chat provider failed or timed out | `cli check` for reachability; AI Studio returns HTTP 503 under high demand, so retry later; NIM chat requests can queue for minutes |
| Gemma replies arrive after 40-90 s | AI Studio free-tier load; thinking is always on for Gemma 4 there | expected on the free tier; offline mode and recorded fixtures keep sessions moving |
| An answer is empty or only thought text | the token budget was spent on thinking | Google calls already use at least 4,096 tokens; raise `NIM_MAX_TOKENS` for other providers |
| `sqlite-vec unavailable` | the Python build blocks SQLite extension loading (for example the macOS system Python) | use a Python from python.org or Homebrew; the default store still works |
| `SQLite FTS5 missing` | a Python build without FTS5 | lexical search falls back to the hashing encoder automatically |
| Chroma column missing in the Retrieval Lab | Chroma is an optional extra | `pip install -r requirements-optional.txt` |
| The second `cli ingest` still embeds chunks | the embedding model changed (offline hashing vs NIM) or a document changed | vectors are cached per model and content hash; this is expected once per model |
| `ingest failed: stage embed failed` | a NIM batch failed after retries (rate limit or network) | `cli ingest --resume RUN_ID` continues from the failed stage; cached batches are kept |
| Verify reports FAIL | probe hit@3 below `ingest.verify_min_hit_rate` | `cli ingest --show verify` lists failing probes; offline hashing search is weaker than NIM embeddings |
| Weather answers say `campus clock pinned` | demos pin the campus date to 2026-10-06; a live forecast only covers the real week | expected: the recorded forecast is replayed and re-dated; unset `app.today` for live forecasts |
| A decision falls back to the stub for one turn | the decision API refused the request (for example HTTP 403 on SQL-shaped text) | the turn continues with the stub decider; the trace records the error |
| `No pending action in this thread` on Confirm | the pending write belongs to another thread, or it was already resolved | confirm in the same thread; `cli chat` shows the thread ID |
| The UI is not reachable from another machine | the app binds to 127.0.0.1 by design | run it where the browser runs; `--share` creates a public link only when passed explicitly |
| `language check failed` on commit | a banned audience word or pronoun in a tracked file (docs/implementation-plan.md §3) | rephrase in the impersonal register; `scripts/check_language.py FILE` checks one file |
| `secret scan failed` on commit | a key-shaped string in a tracked file | remove it and rotate the key (docs/setup_keys.md) |
| An answer misses a fact that is in the document | the chunk holding it did not reach the model, or it reached it without context | `cli ask "..." -v --show-chunks` lists every retrieved chunk with its lexical, dense, and reranker scores and marks the ones sent to the model; `cli ingest --show chunk --doc ID` shows how the document was split |
| Table numbers come back under the wrong column | an older knowledge base split tables mid-row | re-run `cli ingest`: the chunk recipe changed, so every document is re-chunked with the header in each table piece |
| `nim reranker unavailable (HTTP 410)` in the notes | the reranker model reached end of life | set `NIM_RERANK_MODEL` to a listed model, or `--set rag.reranker=laya` / `local`; retrieval continues with the local heuristic |
| Scanned PDF adds no chunks | the PDF has no text layer; OCR is out of scope | the extract stage flags empty pages; use a PDF with text or a Markdown version |
