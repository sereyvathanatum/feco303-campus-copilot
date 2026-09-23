# Jev primer

Jev is TypeSafe's System One decision model: it answers closed questions about a piece of state with typed
answers and probabilities, and never generates free text. The copilot calls it over plain HTTP.

## The reference call

<!-- language-check: off -->
```bash
curl -X POST https://api.typesafe.ai/v1/systemone   -H "Authorization: Bearer $TYPESAFE_API_KEY"   -H "Content-Type: application/json"   -d @data/fixtures/jev_smoke_request.json
```

Request body (`data/fixtures/jev_smoke_request.json`):

```json
{
  "state": "Hi, I've been trying to connect my Stripe account for 3 days and the integration keeps failing. I'm losing sales. Please help ASAP.",
  "model": "jev-latest",
  "questions": {
    "urgency": {
      "type": "noul",
      "instructions": "Does this message express urgency?"
    }
  }
}
```
<!-- language-check: on -->

On any platform, including Windows PowerShell: `python -m campus_copilot.cli jev-smoke` sends the same
body and prints the Noul, the returned `model`, `usage`, and latency.

## Response shape

Recorded from a live call (`jev-1.13.0`, 23 Sep 2026; `data/fixtures/jev_response_shape.json`):

```json
{
  "model": "jev-1.13.0",
  "usage": {
    "input_tokens": 648,
    "output_tokens": 196
  },
  "answers": {
    "urgent": {
      "type": "noul",
      "noul": 0.41
    },
    "dept": {
      "type": "choice",
      "choice": "billing",
      "confidence": 1.0,
      "probabilities": {
        "billing": 1.0,
        "technical": 0.0,
        "delivery": 0.0
      }
    },
    "frust": {
      "type": "score",
      "score": 0.54,
      "confidence": 0.31,
      "legend": {
        "0": "Calm, neutral or happy",
        "1": "Mildly annoyed or disappointed",
        "2": "Very angry or furious"
      },
      "probabilities": {
        "0": 0.46,
        "1": 0.54,
        "2": 0.0
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
- **Passage questions** (`relevant`, `has_answer`, `injection`, `contradicts`): one request per retrieved chunk,
  in parallel.
- **Answer check**: `claim_support` per answer sentence against its cited passage.
- **Risk gate**: `explicit`, `own_account`, and `impact` before any write.
- **Notice fields**: `<field>_supported` per extracted event field.

Question IDs carry no meaning to the model, so the instructions state the full question. For Khmer messages
the questions stay in English.

## Offline and replay

Without a key, `decisions/stub.py` answers the same questions in the same shape (labelled `STUB`).
`COPILOT_JEV_REPLAY=replay` reads responses recorded in `data/fixtures/jev/`, keyed on a hash of the request
body; `scripts/record_fixtures.py --jev` records them.

## Limits and prices (checked 23 Sep 2026)

64K tokens per request (32K for `state` plus the longest question); a Choice has at most 255 options; a Score
has 2-10 levels. Input costs 0.042 USD per million tokens; output tokens are free. The per-turn request in
this repository uses about 1,960 input tokens and answers in about 0.3-0.6 s from Phnom Penh.
