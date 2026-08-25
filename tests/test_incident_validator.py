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
        # Real false positives found running against CC-NEWS/RSS full article
        # text (2026-08-24): "X told reporters that Y was killed/attacked" is
        # common in full-length body text and was missed by the
        # subject-first-only SOURCE_ATTRIBUTION_PATTERNS regex, which only
        # caught "reporter told/said X", not "X told reporters".
        (
            {
                "title": "Landslide at waste mound in Guinea capital kills 30, government says",
                "description": (
                    "One woman, Cire Diallo, told reporters at the scene "
                    "that her five children were killed."
                ),
            },
            "",
            "rejected",
            None,
        ),
        (
            {
                "title": "Trump lashes out after US-Canada talks devolve into trade war",
                "description": (
                    "\"You're at war when you're attacked, and we got "
                    "attacked,\" the Canadian prime minister told reporters "
                    "in Ottawa."
                ),
            },
            "",
            "rejected",
            None,
        ),
        # Headline-style anniversary phrasing ("Year after X", "it's been a
        # year since X") -- the original RETROSPECTIVE_PATTERNS only caught
        # numeric forms like "6 years later".
        (
            {
                "title": (
                    "Year after Israeli strikes killed journalists at "
                    "hospital, no one has been held accountable"
                ),
                "description": (
                    "It's been a year since Israeli soldiers killed 22 "
                    "Palestinians, including journalists and rescue "
                    "workers, in a double strike on a hospital in Gaza."
                ),
            },
            "",
            "candidate",
            None,
        ),
        # Negation directly attached to a harm-action term flips its
        # meaning; the validator originally had no negation handling.
        (
            {
                "title": "",
                "description": (
                    "Traditionally the KGB harassed and intimidated "
                    "foreign reporters, but did not harm them."
                ),
            },
            "",
            "candidate",
            None,
        ),
        # Negation elsewhere in the sentence, about something unrelated to
        # the harm action, must NOT suppress a real positive match -- a
        # first attempt at the negation fix (window-based, not
        # action-attached) regressed exactly this case.
        (
            {
                "title": "Journalist shot dead, police have not named a suspect",
                "description": "",
            },
            "",
            "validated",
            "KILLING",
        ),
    ],
)
def test_validate_incident_types(article, query, expected_status, expected_type):
    result = validate_incident(article, matched_query=query)

    assert result.status == expected_status
    assert result.incident_type == expected_type
