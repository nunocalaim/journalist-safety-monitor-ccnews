# Journalist Safety Monitor (Common Crawl News + GDELT)

Monitors journalist-safety incidents (killings, detentions, attacks, threats,
censorship) from three sources feeding the same validator and database:
[Common Crawl News (CC-NEWS)](https://commoncrawl.org/), RSS feeds, and
GDELT's keyword search. Started as a CC-NEWS-only parallel approach to the
GDELT-based [journalist-safety-monitor](https://github.com/nunocalaim/journalist-safety-monitor)
repo; as of 2026-09-01, GDELT is a third collector here too, so this repo
combines both approaches rather than just comparing them.

See [PLAN.md](PLAN.md) for the full design history and a dated log of every
major decision, including the comparison that led to combining the two.

## How the three sources differ

- **CC-NEWS** (`ccnews_collector.py`) has no keyword or domain search API —
  every WARC file has to be downloaded and scanned. Streams and filters WARC
  files by a curated domain allowlist (`config.yaml`'s `ccnews_domains`),
  extracts article text from the raw HTML with `trafilatura`.
- **RSS** (`rss_collector.py`) polls feeds for outlets that block CCBot in
  `robots.txt` but publish a public feed instead.
- **GDELT** (`gdelt_collector.py`) runs keyword/proximity queries against
  GDELT's DOC 2.0 API (public, no key needed) — broad reach across sources
  neither of the above track, but the API only ever returns a title, no body
  text, so this collector fetches each hit's full article page itself before
  validating (falling back to GDELT's title if that fetch fails).

All three feed into `incident_validator.py` — a rule-based validator
supporting English, Spanish, Portuguese, Italian, French, Russian, and
Turkish — and the same `data/incidents.db`.

## Status

Live: a GitHub Actions workflow (`.github/workflows/monitor.yml`) runs the
pipeline on a schedule, shards CC-NEWS WARC files and GDELT queries across
runs, and commits results (`data/incidents.db`, `data/exports/`, `reports/`)
back to the repo automatically. 306 CC-NEWS/RSS sources across 59 countries,
plus whatever GDELT's live search independently turns up.

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

### Merging in another repo's historical data

`scripts/merge_gdelt_backlog.py` re-validates another journalist-safety-monitor
instance's already-collected data (e.g. `RoyKrovel/journalist-safety-monitor`'s
GDELT backlog) against this repo's *current* validator and merges whatever
confirms into `data/incidents.db` — the committed version of the one-off
analysis described in PLAN.md's 2026-08-26 comparison update. Reads the other
repo's database directly and read-only; never writes to it.

```bash
# Preview first, no writes (defaults to ../Roy/journalist-safety-monitor):
python3 scripts/merge_gdelt_backlog.py --dry-run

# The real run:
python3 scripts/merge_gdelt_backlog.py

# Against a different source database:
python3 scripts/merge_gdelt_backlog.py --source-db /path/to/other/incidents.db
```

Only exact-URL duplicates are skipped automatically — near-duplicate stories
covering the same event from different URLs are not deduplicated. See the
script's own docstring and PLAN.md for why.

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
