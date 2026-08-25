#!/usr/bin/env python3
"""
Replays historical CC-NEWS WARC files through the current CCNewsCollector +
validate_incident() pipeline and backfills the database. See PLAN.md's
phased build plan, phase 8.

RSS feeds carry no historical archive (just recent entries), so this only
covers the "source: ccnews" domains in config.yaml, not RSS-only outlets.

Meant to run locally, not via GitHub Actions: CC-NEWS ships ~16 WARC files/
day and each takes roughly a minute to stream and scan, so a few months of
history is realistically an hours-to-a-day-scale local job, well past what
a scheduled Actions job should be doing. It's resumable -- interrupt it any
time and a re-run with the same --state file picks up where it left off,
skipping already-scanned WARC files -- so it doesn't need to finish in one
sitting.

Usage:
    python3 scripts/backfill_ccnews.py --days-back 90
    python3 scripts/backfill_ccnews.py --start-date 2026-05-25 --end-date 2026-08-25
    python3 scripts/backfill_ccnews.py --days-back 90 --dry-run --max-files 5
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ccnews_collector import CCNewsCollector, WARC_BASE_URL  # noqa: E402
from database import IncidentDatabase  # noqa: E402
from incident_validator import validate_incident  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

WARC_FILENAME_RE = re.compile(r"CC-NEWS-(\d{14})-\d+\.warc\.gz$")


def parse_warc_timestamp(path: str) -> Optional[datetime]:
    """WARC filenames embed their crawl timestamp, e.g.
    crawl-data/CC-NEWS/2026/08/CC-NEWS-20260801193946-00321.warc.gz --
    letting us filter to a date range without downloading every file in a
    month's index."""
    match = WARC_FILENAME_RE.search(path)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def months_between(start: datetime, end: datetime) -> List[Tuple[int, int]]:
    months = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return months


class BackfillState:
    """Tracks WARC file paths already scanned across (possibly many, given
    the multi-hour scope) runs, separate from the live pipeline's
    data/ccnews_state.json -- the two scan disjoint time windows in
    practice (this one reaches backward, the live shards scan the current
    month), so there's no benefit to sharing state and real risk in
    coupling a one-off backfill to the live scheduled pipeline's bookkeeping."""

    def __init__(self, path: Path):
        self.path = path
        self.processed = set(self._load())

    def _load(self) -> List[str]:
        if not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text()).get("processed_files", [])
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read %s, starting fresh", self.path)
            return []

    def is_processed(self, path: str) -> bool:
        return path in self.processed

    def mark_processed(self, path: str) -> None:
        self.processed.add(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"processed_files": sorted(self.processed)}, indent=2))


def scan_file_with_retries(collector: CCNewsCollector, warc_url: str, max_retries: int, backoff_seconds: int) -> List[Dict]:
    # config.yaml declares ccnews_collection.max_retries/retry_backoff_seconds,
    # but nothing implemented them (the live pipeline just skips a failed
    # file and tries again next scheduled run -- fine for a recurring job,
    # not for a run meant to finish an entire historical range). A transient
    # blip shouldn't lose progress on an otherwise-unattended multi-hour run.
    attempt = 0
    while True:
        try:
            return collector.scan_file(warc_url)
        except requests.RequestException as e:
            attempt += 1
            if attempt > max_retries:
                raise
            wait = backoff_seconds * attempt
            logger.warning("Stream failed (attempt %d/%d): %s -- retrying in %ds", attempt, max_retries, e, wait)
            time.sleep(wait)


def article_to_decision(article: Dict, validation, matched_source: str) -> Dict:
    return {
        "url": article.get("url", ""),
        "title": article.get("title", ""),
        "published_date": article.get("published_date", ""),
        "domain": article.get("domain", ""),
        "source_country": article.get("country", ""),
        "language": article.get("language", ""),
        "matched_query": matched_source,
        "validation_status": validation.status,
        "validation_reason": validation.reason,
        "evidence_text": validation.evidence_text,
    }


def article_to_incident(article: Dict, validation, matched_source: str) -> Dict:
    return {
        "url": article.get("url", ""),
        "title": article.get("title", ""),
        "date": article.get("published_date", ""),
        "domain": article.get("domain", ""),
        "country": article.get("country", ""),
        "severity": validation.severity,
        "incident_type": validation.incident_type,
        "description": validation.evidence_text or article.get("description", "")[:1000] or article.get("title", ""),
        "language": article.get("language", ""),
        "source_country": article.get("country", ""),
        "matched_query": matched_source,
        "validation_status": validation.status,
        "validation_reason": validation.reason,
        "evidence_text": validation.evidence_text,
    }


