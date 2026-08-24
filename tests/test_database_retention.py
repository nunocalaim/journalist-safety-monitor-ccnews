from datetime import datetime, timedelta

from database import IncidentDatabase


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
                "validation_reason": "non-English returned text lacks English validation evidence",
                "evidence_text": "Periodista asesinado en Mexico",
            }
        ])
        export_path = tmp_path / "candidates_10d.csv"

        db.export_candidates_to_csv(str(export_path), days=10)

        exported = export_path.read_text()
        assert "https://example.com/candidate" in exported
        assert "non-English returned text" in exported
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
                "validation_reason": "non-English returned text lacks English validation evidence",
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
