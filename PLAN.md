# New repo: journalist-safety-monitor-ccnews (Common Crawl News source)

## Update 2026-08-26 (9): domain list expanded 96 -> 205 by mining Roy's GDELT data

Compared this repo against `RoyKrovel/journalist-safety-monitor` (the
GDELT-based sibling, cloned read-only at `../Roy/journalist-safety-monitor`
-- already existed from an earlier session, just needed a `git fetch` +
`git merge origin/main` since `git pull` hit an unrelated ref-resolution
quirk there). Findings from that comparison (10/12 of Roy's "validated"
incidents hold up under our current validator; 2/12 are exactly the
retrospective-headline false positives we already fixed; several real
non-English incidents sit unrecognized in Roy's `candidate` bucket since
Roy's validator has no language support) are recorded in the conversation,
not repeated here -- what matters for this repo is the follow-up action.

Re-ran Roy's entire dataset through our current `validate_incident()`:
64,038 "legacy" rows (title-only, no body text -- these predate Roy's
validator existing at all) plus 343 recent `candidate` rows (title +
evidence_text). ~3 minutes runtime. 944 would now validate (936 + 8).
Recall is necessarily lower than our own CC-NEWS pipeline's here, since
GDELT's article-list API doesn't return full body text the way our
collectors do -- title-only matching misses positive frames that need a
full sentence. Still a large, useful discovery signal.

Extracted the domains behind those 944, filtered to ones appearing >=2
times (595 -> 164; a single hit is usually one wire story syndicated
across many mirrors, not a reliably valuable recurring source -- e.g. a
single "CBS news crew attacked" AP story appeared under dozens of
US-local-affiliate domains, each once), and ran them through
`scripts/discover_sources.py`. 113 came back classified (82 ccnews, 33
rss; 2 excluded as pure content aggregators with no original reporting --
`article.wn.com`, `bignewsnetwork.com`); the other 49 uncovered (CCBot-
blocked, no feed) weren't recorded in `uncovered_domains` this round --
lower value than the 2026-08-25 round's uncovered list since most are
one-off US local-TV-affiliate domains, not worth the config bloat.

Merging in generated four exact RSS duplicates -- same domain modulo a
`www.` prefix, same `feed_url`, which would have made `RSSCollector` poll
the identical feed twice under two labels every run (`thehindu.com`,
`rappler.com`, `independent.co.uk`, `ansa.it`) -- removed the redundant
copy of each. Left the `www.`/bare pairs where the entries are `ccnews`
(hostname-exact-match filtering, so both forms just maximize real-URL
catch rate with no downside) or where the feed URLs actually differ
(`theguardian.com`'s new entry turned out to be the *Europe* edition feed,
not a duplicate of the existing World edition one -- kept both, labeled).

Result: **96 -> 205 sources, 21 -> 37 countries**. The 16 new countries
(Argentina, Bulgaria, Canada, Chile, Colombia, Cuba, Israel, Kenya,
Malaysia, Nigeria, New Zealand, Peru, Portugal, Senegal, Kosovo, South
Africa) weren't part of the original curated priority list -- they only
have sources because GDELT independently found real incidents there.
Added a `priority_countries.additional` tier documenting this (that field
isn't read by any code -- confirmed via grep -- so, like the existing
tiers, it's purely informational).

Deliberately did NOT insert Roy's 944 re-validated incidents into this
repo's own `data/incidents.db`: they're GDELT-sourced, not CC-NEWS/RSS-
sourced, and mixing origins into one database would undermine the ability
to compare the two repos' output later, which was the whole point of
pulling Roy's repo in. The re-validation was purely a discovery tool for
new domains, not a data-merge operation.

## Update 2026-08-26 (8): backfill stopped, Actions resumed -- back to steady state

Deliberately stopped the historical backfill (SIGINT both times, clean
flush verified) rather than run it to completion of the full 90-day
window: 374 WARC files processed, covering 2026-05-27 through 2026-06-28,
172 validated incidents. Judged a solid initial historical baseline rather
than something that had to finish in one go -- it's resumable
(`data/ccnews_backfill_state.json`) whenever picking the remaining ~55
days back up makes sense.

Worth recording what the backfill actually proved, beyond just adding
rows: of the 172 incidents, 75 are in a non-English language an
English-only validator would have missed entirely -- 33 Turkish, 29
Spanish, 8 Russian, 5 Italian (97 English). That's direct, real-data
confirmation that the 2026-08-25 multi-language validator work was worth
doing, not just theoretically sound.

Re-enabled the GitHub Actions `schedule:` trigger (paused earlier today to
avoid racing a scheduled push against the local backfill run). Reports/
exports regenerated and pushed. Project is now back to steady state:
Actions running on its normal 4x/day schedule, LFS handling
`data/incidents.db`, 96 sources across 21 countries, 6 supported
languages (English, Spanish, Portuguese, Italian, French, Russian,
Turkish), `candidate` status reserved for genuinely ambiguous cases.

Natural next steps whenever picked back up: resume the backfill further
back, add Arabic/Farsi language support (the biggest remaining
unsupported-language gap given the source list's Iran/Arab-world
coverage), or expand the domain list further.

## Update 2026-08-26 (7): two candidate-bucket fixes -- 65k rows reclassified

Reviewing the actual `article_candidates` reason breakdown (prompted by
"why are these candidates, what are the criteria") turned up two branches
in `validate_incident()` that were producing "candidate" for reasons that
don't actually apply to this repo:

**`matched_query` fallback (35,412 rows, the single largest bucket).** This
validator was originally shared with the GDELT-based sibling repo, where
`matched_query` meant "this article's *title/snippet* matched a keyword
search, but we don't have the full article text to confirm it" -- a real
source of uncertainty, since GDELT never returns full article bodies. This
repo always validates full extracted article text, and both collectors set
`matched_query` to a constant per-domain label (`"ccnews:bianet.org"`,
`"historical_backfill"`), never an actual search match -- so it carried no
signal, and "nothing found anywhere in the full text" is a confident
rejection, not genuine ambiguity. Removed the `matched_query` parameter
from `validate_incident()` entirely (and the leftover `query` field from
test fixtures/parametrization) rather than leave a dead parameter around.

**Unsupported-language cap (21,730 rows).** Previously capped at
"candidate" so a human could review non-English articles the validator
couldn't confirm. Per user decision: reject these instead for now (fewer
false "needs review" rows to sift through) and revisit as more languages
get term-list support (see the 2026-08-25 Turkish/es/pt/it/fr/ru entries
above) -- Arabic and Farsi are the two biggest remaining gaps given the
57-source list's exile/state-media coverage of Iran and the Arab world.

Existing `article_candidates` rows were reclassified (UPDATE, not DELETE --
this keeps the audit trail of what was actually seen and scanned) from
`candidate` to `rejected` with the reason text the current code would now
produce: 35,412 rows moved from "query-only match..." to "no media subject
or harm action found", 21,730 from "non-English returned text lacks
English validation evidence" to "unsupported language; no term list to
validate against yet". `candidate` dropped from ~65k to 8,297 -- now only
the two branches that represent genuine ambiguity (retrospective/
historical framing, and "journalist term present but no clear harm
action"). Reports/exports regenerated from the cleaned database.

## Update 2026-08-25 (6): historical backfill script (phase 8)

Built `scripts/backfill_ccnews.py`, the last item on the original phased
build plan. Replays historical CC-NEWS WARC files through the *current*
`CCNewsCollector` + `validate_incident()` (so it benefits from all of this
session's work: the 96-source allowlist, language detection, and the
6-language validator dispatch) and backfills the database, rather than
re-querying anything live. RSS feeds have no historical archive (only
recent entries), so this only covers `source: ccnews` domains.

Two of `CCNewsCollector`'s methods (`_fetch_warc_paths`, `_scan_file`) were
promoted from private to public (`fetch_warc_paths`, `scan_file`) since
they're now genuinely called by two things -- the live scheduled collector
and this script -- rather than duplicating WARC-streaming/extraction logic
a second time and risking the two drifting apart.

Runs locally per the user's standing instruction (not via GitHub Actions):
CC-NEWS ships ~16 WARC files/day at roughly a minute each to stream+scan,
so the agreed 3-month backfill window (~1,440 files) is realistically a
day-scale job -- well past what a scheduled Actions job should attempt, and
past what fits in one sitting anyway. Built resumable from the start: a
`--state` file (`data/ccnews_backfill_state.json`, tracked in git like the
live pipeline's `data/ccnews_state.json`) records every WARC file already
scanned, so an interrupted run can be restarted and picks up where it left
off. WARC filenames embed their crawl timestamp
(`CC-NEWS-20260801193946-00321.warc.gz`), so date-range filtering happens
against the path list itself, without downloading files outside the
requested window.

Also implemented actual retry-with-backoff for WARC streaming, using
`ccnews_collection.max_retries`/`retry_backoff_seconds` from config --
these were declared but silently never read by any code (the live
collector just skips a failed file and tries again next scheduled run,
which is fine for a recurring job but not for a run meant to complete an
entire historical range unattended).

Verified end-to-end against real data before considering it done, not just
unit-tested: a dry run correctly narrowed a month's 412 WARC files down to
15 in a 2-day test range, a second dry run against the same `--state` file
correctly skipped the already-scanned files and moved to the next ones
(proving resumability), and a real (non-dry-run) run against a throwaway
database inserted 2 new validated incidents with correct evidence text
(an IR journalist detention, an IR cameraman wounded) -- confirming the
whole path from historical WARC bytes to a validated database row works.

Not yet run for real: the actual 3-month backfill is a deliberate,
user-initiated long-running local job, not something to kick off
automatically.

## Update 2026-08-25 (5): domain list expanded 57 -> 96 sources

The 2026-08-24 expansion left several countries thin -- averaging 2.7
sources/country, with Saudi Arabia and Italy down to a single outlet each
and Somalia to two -- thin enough that most real incidents in those
countries wouldn't be caught by any watched source regardless of validator
quality. Researched a second, larger candidate batch
(`scripts/candidate_domains.txt`, appended -- 46 new domains, same
diversity criteria as round 1: state media alongside independent/exile
media where the press is restricted) and ran it through
`scripts/discover_sources.py`. 38 of 46 came back usable; 8 uncovered
(CCBot-blocked with no working feed: `sinembargo.mx`, `samaa.tv`,
`nation.com.pk`, `verafiles.org`, `caixinglobal.com`, `mediapart.fr`,
`lefigaro.fr`, `elconfidencial.com` -- added to `uncovered_domains`).

New per-country counts: every country now has at least 3 sources (France,
the new minimum), most have 4-6. Saudi Arabia went 1 -> 4 (added Saudi
Gazette, the state Saudi Press Agency, and Asharq Al-Awsat), Italy 1 -> 4
(La Stampa, ANSA, Il Fatto Quotidiano), Somalia 2 -> 5. Total: 57 -> 96
sources (61 ccnews + 35 rss). Also re-verified the 6 originally-uncovered
domains from the 2026-08-24 round (NDTV, Anadolu/aa.com.tr, TASS, Al
Arabiya, DW, La Repubblica) that this session initially thought were
undocumented -- they were already correctly recorded in
`uncovered_domains`, just past where an earlier partial file read had
stopped; no actual gap, confirmed still uncovered on re-check.

Next: historical backfill script (phase 8), the last item on the original
phased build plan.

## Update 2026-08-25 (4): live pipeline check + Turkish language support

Re-ran the live GitHub Actions pipeline after the (3) language work below
and confirmed the dispatch is actually exercised on real traffic, not just
synthetic tests: querying `article_candidates` by language+status after the
run showed real `rejected` decisions for es (41), it (6), pt (5), ru (2) --
those only happen when the new term lists actually matched something and
correctly ruled it out, so the code paths are demonstrably live. 0
`validated` incidents fired for any language this run, English included --
not a red flag, just a small sample (one shard of one day's WARC files);
real killings/detentions are rare per few hundred articles.

That same query surfaced something the source list alone didn't show:
**Turkish was the second-largest language bucket in live traffic (320
articles -- more than Spanish and Russian combined)**, entirely from
`haberler.com`/`bianet.org`-style Turkish-language CC-NEWS sources, and it
had zero language support. Added it, following the same
`language_terms.py` pattern as (3) below -- with one real architectural
wrinkle: Turkish negates by fusing a suffix into the verb itself
(öldürüldü "was killed" -> öldürülmedi "was not killed"), not with a
preceding word like every other language handled so far, so the existing
`negation_prefixes` mechanism (a word before the action, within a small
window) can't express it at all. Added a second mechanism,
`negated_action_terms` -- literal fully-inflected negated verb forms,
matched directly -- that a language can use instead of or alongside
prefixes. Building it surfaced and fixed a real latent bug: a language
with neither mechanism set would silently compile `"|".join([])` -> `""`,
and `re.compile("")` matches every position in any string, which would
have made every sentence look "negated" and blocked all validation for
that language. Regression test added
(`test_build_negated_action_re_with_no_negation_config_never_matches`).

Turkish's core case -- passive-voice headlines like "Gazeteci öldürüldü"
(journalist was-killed), the dominant real-world Turkish news pattern --
is covered and tested (validated killing/detention, source-attribution
rejection, retrospective and negated-action candidates, all checked
directly before being written into the suite, same discipline as (3)).
But Turkish's agglutination goes further than the negation case: nouns and
verbs take productive case/tense/mood suffixes that a bare-word-list
approach doesn't cover reported speech ("gazetecilere" = "to journalists",
"öldürüldüğünü" = "that [he] was killed" -- both miss the plain
"gazeteci"/"öldürüldü" list entries the same way "asked" doesn't match a
list entry for "ask"). This is a distinct, real coverage gap from the
Arabic/Farsi one (that was prefixes on nouns; this is suffixes on both
nouns and verbs, and on verbs it's productive across many more
grammatical categories) -- worth a fuller pass (case-suffixed subject
forms, more verb-form coverage) if Turkish's false-negative rate looks
high in practice, not attempted here given the scope of this session.

Next: expand the domain/RSS candidate list (see the source-count table
below -- several countries, especially Saudi Arabia at 1 source and Italy
at 1, are thin), then the historical backfill script (phase 8).

## Update 2026-08-25 (3): per-language validator dispatch for es/pt/it/fr/ru

Step "3b" (language support) is now implemented, not just detected. New
`language_terms.py` holds a `LanguageTerms` dataclass (media subject terms,
action terms by incident type, source-attribution patterns, retrospective
patterns, negation prefixes) and a registry for Spanish, Portuguese,
Italian, French, and Russian -- the languages the 2026-08-24 expansion
actually put live sources in. `incident_validator.py` was refactored so
every helper function takes a `terms` argument instead of closing over
English module constants directly; `validate_incident()` looks up
`article["language"]` (now populated by `language_detect.py`) and dispatches
to the matching term set, falling back to the pre-existing English-only/
capped-at-candidate behavior for any language not in the registry
(Arabic and Farsi included -- still deliberately deferred, see below).

English's own behavior is unchanged: its term lists and the negation-regex
construction were generalized into the same `negation_prefixes`-based
builder every language now uses, and the full pre-existing English
regression suite still passes byte-for-byte. One existing fixture flipped
on purpose: a Spanish-tagged article ("Periodista asesinado en Mexico")
that used to be capped at "candidate" now validates as KILLING, which is
the entire point of this work -- updated with a comment explaining why.

Added 26 new regression cases (`tests/test_incident_validator.py`): a
validated killing, validated detention, source-attribution rejection,
retrospective candidate, and negated-action candidate for each of the 5
new languages, all checked directly against the code before being written
into the suite (not written speculatively). Plus one case confirming a
still-unsupported language (Arabic) stays capped at "candidate" exactly as
before the refactor.

Real translation gotchas hit and fixed along the way, worth remembering if
extending further: (1) Spanish's "a un año del asesinato" and Italian's
"anno dall'omicidio" use article contractions (de+el -> del, da+l' ->
dall') that a plain trailing `\b` after the preposition misses -- fixed by
allowing the contracted form explicitly (Spanish) or dropping the trailing
boundary since the contraction attaches directly (Italian). (2) These
languages negate with a particle directly before the verb (no/não/non,
French "pas" after the auxiliary in compound tenses, Russian "не") rather
than English's auxiliary+"not" -- the negation builder needed to accept
raw regex fragments per language, not a fixed English-shaped template.

Explicitly out of scope for this pass, still open: Arabic and Farsi (their
definite article attaches to the noun with no space, e.g. Arabic "الصحفي" =
"the journalist" as one token, so plain `\bterm\b` entries won't match --
needs prefixed word-form variants, not a copy of this pass); the optional
English-only "killing of a journalist" nominal-frame bonus pattern wasn't
translated (subject/action proximity matching already covers the core
cases). Translations are rule-based vocabulary, not reviewed by a native
speaker of each language -- worth revisiting if real traffic surfaces a
language whose false-positive/negative rate looks off.

Next: re-run the live pipeline to confirm the now-validating non-English
sources actually produce validated/CRITICAL alerts end-to-end, then move to
the historical backfill script (phase 8), run locally per the user's
earlier instruction (not via GitHub Actions, to avoid run-time limits).

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
