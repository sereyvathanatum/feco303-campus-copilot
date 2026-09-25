# Laya primer

Laya is ConvAI's open-weights System One decision model: it answers closed questions about a piece of state
with typed answers and probabilities, and never generates free text. It runs next to the copilot, either in
the same process or behind a local server; there is no hosted API and no key.

## The two ways to reach it

| `LAYA_MODE` | How it runs | Install |
|---|---|---|
| `local` (default) | the `laya` package loads a checkpoint in this process; `Router` picks `english`, `multilingual`, or `typed-decisions` per request | `pip install laya` |
| `http` | a `laya-serve` process answers `POST {LAYA_BASE_URL}/systemone` with the same body and answer shape | `pip install "laya[serve]"`, then `laya-serve` |
| `off` | nothing; `decisions/stub.py` answers instead | - |

Checkpoints download from Hugging Face (`convaiinnovations/laya`) on first use and are cached there.
`LAYA_DEVICE` picks the device (empty = auto); `LAYA_MODEL` pins a checkpoint, and `auto` lets the Router
choose by language.

## The reference call

`python -m campus_copilot.cli laya-smoke` sends the reference body on any platform, including Windows
PowerShell, and prints the Noul, the checkpoint that answered, the Router's reason, `usage`, and latency.

With `LAYA_MODE=http` and `laya-serve` running, the same body over plain HTTP:

<!-- language-check: off -->
```bash
curl -X POST http://127.0.0.1:8000/v1/systemone   -H "Content-Type: application/json"   -d @data/fixtures/laya_smoke_request.json
```

Request body (`data/fixtures/laya_smoke_request.json`):

```json
{
  "state": "Hi, my ID card stopped opening the library gate this morning and the exam in Room B-204 starts in 30 minutes. Please help ASAP.",
  "model": "auto",
  "questions": {
    "urgency": {
      "type": "noul",
      "instructions": "Does this message express urgency?"
    }
  }
}
```
<!-- language-check: on -->

A bearer header is sent only when `LAYA_API_KEY` is set, for a `laya-serve` started behind one.

## Response shape

Both modes are normalised to one stored shape (`decisions/laya.py`, `_payload`): the answers, the usage
counters, and which checkpoint answered and why. Replay files in `data/fixtures/laya/` hold exactly this,
and `data/fixtures/laya_response_shape.json` holds the example below, which the contract test in
`tests/test_decisions.py` replays through a fake `laya-serve`. It shows all three answer types at once:

```json
{
 "model": "laya/english",
 "routing": {
  "model": "english",
  "repo": "convaiinnovations/laya",
  "reason": "latin script, english tokens"
 },
 "usage": {
  "input_tokens": 302,
  "output_tokens": 0
 },
 "answers": {
  "urgency": {
   "type": "noul",
   "noul": 0.98
  },
  "dept": {
   "type": "choice",
   "choice": "facilities",
   "confidence": 0.87,
   "probabilities": {
    "facilities": 0.87,
    "registry": 0.1,
    "library": 0.03
   }
  },
  "frustration": {
   "type": "score",
   "score": 1.41,
   "confidence": 0.52,
   "legend": {
    "0": "Calm, neutral or happy",
    "1": "Mildly annoyed or disappointed",
    "2": "Very angry or furious"
   },
   "probabilities": {
    "0": 0.11,
    "1": 0.37,
    "2": 0.52
   }
  }
 }
}
```

## Answer types

| Type | Answer fields | Reading |
|---|---|---|
| `choice` | `choice`, `confidence`, `probabilities` | one option from a fixed set; a split such as 0.60 / 0.39 means low confidence |
| `noul` | `noul` (0-1) | a yes-or-no question; 0.5 means the model cannot tell, not "medium" |
| `score` | `score`, `confidence`, `probabilities`, `legend` | an ordered scale of 2-10 levels; `score` is the expected level |

## How the copilot uses it

- **One request per turn** for guard, route, and argument questions (`decisions/questions.py`, `turn_catalogue`).
  The request carries `message`, the last three turns as `history`, `session.account_id`, and any `image_text`.
- **Passage questions** (`relevant`, `has_answer`, `injection`, `contradicts`): one per retrieved chunk. In
  `local` mode the chunks that route to the same checkpoint share one batched forward pass; in `http` mode
  they go out in parallel (`laya.passage_workers`).
- **Answer check**: `claim_support` per answer sentence against its cited passage.
- **Risk gate**: `explicit`, `own_account`, and `impact` before any write.
- **Notice fields**: `<field>_supported` per extracted event field.

Question IDs carry no meaning to the model, so the instructions state the full question. For Khmer messages
the questions stay in English.

## Offline and replay

With `LAYA_MODE=off`, or with the `laya` package absent, `decisions/stub.py` answers the same questions in
the same shape (labelled `STUB`).
`COPILOT_LAYA_REPLAY=replay` reads responses recorded in `data/fixtures/laya/`, keyed on a hash of the request
body; `scripts/record_fixtures.py --laya` records them.

## Limits and cost

A Choice has at most 255 options; a Score has 2-10 levels. Each question is encoded as
`[CLS] instructions [SEP] options [SEP] state`, and the instructions plus options share the checkpoint's
`head_max_len` budget (192 tokens on the English checkpoint), which is why long option lists need
`laya.head_max_len` and `laya.max_len` raised in the profile (`decisions/laya.py`, `_apply_budget`).

Nothing is billed per token: the checkpoints run on local hardware, so the cost is memory and the time of a
forward pass, and the first call also pays for loading the checkpoint. Measured latency per turn is in
docs/budgets.md.
