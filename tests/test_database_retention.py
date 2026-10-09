import sqlite3
from datetime import datetime, timedelta

from database import CANDIDATES_INDEX_SQL, CANDIDATES_TABLE_SQL, IncidentDatabase


def _incident(url, days_ago, title=None, description=None):
    date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    title = title or f"Journalist incident {url}"
    return {
        "url": url,
        "title": title,
        "date": date,
        "domain": "example.com",
        "country": "US",
        "severity": "HIGH",
        "incident_type": "DETENTION",
        "description": description or title,
        "language": "English",
        "source_country": "US",
    }


def test_purge_old_data_removes_incidents_outside_window(tmp_path):
    db = IncidentDatabase(db_path=str(tmp_path / "incidents.db"))
    try:
        db.bulk_insert_incidents([
            _incident("https://example.com/recent", days_ago=5, title="Reporter detained at protest"),
            _incident("https://example.com/old", days_ago=200, title="Editor arrested after investigation"),
        ])

        deleted = db.purge_old_data(days=180)
        stats = db.get_statistics(days=365)

        assert deleted == 1
        assert stats["total_incidents"] == 1
    finally:
        db.close()


def test_export_to_csv_respects_days_window(tmp_path):
    db = IncidentDatabase(db_path=str(tmp_path / "incidents.db"))
    try:
        db.bulk_insert_incidents([
            _incident("https://example.com/recent", days_ago=5),
            _incident("https://example.com/older", days_ago=20),
        ])
        export_path = tmp_path / "incidents_10d.csv"

        db.export_to_csv(str(export_path), days=10)

        exported = export_path.read_text()
        assert "https://example.com/recent" in exported
        assert "https://example.com/older" not in exported
    finally:
        db.close()


def test_statistics_and_exports_can_filter_validated_rows(tmp_path):
    db = IncidentDatabase(db_path=str(tmp_path / "incidents.db"))
    try:
        validated = _incident("https://example.com/validated", days_ago=1, title="Reporter detained")
        legacy = _incident("https://example.com/legacy", days_ago=1, title="Unrelated person killed")
        legacy["validation_status"] = "legacy"
        db.bulk_insert_incidents([validated, legacy])

        stats = db.get_statistics(days=10, validation_status="validated")
        export_path = tmp_path / "validated.csv"
        db.export_to_csv(str(export_path), days=10, validation_status="validated")
        exported = export_path.read_text()

        assert stats["total_incidents"] == 1
        assert "https://example.com/validated" in exported
        assert "https://example.com/legacy" not in exported
    finally:
        db.close()


def test_candidate_export_writes_review_candidates(tmp_path):
    db = IncidentDatabase(db_path=str(tmp_path / "incidents.db"))
    try:
        db.bulk_insert_candidates([
            {
                "url": "https://example.com/candidate",
                "title": "Periodista asesinado en Mexico",
                "published_date": datetime.now().strftime("%Y-%m-%d"),
                "domain": "example.com",
                "source_country": "MX",
                "language": "Spanish",
                "matched_query": 'near10:"journalist killed"',
                "validation_status": "candidate",
                "validation_reason": "media subject found but no clear harm action in returned text",
                "evidence_text": "Periodista asesinado en Mexico",
            }
        ])
        export_path = tmp_path / "candidates_10d.csv"

        db.export_candidates_to_csv(str(export_path), days=10)

        exported = export_path.read_text()
        assert "https://example.com/candidate" in exported
        assert "media subject found but no clear harm action" in exported
    finally:
        db.close()


