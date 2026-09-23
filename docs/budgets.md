# Budgets and targets: measured

Checked against docs/implementation-plan.md §11 on 23 Sep 2026 from the build machine (Phnom Penh), `full`
mode: Jev `jev-1.13.0`, NIM embeddings, chat through Google AI Studio (NIM chat requests were timing out that
day, see docs/verify-at-build.md), live public APIs with the campus clock pinned for demo dates.
Re-measure with `python -m campus_copilot.cli trace-report` after `cli demo` or `cli eval`.

| Item | Target | Measured | Verdict |
|---|---|---|---|
| Jev requests per turn | 1 (guard + route + arguments) + 1 parallel passage batch (RAG only) + at most 1 answer check | exactly that: 1 turn request; 4 passage requests in parallel (about 0.4 s for the batch); 1 answer-check batch; 2.4 Jev requests per turn on average over a mixed session | met |
| End-to-end turn, single tool, `full` mode | p50 ≤ 4 s | p50 0.44 s over 6 single-tool turns (0.30-1.36 s); the single-tool path makes no chat-model call | met |
| RAG turn with a live chat model | (not budgeted separately) | 70-100 s, almost all in the Gemma 4 call on the AI Studio free tier (Jev share about 1.1 s) | provider-bound; offline and cached runs are unaffected |
| Reranking (added in 1.1.0) | not budgeted | NIM `llama-nemotron-rerank-vl-1b-v2`: about 0.6 s for 20 candidates, one request per RAG turn; the passage filter then asks Jev about the top 5 (was 4) | adds about 0.6 s to a RAG turn |
| Agent loop | ≤ 4 tool calls; hard stop on repeats | `agent.max_tool_calls = 4`; repeat detector tested (`tests/test_graph.py`) | met |
| Follow-up rewrite | ≤ 1 small-model call, only when `follow_up` fires; p50 ≤ 0.8 s added | 1 call, gated by the Noul; 10.8 s with `gemma-4-26b-a4b-it` on AI Studio | call count met; latency missed on this provider |
| Model window | ≤ 2,000 history tokens per call | `memory.max_tokens = 2000` with `trim_messages`; tested | met |
| Full ingest of the pack, `nim` mode | ≤ 2 min, batched | about 1 min (117 chunks, 8 batches) | met |
| Re-ingest with no changes | 0 embedding calls | 0 calls, 117 cache hits | met |
| Jev cost per seat | ≈ 0.05 USD per seat (200 turns); ≈ 2 USD per 40-seat cohort | 3,771 tokens per turn → 0.00012 USD per turn → 0.023 USD per seat, 0.92 USD per cohort; 9.22 USD per cohort at 10x | met; assumptions: 200 turns per seat, 40 seats, Jev price 0.042 USD per million input tokens, output free |
| NIM | within about 40 requests per minute per key | client-side limiter at 35 per minute for embeddings; chat calls are few per turn | met by design (not load-tested) |
| Offline mode | all 14 demo turns run; UI shows STUB badges | 14/14 at step 12; STUB badge in the Decisions panel and in replies | met |

Chat-model prices on the AI Studio free tier and on NIM are not published per token for this use, so the
trace report counts those calls as `unknown` instead of estimating them.
