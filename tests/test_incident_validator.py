import json
from pathlib import Path

import pytest

from incident_validator import validate_incident


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "articles.json"


@pytest.mark.parametrize("article", json.loads(FIXTURE_PATH.read_text()))
def test_validate_incident_fixture(article):
    result = validate_incident(article, matched_query=article.get("query", ""))

    assert result.status == article["expected"]


@pytest.mark.parametrize(
    ("article", "query", "expected_status", "expected_type"),
    [
        (
            {
                "title": "Mexican journalist shot dead outside his home",
                "description": "",
            },
            "journalist killed",
            "validated",
            "KILLING",
        ),
        (
            {
                "title": "Police detain reporter covering demonstration",
                "description": "",
            },
            "reporter detained",
            "validated",
            "DETENTION",
        ),
        (
            {
                "title": "Sudanese journalists murdered after militia raid",
                "description": "",
            },
            "journalists killed",
            "validated",
            "KILLING",
        ),
        (
            {
                "title": "Authorities arrest reporters covering the protest",
                "description": "",
            },
            "reporters detained",
            "validated",
            "DETENTION",
        ),
        (
            {
                "title": "Newspaper office raided by security forces",
                "description": "",
            },
            "newspaper raided",
            "validated",
            "CENSORSHIP",
        ),
        (
            {
                "title": "Press conference held after deadly mine collapse",
                "description": "",
            },
            "press killed",
            "rejected",
            None,
        ),
        (
            {
                "title": "Journalist writes about attacks on schools",
                "description": "",
            },
            "journalist attacked",
            "candidate",
            None,
        ),
        (
            {
                "title": "Periodista asesinado en Mexico",
                "description": "",
                "language": "Spanish",
            },
            "near10:\"journalist killed\"",
            "candidate",
            None,
        ),
        (
            {
                "title": "AP first journalist killed in action was at the Battle of Little Bighorn 150 years ago",
                "description": "",
            },
            'near10:"journalist killed"',
            "candidate",
            None,
        ),
        (
            {
                "title": "Six Years Later, DNA Finally Identifies Body of Missing #EndSARS Reporter",
                "description": "",
            },
            'near10:"journalist detained"',
            "candidate",
            None,
        ),
    ],
)
def test_validate_incident_types(article, query, expected_status, expected_type):
    result = validate_incident(article, matched_query=query)

    assert result.status == expected_status
    assert result.incident_type == expected_type
