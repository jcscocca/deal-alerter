# Durable state

Commit the generated JSON and JSONL files here, not SQLite files or previews.
Steam uses `steam/<country>/alerts.json` and `games.json`; hardware uses
`hardware/US/alerts.json`, `prices.jsonl`, and `manual.jsonl` for listings added
with `--add`. Separate country directories prevent one market's price from
becoming another market's alert baseline.

The hardware SQLite database lives in a private temporary directory for one run.
It is rebuilt from committed JSONL, including for read-only previews and statistics.
Only a real run exports observations back here.
