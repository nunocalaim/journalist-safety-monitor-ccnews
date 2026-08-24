#!/usr/bin/env python3
"""
Database layer for Journalist Safety Monitoring System
Handles all SQLite operations
"""

import sqlite3
import csv
import json
import re
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class IncidentDatabase:
    """SQLite database for storing and querying journalist safety incidents"""
    
    def __init__(self, db_path: str = 'data/incidents.db'):
        """Initialize database connection and create tables if needed"""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        
        self.create_tables()
        logger.info(f"Database initialized: {self.db_path}")
    
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

        self.conn.execute('''
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
        ''')
        
        self.conn.execute('CREATE INDEX IF NOT EXISTS idx_country ON incidents(country)')
        self.conn.execute('CREATE INDEX IF NOT EXISTS idx_date ON incidents(published_date)')
        self.conn.execute('CREATE INDEX IF NOT EXISTS idx_severity ON incidents(severity)')
        self.conn.execute('CREATE INDEX IF NOT EXISTS idx_type ON incidents(incident_type)')
        self.conn.execute('CREATE INDEX IF NOT EXISTS idx_domain ON incidents(domain)')
        self._ensure_incidents_columns()
        self.conn.execute('CREATE INDEX IF NOT EXISTS idx_validation_status ON incidents(validation_status)')
        self.conn.execute('CREATE INDEX IF NOT EXISTS idx_incident_fingerprint ON incidents(incident_fingerprint)')
        self.conn.execute('CREATE INDEX IF NOT EXISTS idx_candidate_status ON article_candidates(validation_status)')
        self.conn.execute('CREATE INDEX IF NOT EXISTS idx_candidate_date ON article_candidates(published_date)')
        
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
        """Insert candidate/rejected article decisions for review exports."""
        new_count = 0
        duplicate_count = 0

        for candidate in candidates:
            if not candidate.get('url'):
                continue
            try:
                self.conn.execute('''
                    INSERT OR REPLACE INTO article_candidates
                    (url, title, published_date, domain, source_country, language,
                     matched_query, validation_status, validation_reason, evidence_text)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    candidate.get('url', ''),
                    candidate.get('title', ''),
                    candidate.get('published_date', ''),
                    candidate.get('domain', ''),
                    candidate.get('source_country', ''),
                    candidate.get('language', ''),
                    candidate.get('matched_query', ''),
                    candidate.get('validation_status', ''),
                    candidate.get('validation_reason', ''),
                    candidate.get('evidence_text', ''),
                ))
                new_count += 1
            except sqlite3.IntegrityError:
                duplicate_count += 1

        self.conn.commit()
        return new_count, duplicate_count

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
        """Export review candidates to CSV."""
        if days:
            cursor = self.conn.execute('''
                SELECT *
                FROM article_candidates
                WHERE validation_status = 'candidate'
                AND COALESCE(date(published_date), date(collected_at)) > date('now', '-' || ? || ' days')
                ORDER BY COALESCE(date(published_date), date(collected_at)) DESC
            ''', (days,))
        else:
            cursor = self.conn.execute('''
                SELECT *
                FROM article_candidates
                WHERE validation_status = 'candidate'
                ORDER BY COALESCE(date(published_date), date(collected_at)) DESC
            ''')

        rows = cursor.fetchall()
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[description[0] for description in cursor.description])
            writer.writeheader()
            for row in rows:
                writer.writerow(dict(row))

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
        self.conn.execute('''
            DELETE FROM article_candidates
            WHERE COALESCE(date(published_date), date(collected_at)) <= date('now', '-' || ? || ' days')
        ''', (days,))

        self.conn.commit()
        self.conn.execute('VACUUM')
        logger.info(f"Purged {deleted_count} incidents older than {days} days")
        return deleted_count

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
