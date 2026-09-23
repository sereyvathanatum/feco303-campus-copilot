# verify@build findings

Items marked `verify@build` in `docs/implementation-plan.md`, as found when the
repository was built (September 2026, Windows, Python 3.14.6).

| Item | Plan assumption | Found at build | Effect |
|---|---|---|---|
| Python | 3.10 and 3.12 | only 3.14.6 on the build machine; CI covers 3.10 and 3.12 | code avoids syntax newer than 3.10 |
| `langchain-nvidia-ai-endpoints` | pin at build | `1.4.3` installs beside `langchain-core==1.6.3` | pinned |
| `langgraph-checkpoint-sqlite` | pin at build | `3.1.1` | pinned |
| `mcp` | v2 line, `MCPServer` class | latest release is `1.30.0`; the server class is `FastMCP` (`mcp.server.fastmcp`) | servers use `FastMCP`; a v2 upgrade renames one import |
| LangChain MCP adapter | `langchain.mcp.MCPAdapter` or `langchain-mcp-adapters` | `langchain-mcp-adapters==0.3.2` | client uses `MultiServerMCPClient` |
| `sqlite-vec` | pin at build | `0.1.9`; loads on CPython 3.14 for Windows | pinned |
| SQLite FTS5 | may be missing | present in CPython 3.14 for Windows | lexical search uses FTS5 |
| `gradio` | pin at build | `6.28.0` | pinned |
| `numpy` | pin | wheels differ per Python version | range `>=1.26,<3` keeps 3.10 installable |
| `google/gemma-4-31b-it` | chat, vision, tools on NIM | listed in `/v1/models`; on 23 Sep 2026 every chat request (streaming or not, both keys) timed out without response headers after 60-180 s | chat calls use a timeout and fall back to the stub model, labelled `STUB (NIM unavailable)`; re-test before a session |
| `nvidia/nemotron-nano-9b-v2` | small model | not listed in `/v1/models` | default small model changed to `nvidia/nemotron-3.5-lightning-30b-a3b` (listed; its chat requests also timed out on 23 Sep 2026) |
| `nvidia/nemotron-3-embed-1b` | asymmetric embedder, `truncate` parameter | works: 2048-dimensional vectors, `input_type` `passage`/`query`, `truncate=NONE` accepted, about 0.5-0.8 s per request | used as planned |
| embedder tokenizer | published tokenizer for chunk sizing | `nvidia/nemotron-3-embed-1b` has no public Hugging Face repository (401) | `tiktoken` `cl100k_base`, labelled `approximate`; a built-in approximate counter when `tiktoken` data is not cached |
| `nvidia/llama-nemotron-rerank-1b-v2` | reranker | retrieval endpoint returns HTTP 410 "end of life on 2026-08-25" | `dense+rerank` reports the reranker as unavailable and falls back to `dense`; E03 marks the column as skipped |
| Khmer text in the PDF | extraction limits | `pypdf` returns Khmer glyphs out of order with stray ASCII characters (page 20) | the extract stage flags the page; Markdown stays the source of truth for Khmer |
| NIM keys | one key covers every model | two keys supplied; `NVIDIA_NEMOTRON_API_KEY` (optional) is used for the Nemotron models and falls back to `NVIDIA_API_KEY` | config and `cli check` report both |
| Google AI Studio (added at build) | not in plan | `gemma-4-31b-it` and `gemma-4-26b-a4b-it` answer through the OpenAI-compatible endpoint `generativelanguage.googleapis.com/v1beta/openai` (about 16 s and 5.5 s for a short reply); thought text always arrives inline as `<thought>...</thought>`, and any thinking-budget setting returns HTTP 400; intermittent HTTP 503 "high demand" | `COPILOT_CHAT_PROVIDER=google` selects it; the client strips thought blocks and retries 429/5xx; NIM stays the fallback and the embedder |
| AI Studio latency (23 Sep 2026) | not in plan | grounded answers from `gemma-4-31b-it` took about 43 s each with 900-1,700 thought characters; a 512-token budget returned only thought text | Google calls use at least 4,096 max tokens and a 120 s timeout (`GOOGLE_TIMEOUT`); an empty reply falls through to `gemma-4-26b-a4b-it`, then NIM, then the stub |
| TypeSafe Jev | `POST /v1/systemone`, `jev-latest` resolves to `jev-1.13.0` | confirmed on 23 Sep 2026: reference call returns `urgency` 0.98, 302 input tokens, 530 ms; the per-turn request (18 questions) uses about 1,960 input tokens and answers in 300-560 ms from the build machine | per-turn cost is about 0.00008 USD at 0.042 USD per million input tokens |
| Jev on the demo turns | routing and argument accuracy | all 14 demo messages routed as planned; "Convert 50" routes to `currency` at 0.60 vs 0.39 `out_of_scope`; generic `missing_info` reads 0.79-0.95 on complete requests | `policy.missing_info` raised to 0.90 as a secondary signal; per-argument `not_stated` checks drive clarifies |
| Jev in the full graph (23 Sep 2026) | per-turn decisions drive the policy | three live-only issues found and fixed: (1) with history, 'cafeteria menu' split `handbook` 0.47 / `out_of_scope`, so routes with the same action now pool probability; (2) Jev reads 'Free room ...?' as write intent (`wants_change` 0.82-0.87), so a write intent with no earlier search runs the search; (3) the gate's `explicit` Noul was 0.16 for 'Book it.' without history and 0.92 with the last turns in its state | live-Jev demo run: 13/14 (turn 13 waits for the vision step) |
| Open-Meteo with a pinned clock | live forecast | the live forecast covers 7 days from the real date, so demo dates (2026-10-06/07) fall outside it | with the campus clock pinned, the forecast replays the recorded fixture (re-dated) and says so in `source` |
| Jev and SQL-shaped input (23 Sep 2026) | not in plan | a turn request whose `message` holds `'; DROP TABLE loans;--` returns HTTP 403 with an HTML page from the API's web firewall | the decision fails as data and the stub decider answers that turn; the SQL text never reaches SQLite either way (templates only) |
| Live adversarial run with Jev | controls hold in `full` mode | all 7 adversarial cases caught by their expected control (poisoned API case replays its fixture, since live Wikipedia text is clean) | E13 evidence |
| Gemma 4 vision through Google AI Studio | image input, structured output | base64 `image_url` parts work on the OpenAI-compatible endpoint; the clean poster and the Khmer-script poster (Khmer digits and month name) were both read correctly in about 47 s each | offline runs replay manifest readings that model typical failures (blur, rotation, Khmer, dense table) |
| Pillow text shaping | Khmer posters | Pillow on this build has no `raqm`; basic layout still rendered the Khmer lines legibly | noted in `data/images/manifest.json` |
