# Inbox

Drop folder for new PDF and Markdown documents. Contents are git-ignored.
Run `python -m campus_copilot.cli ingest` after adding a document.

The knowledge base the pack ships with is CamTech's own material in `data/sources/`
(`CamTech-Prospectus.pdf`, `Academic_Info.md`). A document dropped here is ingested next to
those; to make it part of the committed pack, move it to `data/sources/` and add a row to
`data/sources/manifest.csv` and questions for it to `data/sources/probes.jsonl`.
