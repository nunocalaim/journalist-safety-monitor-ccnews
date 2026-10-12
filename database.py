#!/usr/bin/env python3
"""
Database layer for Journalist Safety Monitoring System
Handles all SQLite operations
"""

import sqlite3
import csv
import json
import re
import secrets
import shutil
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# article_candidates's storage format, 2026-09-22 through 2026-10-12: one
# SQLite file PER MONTH (data/candidates/candidates_YYYY-MM.db), not fused
# into incidents.db -- it's a pure audit trail (every article the
# validator looked at, kept so false-negative rate can be reviewed) that
# dwarfs the actual incidents data. That per-month split bounded the
# LIFETIME of the problem (a closed month's file is never touched again),
# but not the cost WITHIN a month: Git LFS can't diff a SQLite file, so
# every single insert into the still-growing current month's file
# re-uploaded (and, on the next run, re-downloaded) the WHOLE file as a
# new billable object -- September's file alone grew to 374MB that way.
# Found 2026-10-12: this was the dominant driver of both the storage *and*
# bandwidth quota crises, not a residual one. See PLAN.md's 2026-10-12
# entry.
#
# Replaced with per-run JSONL fragments (data/candidates/candidates_YYYY-MM/
# <timestamp>_<random>.jsonl, see bulk_insert_candidates): each run writes
# only its OWN new rows as a small, immutable, plain-text file -- nothing
# to read first, nothing that ever gets re-uploaded, and small enough to
# stay out of Git LFS entirely (plain git handles many small text files
# fine). Existing pre-2026-10-12 month .db files are left as closed,
# read-only history rather than migrated -- _iter_old_month_db_rows below
# still merges their rows into every query/export, same as before.
CANDIDATES_TABLE_SQL = '''
    CREATE TABLE IF NOT EXISTS article_candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT UNIQUE NOT NULL,
        title TEXT,
        published_date TEXT,
        domain TEXT,
        source_country TEXT,
        language TEXT,
        matched_query TEXT,
        validation_status TEXT,
        validation_reason TEXT,
        evidence_text TEXT,
        collected_at TEXT DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT unique_candidate_url UNIQUE(url)
    )
'''
CANDIDATES_INDEX_SQL = [
    'CREATE INDEX IF NOT EXISTS idx_candidate_status ON article_candidates(validation_status)',
    'CREATE INDEX IF NOT EXISTS idx_candidate_date ON article_candidates(published_date)',
]
# Matches CANDIDATES_TABLE_SQL's columns -- used as the CSV header when a
# window has zero matching rows across every monthly file, so a quiet
# day/window still produces a fresh (header-only) export rather than
# silently leaving a stale file with an earlier day's data sitting there.
CANDIDATES_COLUMNS = [
    'id', 'url', 'title', 'published_date', 'domain', 'source_country',
    'language', 'matched_query', 'validation_status', 'validation_reason',
    'evidence_text', 'collected_at',
]
# Fields actually written to a fragment row (no autoincrement 'id' --
# that was only ever an old per-month-file SQLite rowid).
_FRAGMENT_FIELDS = [c for c in CANDIDATES_COLUMNS if c != 'id']
# Query-time-only merge table: deliberately has NO unique constraint on
# url, unlike CANDIDATES_TABLE_SQL -- it's a throwaway in-memory table
# built fresh from every old month file plus every fragment on each call,
# and the old per-file design already tolerated (and relied on returning)
# duplicate URLs across different sources rather than deduping them away;
# this preserves that.
_CANDIDATES_MERGE_TABLE_SQL = '''
    CREATE TABLE article_candidates (
        url TEXT,
        title TEXT,
        published_date TEXT,
        domain TEXT,
        source_country TEXT,
        language TEXT,
        matched_query TEXT,
        validation_status TEXT,
        validation_reason TEXT,
        evidence_text TEXT,
        collected_at TEXT
    )
'''


