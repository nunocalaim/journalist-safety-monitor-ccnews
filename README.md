# Journalist Safety Monitor (Common Crawl News)

Monitors journalist-safety incidents (killings, detentions, attacks, threats,
censorship) using [Common Crawl News (CC-NEWS)](https://commoncrawl.org/) as
the source, instead of the GDELT-based approach used in the sibling
[journalist-safety-monitor](https://github.com/nunocalaim/journalist-safety-monitor)
repo.

See [PLAN.md](PLAN.md) for the full design, the CC-NEWS data investigation
that informed it, and the phased build plan.

## Key difference from the GDELT version

CC-NEWS has no keyword or domain search API — every WARC file has to be
downloaded and scanned. This repo streams and filters CC-NEWS WARC files by a
curated domain allowlist, extracts article text from the raw HTML, then reuses
the same validation logic (`incident_validator.py`) as the GDELT-based repo.

## Status

Early build-out, following the phased plan in [PLAN.md](PLAN.md). Not yet
running on a schedule.
