# UI checklist

Manual checks for `python -m campus_copilot.cli ui` (docs/implementation-plan.md §8.12, phase P7).
Automated coverage lives in `tests/test_ui.py`; this list covers what only a browser shows.

Start: `python -m campus_copilot.cli --profile offline ui` and open http://127.0.0.1:7860.

| # | Check | Expected | Result (23 Sep 2026, offline profile) |
|---|---|---|---|
| 1 | Server address | listens on 127.0.0.1 only; no share link unless `--share` | 127.0.0.1:7861 only (netstat); HTTP 200 |
| 2 | Header | step label, profile, run mode, chat provider chain | shown |
| 3 | Demo turn 1 | cited answer `[academic-info § IV. Tuition Fees › ...]`; Decisions tab shows bars and a `STUB` badge | covered by `test_chat_turn_fills_every_panel` |
| 4 | Demo turns 1-14 in order | the same results as `cli demo` (13/14 before the vision step is built) | via the shared `Copilot`; `send` driven over HTTP with `gradio_client` |
| 5 | Sources tab | chunks with `source_id` and page, scores, judge verdicts; original and rewritten query on turn 2 | shown |
| 6 | Tools tab | calls, arguments, results, attribution | shown |
| 7 | Trace tab | node timeline with milliseconds and tokens | shown |
| 8 | Memory tab | thread state, slots, and the trimmed model window | shown |
| 9 | Pending write (turn 9) | Confirm and Cancel buttons appear; Cancel replies "Cancelled. Nothing was changed." | covered by `test_confirm_and_cancel_buttons_follow_a_pending_write` |
| 10 | New thread | chat clears; the next follow-up has no history | shown |
| 11 | Profile dropdown | switching to `steps/step-05` changes the header and the behaviour | shown |
| 12 | Knowledge Base: add document | a PDF or Markdown file lands in `data/inbox/`; unknown licence is flagged | handler tested |
| 13 | Knowledge Base: run and inspect | stage table fills; document view shows extracted text, removals, chunks | covered by `test_retrieval_lab_and_knowledge_base_views` |
| 14 | Retrieval Lab | modes × stores side by side, overlap table, Markdown evidence with a copy button | covered by the same test |
| 15 | Footer | demo banner visible | shown |