class IncidentDatabase:
    """SQLite database for storing and querying journalist safety incidents"""

    def __init__(self, db_path: str = 'data/incidents.db'):
        """Initialize database connection and create tables if needed"""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row

        # candidates_dir sits next to incidents.db (not a hardcoded
        # "data/candidates") so a differently-located db -- e.g. a test's
        # tmp_path -- gets its own isolated candidates directory too.
        self.candidates_dir = self.db_path.parent / 'candidates'

        self.create_tables()
        logger.info(f"Database initialized: {self.db_path}")

    def _candidates_fragment_dir(self, when: Optional[datetime] = None) -> Path:
        when = when or datetime.now()
        return self.candidates_dir / f"candidates_{when.strftime('%Y-%m')}"

    def _old_month_db_paths(self) -> List[Path]:
        """Every pre-2026-10-12 candidates_YYYY-MM.db file actually present
        as a real SQLite file -- not just present as a path. The scheduled
        workflow does a SCOPED `git lfs pull` (current + previous month
        only, full history once a day -- see monitor.yml), but
        `actions/checkout` still writes every tracked path in the tree
        regardless, including months that weren't pulled: those sit on
        disk as small LFS *pointer* text files
        ("version https://git-lfs.github.com/..."), not the actual
        database. Found 2026-10-09: querying one of those raised
        `sqlite3.DatabaseError: file is not a database` and crashed the
        whole export. Checking the SQLite magic header before trusting a
        path is cheap and also protects against any other way a file could
        end up present-but-not-materialized (shallow clone, interrupted
        pull, etc.) -- a missing/unpulled month just silently contributes
        no rows instead of crashing the run.
        """
        if not self.candidates_dir.exists():
            return []
        paths = []
        for path in sorted(self.candidates_dir.glob('candidates_*.db')):
            try:
                with open(path, 'rb') as f:
                    header = f.read(16)
            except OSError:
                continue
            if header != b'SQLite format 3\x00':
                logger.warning(
                    f"Skipping {path} -- not a real SQLite file (likely an "
                    f"un-pulled Git LFS pointer stub)"
                )
                continue
            paths.append(path)
        return paths

    def _fragment_month_dirs(self) -> List[Path]:
        """Every candidates_YYYY-MM/ fragment directory (2026-10-12+
        format)."""
        if not self.candidates_dir.exists():
            return []
        return sorted(
            p for p in self.candidates_dir.glob('candidates_????-??') if p.is_dir()
        )

    def _iter_old_month_db_rows(self) -> Iterator[Dict]:
        """Rows from every closed, read-only pre-2026-10-12 month file."""
        for path in self._old_month_db_paths():
            conn = sqlite3.connect(str(path))
            conn.row_factory = sqlite3.Row
            try:
                for row in conn.execute('SELECT * FROM article_candidates'):
                    yield dict(row)
            finally:
                conn.close()

    def _iter_fragment_rows(self) -> Iterator[Dict]:
        """Rows from every per-run JSONL fragment, across every month."""
        for month_dir in self._fragment_month_dirs():
            for fragment_path in sorted(month_dir.glob('*.jsonl')):
                try:
                    with open(fragment_path, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            yield json.loads(line)
                except (OSError, json.JSONDecodeError) as exc:
                    logger.warning(f"Skipping unreadable fragment {fragment_path}: {exc}")

    def _iter_all_candidates(self) -> Iterator[Dict]:
        yield from self._iter_old_month_db_rows()
        yield from self._iter_fragment_rows()

    def _query_all_candidates(self, where_sql: str, params: tuple) -> List[sqlite3.Row]:
        """Merge every old month file's rows with every fragment's rows
        into a throwaway in-memory table, then run the same SELECT against
        it. Reusing SQL (rather than hand-rolling the filter in Python) is
        deliberate: published_date's format is wildly inconsistent across
        sources (RSS's RFC-822 dates, GDELT's "20260920T143000Z", CC-NEWS's
        plain "2026-09-04", etc.) and SQLite's date() function already
        tolerates that -- re-deriving its parsing behavior in Python would
        risk silently diverging from it.

        Adds a synthetic __sort_date column (same COALESCE(date(...), ...)
        normalization the old query sorted by) so callers can sort merged
        rows consistently.
        """
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.execute(_CANDIDATES_MERGE_TABLE_SQL)
        try:
            conn.executemany(
                '''
                INSERT INTO article_candidates
                (url, title, published_date, domain, source_country, language,
                 matched_query, validation_status, validation_reason,
                 evidence_text, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    (
                        row.get('url', ''), row.get('title', ''), row.get('published_date', ''),
                        row.get('domain', ''), row.get('source_country', ''), row.get('language', ''),
                        row.get('matched_query', ''), row.get('validation_status', ''),
                        row.get('validation_reason', ''), row.get('evidence_text', ''),
                        row.get('collected_at', ''),
                    )
                    for row in self._iter_all_candidates()
                ),
            )
            cursor = conn.execute(
                f'''
                SELECT *, COALESCE(date(published_date), date(collected_at)) AS __sort_date
                FROM article_candidates {where_sql}
                ''',
                params,
            )
            return cursor.fetchall()
        finally:
            conn.close()
    
    def create_tables(self):
        """Create all necessary tables and indexes"""
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                published_date TEXT,
                domain TEXT,
                country TEXT,
                severity TEXT,
                incident_type TEXT,
                description TEXT,
                language TEXT,
                source_country TEXT,
                collected_at TEXT DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT unique_url UNIQUE(url)
            )
        ''')
        
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS daily_stats (
                date TEXT PRIMARY KEY,
                total_incidents INTEGER,
                critical_count INTEGER,
                high_count INTEGER,
                medium_count INTEGER,
                low_count INTEGER,
                unique_countries INTEGER,
                unique_domains INTEGER,
                collection_queries INTEGER
            )
        ''')
        
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS country_scores (
                country TEXT,
                date TEXT,
                risk_score INTEGER,
                incident_count INTEGER,
                critical_count INTEGER,
                high_count INTEGER,
                PRIMARY KEY (country, date)
            )
        ''')
        
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS collection_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date TEXT,
                queries_executed INTEGER,
                articles_collected INTEGER,
                new_incidents INTEGER,
                execution_time_seconds REAL,
                status TEXT
            )
        ''')

        self.conn.execute('CREATE INDEX IF NOT EXISTS idx_country ON incidents(country)')
        self.conn.execute('CREATE INDEX IF NOT EXISTS idx_date ON incidents(published_date)')
        self.conn.execute('CREATE INDEX IF NOT EXISTS idx_severity ON incidents(severity)')
        self.conn.execute('CREATE INDEX IF NOT EXISTS idx_type ON incidents(incident_type)')
        self.conn.execute('CREATE INDEX IF NOT EXISTS idx_domain ON incidents(domain)')
        self._ensure_incidents_columns()
        self.conn.execute('CREATE INDEX IF NOT EXISTS idx_validation_status ON incidents(validation_status)')
        self.conn.execute('CREATE INDEX IF NOT EXISTS idx_incident_fingerprint ON incidents(incident_fingerprint)')
        # article_candidates is NOT created here -- see the module-level
        # comment above CANDIDATES_TABLE_SQL for why it lives in its own
        # per-month file instead.

        self.conn.commit()
        logger.info("Database tables created/verified")

    def _ensure_incidents_columns(self):
        """Add validation columns to older databases without rebuilding them."""
        existing_columns = {
            row['name']
            for row in self.conn.execute("PRAGMA table_info(incidents)").fetchall()
        }
        columns = {
            'matched_query': "TEXT",
            'validation_status': "TEXT DEFAULT 'legacy'",
            'validation_reason': "TEXT",
            'evidence_text': "TEXT",
            'incident_fingerprint': "TEXT",
        }
        for column, definition in columns.items():
            if column not in existing_columns:
                self.conn.execute(f"ALTER TABLE incidents ADD COLUMN {column} {definition}")
    
    def bulk_insert_incidents(self, incidents: List[Dict]) -> Tuple[int, int]:
        """Insert multiple incidents, handling duplicates"""
        new_count = 0
        duplicate_count = 0
        
        for incident in incidents:
            fingerprint = self._incident_fingerprint(incident)
            if self._has_similar_incident(incident, fingerprint):
                duplicate_count += 1
                continue

            try:
                self.conn.execute('''
                    INSERT INTO incidents 
                    (url, title, published_date, domain, country, severity, 
                     incident_type, description, language, source_country,
                     matched_query, validation_status, validation_reason,
                     evidence_text, incident_fingerprint)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    incident['url'],
                    incident['title'],
                    incident['date'],
                    incident['domain'],
                    incident['country'],
                    incident['severity'],
                    incident['incident_type'],
                    incident['description'],
                    incident['language'],
                    incident.get('source_country', ''),
                    incident.get('matched_query', ''),
                    incident.get('validation_status', 'validated'),
                    incident.get('validation_reason', ''),
                    incident.get('evidence_text', ''),
                    fingerprint
                ))
                new_count += 1
            except sqlite3.IntegrityError:
                duplicate_count += 1
        
        self.conn.commit()
        return new_count, duplicate_count

    def bulk_insert_candidates(self, candidates: List[Dict]) -> Tuple[int, int]:
        """Write this run's new review candidates as one small, immutable
        JSONL fragment (data/candidates/candidates_YYYY-MM/<ts>_<rand>.jsonl)
        -- never into a shared, growing file. See the module-level comment
        above CANDIDATES_TABLE_SQL for why: a file that's never modified
        again after being written has nothing to re-upload or re-download,
        unlike the old per-month SQLite file this replaced.

        Deduplicates by URL only within this one call's batch (there's no
        shared index across fragments to enforce it otherwise) -- same
        trade-off the old per-month file already accepted ("a review aid,
        not the source of truth"), just scoped to a batch instead of a
        month.
        """
        seen_urls = set()
        deduped = []
        duplicate_count = 0
        for candidate in candidates:
            url = candidate.get('url')
            if not url:
                continue
            if url in seen_urls:
                duplicate_count += 1
                continue
            seen_urls.add(url)
            deduped.append(candidate)

        if not deduped:
            return 0, duplicate_count

        fragment_dir = self._candidates_fragment_dir()
        fragment_dir.mkdir(parents=True, exist_ok=True)
        fragment_path = fragment_dir / (
            f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{secrets.token_hex(4)}.jsonl"
        )
        now = datetime.now().isoformat(timespec='seconds')
        with open(fragment_path, 'w', encoding='utf-8') as f:
            for candidate in deduped:
                row = {field: candidate.get(field, '') for field in _FRAGMENT_FIELDS}
                row['collected_at'] = candidate.get('collected_at') or now
                f.write(json.dumps(row, ensure_ascii=False) + '\n')

        return len(deduped), duplicate_count

    def _incident_fingerprint(self, incident: Dict) -> str:
        title = incident.get('description') or incident.get('title') or ''
        normalized = re.sub(r'[^a-z0-9\s]', ' ', title.lower())
        tokens = [
            token
            for token in normalized.split()
            if token not in {
                'the', 'a', 'an', 'in', 'on', 'at', 'to', 'of', 'and', 'or',
                'says', 'said', 'rejects', 'claim', 'claims', 'against', 'was',
                'were', 'he', 'she', 'they', 'his', 'her', 'their'
            }
        ]
        return ' '.join(tokens[:12])

    def _has_similar_incident(self, incident: Dict, fingerprint: str) -> bool:
        incident_type = incident.get('incident_type', '')
        country = incident.get('country', '')
        title = (incident.get('description') or incident.get('title') or '').lower()
        if not title:
            return False

        cursor = self.conn.execute('''
            SELECT title, description, incident_fingerprint
            FROM incidents
            WHERE validation_status = 'validated'
            AND incident_type = ?
            AND COALESCE(country, '') = COALESCE(?, '')
            AND COALESCE(date(published_date), date(collected_at)) > date('now', '-14 days')
            ORDER BY id DESC
            LIMIT 100
        ''', (incident_type, country))

        for row in cursor.fetchall():
            existing_text = (row['description'] or row['title'] or '').lower()
            existing_fingerprint = row['incident_fingerprint'] or self._incident_fingerprint(dict(row))
            if fingerprint and existing_fingerprint and fingerprint == existing_fingerprint:
                return True
            if SequenceMatcher(None, title, existing_text).ratio() >= 0.72:
                return True

        return False
    
    def get_statistics(self, days: int = 30, validation_status: Optional[str] = None) -> Dict:
        """Get comprehensive statistics - FIXED to handle NULL dates"""
        validation_clause, validation_params = self._validation_filter(validation_status)
        cursor = self.conn.execute('''
            SELECT 
                COUNT(*) as total_incidents,
                COUNT(DISTINCT country) as unique_countries,
                COUNT(DISTINCT domain) as unique_domains,
                SUM(CASE WHEN severity = 'CRITICAL' THEN 1 ELSE 0 END) as critical,
                SUM(CASE WHEN severity = 'HIGH' THEN 1 ELSE 0 END) as high,
                SUM(CASE WHEN severity = 'MEDIUM' THEN 1 ELSE 0 END) as medium,
                SUM(CASE WHEN severity = 'LOW' THEN 1 ELSE 0 END) as low,
                MIN(COALESCE(date(published_date), date(collected_at))) as earliest_date,
                MAX(COALESCE(date(published_date), date(collected_at))) as latest_date
            FROM incidents
            WHERE COALESCE(date(published_date), date(collected_at)) > date('now', '-' || ? || ' days')
            {validation_clause}
        '''.format(validation_clause=validation_clause), (days, *validation_params))
        
        result = dict(cursor.fetchone())
        
        if result['total_incidents'] is None:
            result['total_incidents'] = 0
        if result['unique_countries'] is None:
            result['unique_countries'] = 0
        if result['unique_domains'] is None:
            result['unique_domains'] = 0
        if result['critical'] is None:
            result['critical'] = 0
        if result['high'] is None:
            result['high'] = 0
        if result['medium'] is None:
            result['medium'] = 0
        if result['low'] is None:
            result['low'] = 0
        
        return result
    
    def save_daily_stats(self, date: str, stats: Dict):
        """Save daily statistics snapshot"""
        self.conn.execute('''
            INSERT OR REPLACE INTO daily_stats
            (date, total_incidents, critical_count, high_count, medium_count, 
             low_count, unique_countries, unique_domains, collection_queries)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            date,
            stats.get('total_incidents', 0),
            stats.get('critical', 0),
            stats.get('high', 0),
            stats.get('medium', 0),
            stats.get('low', 0),
            stats.get('unique_countries', 0),
            stats.get('unique_domains', 0),
            stats.get('queries_executed', 0)
        ))
        self.conn.commit()
    
    def get_country_rankings(self, days: int = 30, validation_status: Optional[str] = None) -> List[Dict]:
        """Get countries ranked by risk"""
        validation_clause, validation_params = self._validation_filter(validation_status)
        cursor = self.conn.execute('''
            SELECT 
                country,
                COUNT(*) as incident_count,
                SUM(CASE WHEN severity = 'CRITICAL' THEN 1 ELSE 0 END) as critical_count,
                SUM(CASE WHEN severity = 'HIGH' THEN 1 ELSE 0 END) as high_count,
                (SUM(CASE WHEN severity = 'CRITICAL' THEN 10 ELSE 0 END) +
                 SUM(CASE WHEN severity = 'HIGH' THEN 5 ELSE 0 END) +
                 SUM(CASE WHEN severity = 'MEDIUM' THEN 2 ELSE 0 END)) as risk_score
            FROM incidents
            WHERE COALESCE(date(published_date), date(collected_at)) > date('now', '-' || ? || ' days')
            {validation_clause}
            AND country IS NOT NULL AND country != ''
            GROUP BY country
            ORDER BY risk_score DESC
        '''.format(validation_clause=validation_clause), (days, *validation_params))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_trend_data(self, days: int = 30, validation_status: Optional[str] = None) -> List[Dict]:
        """Get incident trend data by day"""
        validation_clause, validation_params = self._validation_filter(validation_status)
        cursor = self.conn.execute('''
            SELECT 
                date(COALESCE(published_date, collected_at)) as date,
                COUNT(*) as total,
                SUM(CASE WHEN severity = 'CRITICAL' THEN 1 ELSE 0 END) as critical,
                SUM(CASE WHEN severity = 'HIGH' THEN 1 ELSE 0 END) as high
            FROM incidents
            WHERE COALESCE(date(published_date), date(collected_at)) > date('now', '-' || ? || ' days')
            {validation_clause}
            GROUP BY date(COALESCE(published_date, collected_at))
            ORDER BY date
        '''.format(validation_clause=validation_clause), (days, *validation_params))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_incident_types_breakdown(self, days: int = 30, validation_status: Optional[str] = None) -> List[Dict]:
        """Get breakdown by incident type"""
        validation_clause, validation_params = self._validation_filter(validation_status)
        cursor = self.conn.execute('''
            SELECT 
                incident_type,
                COUNT(*) as count,
                SUM(CASE WHEN severity = 'CRITICAL' THEN 1 ELSE 0 END) as critical_count
            FROM incidents
            WHERE COALESCE(date(published_date), date(collected_at)) > date('now', '-' || ? || ' days')
            {validation_clause}
            GROUP BY incident_type
            ORDER BY count DESC
        '''.format(validation_clause=validation_clause), (days, *validation_params))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_incidents_by_severity(self, severity: str, days: int = 7, validation_status: Optional[str] = None) -> List[Dict]:
        """Get incidents by severity level"""
        validation_clause, validation_params = self._validation_filter(validation_status)
        cursor = self.conn.execute('''
            SELECT *
            FROM incidents
            WHERE severity = ? 
            AND COALESCE(date(published_date), date(collected_at)) > date('now', '-' || ? || ' days')
            {validation_clause}
            ORDER BY COALESCE(date(published_date), date(collected_at)) DESC
            LIMIT 20
        '''.format(validation_clause=validation_clause), (severity, days, *validation_params))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def export_to_csv(self, filepath: str, days: Optional[int] = None, validation_status: Optional[str] = None):
        """Export incidents to CSV"""
        validation_clause, validation_params = self._validation_filter(validation_status)
        if days:
            cursor = self.conn.execute('''
                SELECT * FROM incidents
                WHERE COALESCE(date(published_date), date(collected_at)) > date('now', '-' || ? || ' days')
                {validation_clause}
                ORDER BY COALESCE(date(published_date), date(collected_at)) DESC
            '''.format(validation_clause=validation_clause), (days, *validation_params))
        else:
            cursor = self.conn.execute('''
                SELECT * FROM incidents
                WHERE 1 = 1
                {validation_clause}
                ORDER BY COALESCE(date(published_date), date(collected_at)) DESC
            '''.format(validation_clause=validation_clause), validation_params)
        
        rows = cursor.fetchall()
        if not rows:
            logger.warning(f"No data to export to {filepath}")
            return
        
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[description[0] for description in cursor.description])
            writer.writeheader()
            for row in rows:
                writer.writerow(dict(row))
        
        logger.info(f"Exported {len(rows)} incidents to {filepath}")

    def export_candidates_to_csv(self, filepath: str, days: Optional[int] = None):
        """Export review candidates to CSV, across every month's file."""
        where_sql = "WHERE validation_status = 'candidate'"
        params: tuple = ()
        if days:
            where_sql += (
                " AND COALESCE(date(published_date), date(collected_at))"
                " > date('now', '-' || ? || ' days')"
            )
            params = (days,)

        rows = self._query_all_candidates(where_sql, params)
        rows.sort(key=lambda r: r['__sort_date'] or '', reverse=True)
        fieldnames = [k for k in rows[0].keys() if k != '__sort_date'] if rows else CANDIDATES_COLUMNS

        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row[k] for k in fieldnames})

        logger.info(f"Exported {len(rows)} candidates to {filepath}")

    def purge_old_data(self, days: int) -> int:
        """Delete incident rows older than the configured retention window."""
        cursor = self.conn.execute('''
            DELETE FROM incidents
            WHERE COALESCE(date(published_date), date(collected_at)) <= date('now', '-' || ? || ' days')
        ''', (days,))
        deleted_count = cursor.rowcount

        self.conn.execute('''
            DELETE FROM daily_stats
            WHERE date(date) <= date('now', '-' || ? || ' days')
        ''', (days,))
        self.conn.execute('''
            DELETE FROM country_scores
            WHERE date(date) <= date('now', '-' || ? || ' days')
        ''', (days,))

        self.conn.commit()
        self.conn.execute('VACUUM')

        self._purge_old_candidates_files(days)

        logger.info(f"Purged {deleted_count} incidents older than {days} days")
        return deleted_count

    def _purge_old_candidates_files(self, days: int) -> None:
        """Delete whole months of candidates data -- both the old
        single-file format and the current per-run-fragment-directory
        format -- once every row a month could possibly contain is past
        the retention window. Much cheaper than a row-level DELETE, and
        the natural way to apply retention given candidates are
        partitioned by month. Trade-off: this is whole-month granularity,
        not exact-day -- a month whose last day hasn't yet crossed the
        cutoff is kept in full even if most of it has, so data can now
        linger up to ~30 days past the configured retention window before
        it's actually deleted."""
        cutoff = datetime.now() - timedelta(days=days)
        current_month = datetime.now().strftime('%Y-%m')

        paths: List[Path] = [*self._old_month_db_paths(), *self._fragment_month_dirs()]
        for path in paths:
            month_str = path.stem.removeprefix('candidates_')
            if month_str == current_month:
                continue  # never delete the month still being written to
            try:
                file_month = datetime.strptime(month_str, '%Y-%m')
            except ValueError:
                continue
            year = file_month.year + (1 if file_month.month == 12 else 0)
            month = 1 if file_month.month == 12 else file_month.month + 1
            first_day_of_next_month = datetime(year, month, 1)
            if cutoff >= first_day_of_next_month:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                logger.info(f"Purged expired candidates data: {path}")

    def get_last_successful_run_date(self) -> Optional[datetime]:
        cursor = self.conn.execute('''
            SELECT run_date
            FROM collection_runs
            WHERE status = 'SUCCESS'
            ORDER BY datetime(run_date) DESC
            LIMIT 1
        ''')
        row = cursor.fetchone()
        if not row:
            return None
        try:
            return datetime.fromisoformat(row['run_date'])
        except ValueError:
            return None

    def _validation_filter(self, validation_status: Optional[str]) -> Tuple[str, Tuple[str, ...]]:
        if not validation_status:
            return "", ()
        return "AND validation_status = ?", (validation_status,)
    
    def export_to_json(self, filepath: str, days: Optional[int] = None):
        """Export incidents to JSON"""
        if days:
            cursor = self.conn.execute('''
                SELECT * FROM incidents
                WHERE COALESCE(date(published_date), date(collected_at)) > date('now', '-' || ? || ' days')
                ORDER BY COALESCE(date(published_date), date(collected_at)) DESC
            ''', (days,))
        else:
            cursor = self.conn.execute('SELECT * FROM incidents ORDER BY COALESCE(date(published_date), date(collected_at)) DESC')
        
        rows = [dict(row) for row in cursor.fetchall()]
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Exported {len(rows)} incidents to {filepath}")
    
    def save_country_scores(self, date: str, countries: List[Dict]):
        """Save country risk scores"""
        for country_data in countries:
            self.conn.execute('''
                INSERT OR REPLACE INTO country_scores
                (country, date, risk_score, incident_count, critical_count, high_count)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                country_data['country'],
                date,
                country_data.get('risk_score', 0),
                country_data.get('incident_count', 0),
                country_data.get('critical_count', 0),
                country_data.get('high_count', 0)
            ))
        self.conn.commit()
    
    def log_collection_run(self, run_data: Dict):
        """Log a collection run"""
        self.conn.execute('''
            INSERT INTO collection_runs
            (run_date, queries_executed, articles_collected, new_incidents, execution_time_seconds, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            run_data['run_date'],
            run_data['queries_executed'],
            run_data['articles_collected'],
            run_data['new_incidents'],
            run_data['execution_time'],
            run_data['status']
        ))
        self.conn.commit()
    
    def close(self):
        """Close database connection"""
        self.conn.close()
        logger.info("Database connection closed")