def print_summary(totals: Counter, reasons: Counter, new_incidents: int, duplicate_incidents: int, candidate_articles: int, files_scanned: int) -> None:
    print("\nBackfill summary")
    print("=" * 80)
    print(f"WARC files scanned: {files_scanned}")
    print(f"Articles processed: {sum(totals.values())}")
    print(f"Validated: {totals['validated']}")
    print(f"Candidates: {totals['candidate']}")
    print(f"Rejected: {totals['rejected']}")
    print(f"New incidents inserted: {new_incidents}")
    print(f"Duplicates skipped: {duplicate_incidents}")
    print(f"Candidate/rejected articles stored: {candidate_articles}")
    print("\nTop validation reasons:")
    for reason, count in reasons.most_common(10):
        print(f"- {count}: {reason}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start-date", help="YYYY-MM-DD, inclusive. Defaults to --days-back before --end-date.")
    parser.add_argument("--end-date", help="YYYY-MM-DD, inclusive. Defaults to today.")
    parser.add_argument("--days-back", type=int, default=90, help="Used when --start-date is not given (default: 90).")
    parser.add_argument("--db", default="data/incidents.db", help="SQLite database path to update.")
    parser.add_argument(
        "--state",
        default="data/ccnews_backfill_state.json",
        help="Tracks already-processed WARC files so a re-run resumes instead of rescanning.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate and count without writing to the database.")
    parser.add_argument("--max-files", type=int, default=None, help="Stop after this many new WARC files, useful for a quick preview.")
    parser.add_argument("--batch-size", type=int, default=200, help="Rows per database batch insert.")
    args = parser.parse_args()

    end_date = datetime.strptime(args.end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if args.end_date else datetime.now(timezone.utc)
    start_date = (
        datetime.strptime(args.start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if args.start_date
        else end_date - timedelta(days=args.days_back)
    )
    if start_date > end_date:
        parser.error("--start-date must be before --end-date")

    with open(ROOT / "config.yaml") as f:
        config = yaml.safe_load(f)
    collection_config = config.get("ccnews_collection", {})
    max_retries = collection_config.get("max_retries", 2)
    retry_backoff_seconds = collection_config.get("retry_backoff_seconds", 30)
    timeout = collection_config.get("request_timeout_seconds", 60)

    collector = CCNewsCollector(config, timeout=timeout)
    state = BackfillState(Path(args.state))
    db = None if args.dry_run else IncidentDatabase(args.db)

    totals: Counter = Counter()
    reasons: Counter = Counter()
    new_incidents = 0
    duplicate_incidents = 0
    candidate_articles = 0
    files_scanned = 0
    incident_batch: List[Dict] = []
    candidate_batch: List[Dict] = []

    def flush() -> None:
        nonlocal new_incidents, duplicate_incidents, candidate_articles, incident_batch, candidate_batch
        if db and incident_batch:
            n, d = db.bulk_insert_incidents(incident_batch)
            new_incidents += n
            duplicate_incidents += d
            incident_batch = []
        if db and candidate_batch:
            n, _ = db.bulk_insert_candidates(candidate_batch)
            candidate_articles += n
            candidate_batch = []

    logger.info("Backfilling CC-NEWS from %s to %s (state: %s)", start_date.date(), end_date.date(), args.state)

    try:
        for year, month in months_between(start_date, end_date):
            logger.info("Fetching WARC index for %04d-%02d", year, month)
            try:
                all_paths = collector.fetch_warc_paths(year, month)
            except requests.RequestException as e:
                logger.error("Could not fetch WARC index for %04d-%02d: %s", year, month, e)
                continue

            in_range = [p for p in all_paths if (ts := parse_warc_timestamp(p)) and start_date <= ts <= end_date]
            logger.info("%d of %d files in %04d-%02d fall in the requested range", len(in_range), len(all_paths), year, month)

            for path in in_range:
                if state.is_processed(path):
                    continue
                if args.max_files is not None and files_scanned >= args.max_files:
                    logger.info("Reached --max-files=%d, stopping", args.max_files)
                    flush()
                    print_summary(totals, reasons, new_incidents, duplicate_incidents, candidate_articles, files_scanned)
                    return 0

                warc_url = WARC_BASE_URL + path
                t0 = time.monotonic()
                try:
                    articles = scan_file_with_retries(collector, warc_url, max_retries, retry_backoff_seconds)
                except requests.RequestException as e:
                    logger.error("Giving up on %s after retries: %s", warc_url, e)
                    continue
                files_scanned += 1

                for article in articles:
                    matched_source = f"ccnews:{article.get('domain', '')}"
                    validation = validate_incident(article, matched_query="historical_backfill")
                    totals[validation.status] += 1
                    reasons[validation.reason] += 1

                    if validation.status == "validated":
                        incident_batch.append(article_to_incident(article, validation, matched_source))
                    else:
                        candidate_batch.append(article_to_decision(article, validation, matched_source))

                if len(incident_batch) >= args.batch_size or len(candidate_batch) >= args.batch_size:
                    flush()

                # Only record a file as done once its results are actually
                # in the database -- a --dry-run preview doesn't write
                # anything, so marking it processed here would make a
                # later real run silently skip it forever, losing whatever
                # it found.
                if db:
                    state.mark_processed(path)
                logger.info(
                    "[%d files done] %s: %d articles matched, %d validated so far (%.0fs)",
                    files_scanned, path, len(articles), totals["validated"], time.monotonic() - t0,
                )
    finally:
        flush()
        if db:
            db.close()

    print_summary(totals, reasons, new_incidents, duplicate_incidents, candidate_articles, files_scanned)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
