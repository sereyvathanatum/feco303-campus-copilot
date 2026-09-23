"""E14: per-image field accuracy of the notice reader against `data/images/manifest.json`.

For each synthetic image the reader's fields are compared with the ground truth,
and the fields the decision model flagged are listed next to the failure type.
"""

from __future__ import annotations

import json

from .. import config

IMAGES = config.DATA_DIR / "images"
FIELDS = ["title", "date", "start", "end", "location"]


def run_vision_eval(rt) -> list[dict]:
    from ..multimodal.notice_reader import normalize_event, read_notice

    manifest = json.loads((IMAGES / "manifest.json").read_text(encoding="utf-8"))
    rows = []
    for name, entry in manifest.items():
        reading = read_notice(rt, str(IMAGES / name))
        reply = reading.pop("_reply", None)
        truth = normalize_event(entry["truth"]["event"], rt.today)
        raw = {k: v for k, v in reading["event"].items()}
        correct = {f: (raw.get(f) or None) == (truth.get(f) or None) for f in FIELDS if truth.get(f)}
        wrong_kept = [f for f in FIELDS if truth.get(f) and raw.get(f) and raw[f] != truth[f]]
        rows.append({"image": name, "variant": entry.get("variant"), "failure": entry.get("failure", ""),
                     "field_accuracy": round(sum(correct.values()) / max(1, len(correct)), 2),
                     "flagged": reading["flagged"], "wrong_and_unflagged": wrong_kept,
                     "model": f"{reply.provider}:{reply.model}" if reply else "-", "stub": reading.get("stub")})
    return rows


def render(rows: list[dict]) -> str:
    lines = ["| image | variant | field accuracy | flagged by the decision model | wrong and not flagged | failure type |",
             "|---|---|---:|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['image']} | {r['variant']} | {r['field_accuracy']:.0%} | {', '.join(r['flagged']) or '-'} | "
                     f"{', '.join(r['wrong_and_unflagged']) or '-'} | {r['failure'] or '-'} |")
    return "\n".join(lines)
