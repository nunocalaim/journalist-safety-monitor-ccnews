#!/usr/bin/env python3
"""
Re-validates RoyKrovel/journalist-safety-monitor's historical backlog
(rows with validation_status 'legacy' or 'candidate' -- i.e. everything
that predates real validation, or that Roy's older validator couldn't
confirm) against this repo's *current* validate_incident(), and merges
whatever confirms into this repo's own database. See PLAN.md's 2026-09-01
update for the full comparison this grew out of.

This is the committed, repeatable version of the one-off analysis done
during that comparison (which found 944 of ~64k rows would validate here).
Re-run it whenever Roy's repo has moved on -- it always reads the source
database fresh, never a cached count (that repo is actively worked on by
other people too; checked during planning that its legacy-row count had
already shifted by several thousand between two checks a few days apart).

RSS/GDELT's own historical reach is irrelevant here -- this reads Roy's
already-collected data directly, not GDELT's live API.

Usage:
    python3 scripts/merge_gdelt_backlog.py --dry-run
    python3 scripts/merge_gdelt_backlog.py
    python3 scripts/merge_gdelt_backlog.py --source-db /path/to/other/incidents.db
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import IncidentDatabase  # noqa: E402
from incident_validator import validate_incident  # noqa: E402

DEFAULT_SOURCE_DB = ROOT.parent / "Roy" / "journalist-safety-monitor" / "data" / "incidents.db"

MATCHED_QUERY_LABEL = "gdelt_legacy_backfill"


def fetch_backlog_rows(source_db: Path) -> List[Dict]:
    conn = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """
            SELECT url, title, description, language, domain, country,
                   source_country, published_date
            FROM incidents
            WHERE validation_status IN ('legacy', 'candidate')
            """
        )
        legacy_rows = [dict(row) for row in cur.fetchall()]

        cur = conn.execute(
            """
            SELECT url, title, evidence_text AS description, language,
                   domain, source_country, source_country AS country,
                   published_date
            FROM article_candidates
            """
        )
        candidate_rows = [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()

    return legacy_rows + candidate_rows


def row_to_article(row: Dict) -> Dict:
    return {
        "url": row.get("url", ""),
        "title": row.get("title", ""),
        "description": row.get("description", "") or "",
        "language": row.get("language", "") or "",
    }


def row_to_incident(row: Dict, validation) -> Dict:
    return {
        "url": row.get("url", ""),
        "title": row.get("title", ""),
        "date": row.get("published_date", ""),
        "domain": row.get("domain", ""),
        "country": row.get("country") or row.get("source_country", ""),
        "severity": validation.severity,
        "incident_type": validation.incident_type,
        "description": validation.evidence_text or row.get("description", "") or row.get("title", ""),
        "language": row.get("language", ""),
        "source_country": row.get("source_country", ""),
        "matched_query": MATCHED_QUERY_LABEL,
        "validation_status": validation.status,
        "validation_reason": validation.reason,
        "evidence_text": validation.evidence_text,
    }


def row_to_candidate(row: Dict, validation) -> Dict:
    return {
        "url": row.get("url", ""),
        "title": row.get("title", ""),
        "published_date": row.get("published_date", ""),
        "domain": row.get("domain", ""),
        "source_country": row.get("source_country", ""),
        "language": row.get("language", ""),
        "matched_query": MATCHED_QUERY_LABEL,
        "validation_status": validation.status,
        "validation_reason": validation.reason,
        "evidence_text": validation.evidence_text,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-db", default=str(DEFAULT_SOURCE_DB), help="Path to Roy's repo's data/incidents.db")
    parser.add_argument("--db", default="data/incidents.db", help="This repo's SQLite database path to update")
    parser.add_argument("--dry-run", action="store_true", help="Validate and count without writing to the database")
    parser.add_argument("--batch-size", type=int, default=500, help="Rows per database batch insert")
    args = parser.parse_args()

    source_db = Path(args.source_db)
    if not source_db.exists():
        parser.error(f"Source database not found: {source_db}")

    print(f"Reading backlog from {source_db}")
    rows = fetch_backlog_rows(source_db)
    print(f"{len(rows)} rows to re-validate (legacy + candidate + article_candidates)")

    db = None if args.dry_run else IncidentDatabase(args.db)
    totals: Counter = Counter()
    reasons: Counter = Counter()
    new_incidents = 0
    duplicate_incidents = 0
    candidate_articles = 0
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

    try:
        for i, row in enumerate(rows, 1):
            validation = validate_incident(row_to_article(row))
            totals[validation.status] += 1
            reasons[validation.reason] += 1

            if validation.status == "validated":
                incident_batch.append(row_to_incident(row, validation))
            else:
                candidate_batch.append(row_to_candidate(row, validation))

            if len(incident_batch) >= args.batch_size or len(candidate_batch) >= args.batch_size:
                flush()

            if i % 5000 == 0:
                print(f"  ...{i}/{len(rows)} processed, {totals['validated']} validated so far")
    finally:
        flush()
        if db:
            db.close()

    print("\nMerge summary")
    print("=" * 80)
    print(f"Rows processed: {sum(totals.values())}")
    print(f"Validated: {totals['validated']}")
    print(f"Candidate: {totals['candidate']}")
    print(f"Rejected: {totals['rejected']}")
    print(f"New incidents inserted: {new_incidents}")
    print(f"Duplicates skipped (exact URL match): {duplicate_incidents}")
    print(f"Candidate/rejected articles stored: {candidate_articles}")
    print("\nTop validation reasons:")
    for reason, count in reasons.most_common(10):
        print(f"- {count}: {reason}")

    if not args.dry_run:
        print(
            "\nNote: near-duplicate stories from different URLs (e.g. the same "
            "event covered by several regional papers) are NOT deduplicated -- "
            "only exact URL matches are. See PLAN.md's 2026-09-01 update."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