def test_candidate_full_export_includes_older_review_candidates(tmp_path):
    db = IncidentDatabase(db_path=str(tmp_path / "incidents.db"))
    try:
        db.bulk_insert_candidates([
            {
                "url": "https://example.com/old-candidate",
                "title": "Periodista asesinado en Mexico",
                "published_date": (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d"),
                "domain": "example.com",
                "source_country": "MX",
                "language": "Spanish",
                "matched_query": "historical_backfill",
                "validation_status": "candidate",
                "validation_reason": "media subject found but no clear harm action in returned text",
                "evidence_text": "Periodista asesinado en Mexico",
            }
        ])
        full_export_path = tmp_path / "candidates_full.csv"
        rolling_export_path = tmp_path / "candidates_10d.csv"

        db.export_candidates_to_csv(str(full_export_path))
        db.export_candidates_to_csv(str(rolling_export_path), days=10)

        assert "https://example.com/old-candidate" in full_export_path.read_text()
        assert "https://example.com/old-candidate" not in rolling_export_path.read_text()
    finally:
        db.close()


def _write_candidate_to_month_file(candidates_dir, month, url, published_days_ago):
    """Directly populate an older month's candidates file, simulating one
    left behind by a previous month's live runs (bulk_insert_candidates
    only ever writes to the CURRENT month, so tests need this to set up a
    multi-month scenario)."""
    candidates_dir.mkdir(parents=True, exist_ok=True)
    path = candidates_dir / f"candidates_{month}.db"
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(CANDIDATES_TABLE_SQL)
        for index_sql in CANDIDATES_INDEX_SQL:
            conn.execute(index_sql)
        published_date = (datetime.now() - timedelta(days=published_days_ago)).strftime("%Y-%m-%d")
        conn.execute(
            '''
            INSERT INTO article_candidates
            (url, title, published_date, domain, source_country, language,
             matched_query, validation_status, validation_reason, evidence_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (url, f"Journalist story {url}", published_date, "example.com", "MX",
             "Spanish", "historical", "candidate", "media subject found but no clear harm action",
             "Journalist story"),
        )
        conn.commit()
    finally:
        conn.close()
    return path


def test_bulk_insert_candidates_only_writes_current_month(tmp_path):
    db = IncidentDatabase(db_path=str(tmp_path / "incidents.db"))
    try:
        old_month = (datetime.now() - timedelta(days=90)).strftime("%Y-%m")
        old_path = _write_candidate_to_month_file(
            tmp_path / "candidates", old_month, "https://example.com/old-month", 90
        )

        db.bulk_insert_candidates([{
            "url": "https://example.com/this-month",
            "title": "Reporter detained",
            "published_date": datetime.now().strftime("%Y-%m-%d"),
            "domain": "example.com",
            "source_country": "US",
            "language": "English",
            "matched_query": "live",
            "validation_status": "candidate",
            "validation_reason": "media subject found but no clear harm action",
            "evidence_text": "Reporter detained",
        }])

        current_month = datetime.now().strftime("%Y-%m")
        current_path = tmp_path / "candidates" / f"candidates_{current_month}.db"
        assert current_path.exists()

        # The old month's file is untouched -- still exactly the one row
        # written directly into it, nothing from this run leaked in.
        conn = sqlite3.connect(str(old_path))
        try:
            rows = conn.execute("SELECT url FROM article_candidates").fetchall()
        finally:
            conn.close()
        assert rows == [("https://example.com/old-month",)]
    finally:
        db.close()


def test_export_candidates_merges_across_months(tmp_path):
    db = IncidentDatabase(db_path=str(tmp_path / "incidents.db"))
    try:
        old_month = (datetime.now() - timedelta(days=60)).strftime("%Y-%m")
        _write_candidate_to_month_file(
            tmp_path / "candidates", old_month, "https://example.com/old-month-candidate", 60
        )
        db.bulk_insert_candidates([{
            "url": "https://example.com/current-month-candidate",
            "title": "Reporter detained",
            "published_date": datetime.now().strftime("%Y-%m-%d"),
            "domain": "example.com",
            "source_country": "US",
            "language": "English",
            "matched_query": "live",
            "validation_status": "candidate",
            "validation_reason": "media subject found but no clear harm action",
            "evidence_text": "Reporter detained",
        }])

        export_path = tmp_path / "candidates_full.csv"
        db.export_candidates_to_csv(str(export_path))

        exported = export_path.read_text()
        assert "https://example.com/old-month-candidate" in exported
        assert "https://example.com/current-month-candidate" in exported
    finally:
        db.close()


def test_export_candidates_skips_unpulled_lfs_pointer_file(tmp_path):
    """Real failure, 2026-10-09: the scheduled workflow's scoped `git lfs
    pull` only fetches the current + previous month's candidates file;
    actions/checkout still writes every OTHER month's path too, left as a
    small LFS pointer stub (not real SQLite content). Querying it crashed
    the whole export with sqlite3.DatabaseError: file is not a database.
    """
    db = IncidentDatabase(db_path=str(tmp_path / "incidents.db"))
    try:
        candidates_dir = tmp_path / "candidates"
        candidates_dir.mkdir(parents=True, exist_ok=True)
        stub_month = (datetime.now() - timedelta(days=90)).strftime("%Y-%m")
        stub_path = candidates_dir / f"candidates_{stub_month}.db"
        stub_path.write_text(
            "version https://git-lfs.github.com/spec/v1\n"
            "oid sha256:0000000000000000000000000000000000000000000000000000000000000000\n"
            "size 123456\n"
        )

        db.bulk_insert_candidates([{
            "url": "https://example.com/current-month-candidate",
            "title": "Reporter detained",
            "published_date": datetime.now().strftime("%Y-%m-%d"),
            "domain": "example.com",
            "source_country": "US",
            "language": "English",
            "matched_query": "live",
            "validation_status": "candidate",
            "validation_reason": "media subject found but no clear harm action",
            "evidence_text": "Reporter detained",
        }])

        export_path = tmp_path / "candidates_full.csv"
        db.export_candidates_to_csv(str(export_path))  # must not raise

        exported = export_path.read_text()
        assert "https://example.com/current-month-candidate" in exported
    finally:
        db.close()


def test_export_candidates_writes_header_only_csv_when_nothing_matches(tmp_path):
    db = IncidentDatabase(db_path=str(tmp_path / "incidents.db"))
    try:
        export_path = tmp_path / "candidates_10d.csv"
        db.export_candidates_to_csv(str(export_path), days=10)

        assert export_path.exists()
        assert export_path.read_text().strip() != ""
    finally:
        db.close()


def test_purge_old_data_deletes_expired_month_files_but_not_current(tmp_path):
    db = IncidentDatabase(db_path=str(tmp_path / "incidents.db"))
    try:
        candidates_dir = tmp_path / "candidates"
        # 250 days, not just past the 180-day cutoff -- purge is whole-file
        # (whole-month) granularity, so a month only qualifies once its
        # LAST day is past the cutoff too; a date only ~20 days past the
        # cutoff can still share a month with dates still inside the
        # window. 250 days leaves enough margin that the entire month is
        # unambiguously expired.
        expired_month = (datetime.now() - timedelta(days=250)).strftime("%Y-%m")
        # 40 days ago rather than 10 -- needs to land in a calendar month
        # distinct from both "now" (the active file) and the expired month,
        # so this test actually exercises three separate files.
        recent_month = (datetime.now() - timedelta(days=40)).strftime("%Y-%m")
        expired_path = _write_candidate_to_month_file(
            candidates_dir, expired_month, "https://example.com/expired", 250
        )
        recent_path = _write_candidate_to_month_file(
            candidates_dir, recent_month, "https://example.com/recent", 40
        )
        # Touch the current month so it exists on disk too.
        db.bulk_insert_candidates([{
            "url": "https://example.com/today",
            "title": "Reporter detained",
            "published_date": datetime.now().strftime("%Y-%m-%d"),
            "domain": "example.com", "source_country": "US", "language": "English",
            "matched_query": "live", "validation_status": "candidate",
            "validation_reason": "x", "evidence_text": "x",
        }])
        current_month = datetime.now().strftime("%Y-%m")
        current_path = candidates_dir / f"candidates_{current_month}.db"

        db.purge_old_data(days=180)

        assert not expired_path.exists()
        assert recent_path.exists()
        assert current_path.exists()
    finally:
        db.close()
