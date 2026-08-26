# Journalist Safety Monitor (Common Crawl News)

Monitors journalist-safety incidents (killings, detentions, attacks, threats,
censorship) using [Common Crawl News (CC-NEWS)](https://commoncrawl.org/) and
RSS feeds as sources, instead of the GDELT-based approach used in the sibling
[journalist-safety-monitor](https://github.com/nunocalaim/journalist-safety-monitor)
repo.

See [PLAN.md](PLAN.md) for the full design history, the CC-NEWS data
investigation that informed it, and a dated log of every major decision.

## Key difference from the GDELT version

CC-NEWS has no keyword or domain search API — every WARC file has to be
downloaded and scanned. This repo streams and filters CC-NEWS WARC files by a
curated domain allowlist (`config.yaml`'s `ccnews_domains`), extracts article
text from the raw HTML with `trafilatura`, detects its language, and validates
it with `incident_validator.py` — a rule-based validator supporting English,
Spanish, Portuguese, Italian, French, Russian, and Turkish. A second collector
(`rss_collector.py`) polls RSS feeds for outlets that block CCBot but publish
a public feed.

## Status

Live: a GitHub Actions workflow (`.github/workflows/monitor.yml`) runs the
pipeline on a schedule, shards WARC files across runs, and commits results
(`data/incidents.db`, `data/exports/`, `reports/`) back to the repo
automatically. 96 sources across 21 priority countries.

## Where the results are

- **`data/incidents.db`** — the source of truth. SQLite database with two
  tables: `incidents` (validated incidents) and `article_candidates`
  (everything the validator examined but didn't confirm — kept so
  false-negative rate can be reviewed).
- **`data/exports/incidents_full.csv`** and `incidents_{10d,30d,180d}.csv` —
  validated incidents as flat CSV, full history plus rolling windows. Only
  written once there's at least one validated incident to export.
- **`data/exports/candidates_full.csv`** / `candidates_10d.csv` — borderline
  articles for reviewing validator recall, not the headline results.
- **`reports/report_YYYY-MM-DD.md`** — one human-readable summary per day the
  pipeline ran.

## Running it locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# One collection + validation pass, writes to data/incidents.db and
# regenerates reports/exports:
python3 journalist_safety_monitor.py

# Preview without writing anything:
python3 journalist_safety_monitor.py --dry-run --max-articles 200
```

### Historical backfill

`scripts/backfill_ccnews.py` replays historical CC-NEWS WARC files through
the *current* collector + validator, rather than re-querying anything live —
useful after language/validator/domain-list improvements, to pick up
incidents the pipeline would have missed before those changes landed. RSS has
no historical archive, so this only covers `source: ccnews` domains.

Meant to run locally, not via GitHub Actions — a multi-month backfill is an
hours-to-a-day-scale job. It's resumable (safe to interrupt and rerun) and
retries transient network failures automatically:

```bash
# Preview first, no writes:
python3 scripts/backfill_ccnews.py --days-back 90 --dry-run --max-files 3

# The real run, in the background so it survives closing the terminal:
nohup python3 scripts/backfill_ccnews.py --days-back 90 > backfill.log 2>&1 &
tail -f backfill.log   # watch progress
```

Running it only updates your **local** `data/incidents.db` — nothing commits
or pushes automatically (that's the point of not using Actions for this).
Once a run finishes, push the result yourself so it becomes part of the
shared dataset:

```bash
git add data/incidents.db data/ccnews_backfill_state.json
git commit -m "Backfill historical CC-NEWS incidents"
git push
```

### Adding new sources

`scripts/discover_sources.py` classifies candidate domains — checks for a
CCBot block in `robots.txt`, auto-discovers an RSS/Atom feed, and validates it
parses — then prints `config.yaml`-ready entries:

```bash
python3 scripts/discover_sources.py www.example.com:MX
python3 scripts/discover_sources.py --input scripts/candidate_domains.txt
```

## Tests

```bash
python3 -m pytest tests/ -v
```
