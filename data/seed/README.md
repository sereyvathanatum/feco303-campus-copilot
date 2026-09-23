# Seed data

Synthetic CSV files, one per campus-database table. All people, rooms, books, and
bookings are invented; book titles carry "(demo record)". Public-holiday rows cover
fixed-date 2026 holidays only; lunar-calendar holidays are listed in
`docs/verify-at-build.md` for confirmation against the official list.

`python -m campus_copilot.cli seed` rebuilds `runs/campus.db` from these files and
prints a content hash, so two builds can be compared.
