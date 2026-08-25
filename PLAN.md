# New repo: journalist-safety-monitor-ccnews (Common Crawl News source)

## Update 2026-08-25 (2): source list expanded, language detection wired in

Domain/RSS list expansion (step "3a" of the post-launch strategy) is done:
`scripts/discover_sources.py` classifies a candidate domain (CCBot block via
robots.txt, RSS/Atom auto-discovery, feed-parse validation), and running it
against a diversity-curated candidate list (`scripts/candidate_domains.txt`
-- state media alongside independent/exile media for restricted-press
countries) grew the allowlist from 17 to 57 sources (34 ccnews + 23 rss),
now covering all 21 priority countries. 10 domains remain structurally
uncovered (CCBot-blocked, no discoverable feed) and are tracked in
`config.yaml`'s `uncovered_domains` list.

That expansion made language support (step "3b") urgent: `incident_validator.py`
caps any non-English article at `candidate` status via `_is_non_english()`,
and its positive-frame matcher is English-word-only, so non-English articles
can never validate today -- now confirmed to affect several of the 57 live
sources (Spanish, Russian, Portuguese, Italian, French, Arabic, Farsi).

First step done: article language now gets detected and stored, via a new
`language_detect.py` (backed by `py3langid`) called from both collectors.
This was not as simple as it looked -- trafilatura only populates its own
`language` field when you pass `target_language`, but that argument is a
*filter*: if the detected language doesn't match, `extract()` raises
internally and returns `None`, silently discarding the article. That would
have dropped every non-English article before it ever reached the
validator, so detection is done independently with `py3langid` instead
(no model download needed, unlike `langdetect`), right after extraction.
Verified 8/8 correct on realistic journalist-safety sentences across en/es/
ru/pt/ar/it/fr/fa; regression tests in `tests/test_language_detect.py`.

Not yet done: the actual per-language validator dispatch (translated term
lists for `MEDIA_SUBJECT_TERMS`/`ACTION_TERMS_BY_TYPE`/source-attribution/
retrospective/negation patterns, keyed by the now-populated `language`
field). Priority order agreed: Spanish, Portuguese, Russian, Italian,
French, then Arabic/Farsi (different scripts but still whitespace-delimited,
so the existing regex approach should work mechanically) -- Hindi/Chinese
deferred since current Indian/Chinese sources are English-language editions,
and true CJK tokenization (no whitespace word boundaries) is a bigger lift.
Historical backfill (phase 8) stays deferred until after this.

## Update 2026-08-25: pipeline built, verified live on GitHub Actions

Steps 1-7 of the phased build plan are done: `CCNewsCollector`,
`RSSCollector`, the orchestrator, and the scheduled workflow all exist and
have been verified against real data, including a live GitHub Actions run
(commit `fb24c1e`) -- checkout, deps, WARC streaming, all 10 RSS feeds,
validation, database, report, and commit-push-back all worked cleanly in
~4 minutes.

Two real validator false positives turned up running the actual pipeline
against real articles (not synthetic fixtures) and got fixed, with the
real cases kept as regression tests: (1) "X told reporters that Y was
killed" -- common in full article body text, missed by the
subject-first-only source-attribution regex; (2) no negation handling at
all -- "harassed and intimidated reporters, but did not harm them" matched
as a positive frame. Also fixed: "Year after X..."-style anniversary
framing without a number, which the numeric-only retrospective filter
missed.

One infra quirk found only on the Actions runner (not locally): El País
(`elpais.com`) returns 403 Forbidden on every full-article-page fetch from
GitHub's IP ranges, even though its robots.txt allows a generic agent.
`RSSCollector` already falls back to the feed summary text on a fetch
failure, so this degrades gracefully (thinner validation text for that one
domain) rather than breaking the run.

Remaining: Phase 8 (backfill script, replaying historical CC-NEWS WARC
files) -- lower priority, not yet started.

## Update 2026-08-24: hybrid CC-NEWS + RSS design

Purpose clarified: this repo is a **parallel, independent path to the GDELT
repo**, for eventual output comparison — not required to match its coverage,
but should be as good a signal as reasonably achievable on its own.

While building the domain allowlist, I found CC-NEWS structurally excludes a
lot of exactly the outlets this project cares about most: **13 of 27
candidate domains (48%) block `CCBot` in `robots.txt`**, including Reuters,
AP, BBC, The Guardian, Der Spiegel, El País, The Hindu, Corriere della Sera,
La Jornada, and — worse for this specific project — Rappler (Maria Ressa's
outlet) and SyriaHR (a human-rights-incident monitoring org). No amount of
WARC sampling will ever find these; the block is structural. What CC-NEWS
*does* reliably contain skews toward non-news content (press-release wires,
commercial sites) plus a real but narrower set of accessible regional/
non-English news outlets (confirmed: `economictimes.indiatimes.com`,
`haberler.com`, `kommersant.ru`, `meduza.io`, `arabnews.com`, `irna.ir`,
`finanznachrichten.de`).

Checked whether the blocked outlets publish public RSS feeds instead (robots
disallow rules target `CCBot` specifically, not feed readers) —
**10 of the 13 blocked domains have working feeds**: BBC, The Guardian,
Rappler, Der Spiegel, El País, The Hindu, La Jornada, SyriaHR, Folha de
S.Paulo, Corriere della Sera. Only AP, Reuters, and Aristegui Noticias have no
usable public feed left (both wire services discontinued RSS years ago) —
permanent gaps, acceptable since wire content is republished broadly enough
that GDELT likely covers it regardless.

**Revised architecture: two collectors, one pipeline.** `CCNewsCollector`
(WARC-based) stays for the broad regional/long-tail signal CC-NEWS is
actually good at. A new `RSSCollector` (using `feedparser` — trivial to use,
gives title/link/summary/published-date directly, no HTML parsing required
for the basic case) covers the specific major outlets CC-NEWS can't reach.
Both normalize into the same article-dict shape and run through the same
`validate_incident` / `database.py` / reporting pipeline. For RSS-sourced
articles, fetch the full article page for richer validation text only where
that domain's `robots.txt` allows a generic (non-`CCBot`) user agent — true
for all of these except the wire services, which have no full-text access
under either approach and are excluded anyway.

## Context

The existing `journalist-safety-monitor` fork works by querying GDELT's DOC 2.0
API (a hosted, keyword-searchable index of global news) and running
`incident_validator.py` against the returned titles/snippets to decide
validated / candidate / rejected. The user wants a **new, separate repo** that
does the same kind of monitoring but sourced from **Common Crawl News
(CC-NEWS)** instead of GDELT — likely as an independent/complementary source,
not a replacement. This plan is investigation + design only; no code is
written yet.

I fetched real CC-NEWS data (index listings, a partial WARC file, the CDX
collection list) to ground this in facts rather than assumptions. The single
biggest finding: **CC-NEWS has no keyword or domain search API.** This
changes the shape of the ingestion layer significantly compared to GDELT, even
though the rest of the pipeline (validator, database, reporting, alerting)
carries over almost unchanged.

## What I verified hands-on

- **Format & cadence**: raw `.warc.gz` files at
  `https://data.commoncrawl.org/crawl-data/CC-NEWS/YYYY/MM/CC-NEWS-<timestamp>-<seq>.warc.gz`,
  published roughly every 2-3 hours (~16/day in August 2026), each **~1.07 GB
  compressed**. No auth, no AWS account needed — plain HTTPS via CloudFront.
- **No index exists for CC-NEWS.** I checked `index.commoncrawl.org/collinfo.json`
  (the CDX/columnar index Common Crawl advertises) — it only covers the
  quarterly `CC-MAIN-*` full-web crawls, not `CC-NEWS`. So there is no
  server-side way to ask "give me only finanznachrichten.de" or "give me only
  articles containing 'journalist'" — **every WARC file has to be downloaded
  and scanned in full**, regardless of whether you restrict to specific
  domains afterward. Domain-restriction is a filtering/curation choice made
  during processing, not a way to cut bandwidth. (I flagged this after the
  scan-scope question was answered — worth knowing before implementation
  starts.)
- **No WET/WAT (plain-text-extract) files for CC-NEWS** — I confirmed
  `wet.paths.gz` / `wat.paths.gz` both 404 for this collection, unlike the
  main crawl. Only raw WARC. So HTML → article-text extraction has to be done
  in-repo (Common Crawl's own text extraction isn't available here).
- **Record structure** (sampled from `CC-NEWS-20260824090656-00330.warc.gz`):
  `warcinfo` → per-URL `request`/`response` pairs. The `response` record is
  the raw HTTP response including full HTML — `<title>`, `<meta
  name="description">`, `og:description` etc. are present in the page head,
  same kind of fields the validator already uses, just embedded in HTML
  instead of handed to you as JSON.
- **Volume**: ~44 response records in a 2 MB compressed sample that
  decompressed to 9.8 MB — extrapolating, a full ~1.07 GB file holds roughly
  **20-25k article records**. At ~16 files/day that's on the order of
  **350-400k articles/day** crawled globally.
- **Source diversity**: the small sample alone had German, Russian, Italian,
  Lithuanian, Turkish, and Indian domains — confirms broad multilingual
  coverage, relevant since journalist-safety incidents cluster in non-English
  sources GDELT may under-cover.
- **History**: WARC files go back to 2016, so backfill/testing against known
  incidents is possible, same idea as the existing `scripts/backfill_validated_incidents.py`.
- **Legal**: Common Crawl data is AWS Open Data (no cost, no rate limit
  documented), but redistribution of scraped full text at scale should
  respect Common Crawl's Terms of Use — worth a read before deciding whether
  to store full article text or just extracted evidence snippets (the
  existing repo already only stores snippets/evidence_text, which sidesteps
  most of this).

## Decisions already made (from the earlier question)

- **Scope**: domain-restricted subset — process all WARC records but keep
  only ones from a curated allowlist of known news domains per priority
  country (same `priority_countries` structure the current `config.yaml`
  already has). Given the finding above, this doesn't reduce what you
  download, but it does reduce (a) what you validate/store, (b) false-positive
  surface from low-quality/unknown sites, and (c) legal/attribution exposure.
  It's a quality/curation choice, not a performance one — worth being
  explicit about in the new repo's README so a future contributor doesn't
  assume it saves bandwidth.
- **Compute**: GitHub Actions, same as today. At ~1 GB/file and a few files
  per scheduled run (sharded, mirroring the existing `--shard-count`/
  `--shard-index` pattern used for GDELT queries), streaming
  download-decompress-filter should comfortably fit in a single Actions job —
  no need to hold a full file in memory or on disk if processed as a stream.

## Recommended architecture

Mirror the existing repo's separation of concerns — most of it is already
source-agnostic and can move over close to as-is:

**Reused with little/no change:**
- `incident_validator.py` — the media-subject/harm-action/retrospective logic
  is text-in, decision-out; it doesn't care whether the text came from a
  GDELT title or a CC-NEWS article body. Worth extending later to use full
  article text (CC-NEWS gives you the whole page, not just a title/snippet),
  which should make validation *more* accurate than the GDELT version, not
  less — but that's a tuning step after the pipeline works, not a blocker.
- `database.py` — same `incidents` / `article_candidates` schema idea;
  maybe add a `source` column (`gdelt` vs `ccnews`) if the two are ever meant
  to share a database, otherwise unchanged.
- Reporting, alerting, data retention, CSV export (`generate_report`,
  `generate_alerts`, `apply_data_retention`, `export_data` in
  `journalist_safety_monitor.py`) — none of this touches the data source.
- The GitHub Actions workflow shape (scheduled + `workflow_dispatch`,
  shard-based run, commit-results-back pattern).

**New, CC-NEWS-specific:**
- A `CCNewsCollector` replacing `GDELTAPIWrapper` + `build_gdelt_queries`.
  Responsibilities: read `warc.paths.gz` for the target date, stream-download
  each assigned WARC file (sharded across files, not query terms — there are
  no query terms here), iterate WARC `response` records with `warcio`, keep
  only records whose URL host is in the configured domain allowlist.
- An HTML → article-text extraction step (e.g. `trafilatura` or
  `readability-lxml`) to turn the raw response HTML into title/description/
  body text before handing it to `validate_incident`.
- A domain allowlist config (new `config.yaml` section, analogous to
  `priority_countries`, mapping domains to country/language) instead of
  `gdelt_queries`.
- New dependencies: `warcio`, an HTML text extractor, plus whatever the
  existing repo already uses (`requests`, `pyyaml`, sqlite via stdlib).
- An `RSSCollector` (see the 2026-08-24 update above): polls a per-domain
  feed URL list with `feedparser`, normalizes entries into the same
  article-dict shape as the CC-NEWS/GDELT collectors, and optionally fetches
  the full article page (where robots.txt allows a generic agent) for richer
  validation text. New dependency: `feedparser`.

## Repo setup

Standalone new GitHub repo (not a fork), seeded from copies of the reusable
files above rather than a git fork of the GDELT repo — the two projects share
logic but not history, and being independent is safer than a fork/upstream
split you'd have to keep syncing (as we just untangled for the current repo).

## Phased build plan (for the future implementation session)

1. **Spike**: `CCNewsCollector` that streams one WARC file, filters to a
   handful of test domains, extracts text from ~5 articles — validate the
   parsing approach end-to-end before wiring anything else up.
2. **Validator integration**: feed extracted article text through
   `validate_incident` (copied as-is initially), compare decisions against a
   few known incidents to sanity-check. Done: confirmed via
   `spikes/spike_validator_on_fulltext.py` that the validator generalizes
   cleanly to full-length body text.
3. **Domain classification**: finalize the config.yaml domain list, tagging
   each entry `source: ccnews` or `source: rss` (+ feed URL) per the
   2026-08-24 update above.
4. **RSSCollector**: build the feedparser-based collector for the 10
   RSS-only domains, normalizing entries to the shared article-dict shape.
5. **Sharded collection loop + database + config** — port over
   `collect_incidents`/`database.py` patterns from the existing repo, calling
   both `CCNewsCollector` and `RSSCollector`.
6. **Reporting/alerting/retention** — copy over largely unchanged.
7. **GitHub Actions workflow** — scheduled + shard, mirroring the existing
   `monitor.yml`.
8. **Backfill script** — adapt `scripts/backfill_validated_incidents.py` to
   replay historical CC-NEWS WARC files instead of re-querying GDELT (RSS
   feeds have no historical archive, so backfill only applies to the CC-NEWS
   side).

## Verification approach

- Spike step (1) is itself the main risk-reduction test: if streaming +
  filtering + text extraction works cleanly on real data, the rest is largely
  known territory copied from a working repo.
- Reuse the existing repo's `tests/test_incident_validator.py` fixtures
  unchanged as a regression baseline once the validator is wired to
  CC-NEWS-extracted text, to confirm behavior didn't regress from the
  GDELT-snippet version.
- Dry-run the collector against a couple of historical WARC files with known
  incidents in them (using CC-NEWS's 2016+ archive) as an informal accuracy
  check before turning on the live schedule.
