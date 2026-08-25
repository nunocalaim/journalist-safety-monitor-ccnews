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
        # Spanish now has its own term list (2026-08-25 language support --
        # see PLAN.md and language_terms.py), so this validates instead of
        # being capped at "candidate" the way any other non-English text
        # still is below.
        (
            {
                "title": "Periodista asesinado en Mexico",
                "description": "",
                "language": "Spanish",
            },
            "near10:\"journalist killed\"",
            "validated",
            "KILLING",
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


# 2026-08-25 language support (see PLAN.md, language_terms.py): each of
# Spanish, Portuguese, Italian, French, and Russian gets the same shape of
# regression coverage as English above -- a validated killing, a validated
# detention, a source-attribution rejection, a retrospective candidate, and
# a negated-action candidate -- to confirm the per-language term/negation
# dispatch actually produces validated/rejected outcomes, not just "doesn't
# crash". A final case confirms a language with no term list yet (Arabic)
# still gets capped at "candidate" the way every non-English language did
# before this support was added.
@pytest.mark.parametrize(
    ("language", "text", "expected_status", "expected_type"),
    [
        ("es", "Periodista fue asesinado a tiros en la capital", "validated", "KILLING"),
        ("es", "Un reportero fue detenido por la policía durante la protesta", "validated", "DETENTION"),
        ("es", "Una testigo dijo a los reporteros que su hijo fue asesinado en el ataque.", "rejected", None),
        ("es", "A un año del asesinato de la periodista, sigue sin justicia.", "candidate", None),
        ("es", "El periodista no fue asesinado durante la redada, según la policía.", "candidate", None),

        ("pt", "Jornalista foi assassinado a tiros na capital.", "validated", "KILLING"),
        ("pt", "Um repórter foi detido pela polícia durante o protesto.", "validated", "DETENTION"),
        ("pt", "Uma testemunha disse aos jornalistas que seu filho foi assassinado no ataque.", "rejected", None),
        ("pt", "Um ano depois do assassinato da jornalista, a justiça segue ausente.", "candidate", None),
        ("pt", "O jornalista não foi assassinado durante a operação, segundo a polícia.", "candidate", None),

        ("it", "Il giornalista è stato ucciso a colpi di arma da fuoco nella capitale.", "validated", "KILLING"),
        ("it", "Un cronista è stato arrestato dalla polizia durante la protesta.", "validated", "DETENTION"),
        ("it", "Un testimone ha detto ai giornalisti che suo figlio è stato ucciso nell'attacco.", "rejected", None),
        ("it", "Ad un anno dall'omicidio della giornalista, la giustizia resta assente.", "candidate", None),
        ("it", "Il giornalista non è stato ucciso durante l'operazione, secondo la polizia.", "candidate", None),

        ("fr", "Le journaliste a été tué par balles dans la capitale.", "validated", "KILLING"),
        ("fr", "Un correspondant a été arrêté par la police pendant la manifestation.", "validated", "DETENTION"),
        ("fr", "Un témoin a dit aux journalistes que son fils a été tué dans l'attaque.", "rejected", None),
        ("fr", "Un an après l'assassinat du journaliste, la justice reste absente.", "candidate", None),
        ("fr", "Le journaliste n'a pas été tué pendant l'opération, selon la police.", "candidate", None),

        ("ru", "Журналист был застрелен в столице.", "validated", "KILLING"),
        ("ru", "Репортёр был задержан полицией во время протеста.", "validated", "DETENTION"),
        ("ru", "Свидетель сказал журналистам, что его сын был убит в ходе нападения.", "rejected", None),
        ("ru", "Годовщина смерти журналиста напоминает о безнаказанности.", "candidate", None),
        ("ru", "Журналист не был убит во время операции, по данным полиции.", "candidate", None),

        # No Arabic term list yet -- still capped at "candidate", same
        # graceful-degradation gate every unsupported language uses.
        ("arabic", "قُتل الصحفي على يد مسلحين في المدينة، وفقا لما أفاد به شهود محليون.", "candidate", None),
    ],
)
def test_validate_incident_multilanguage(language, text, expected_status, expected_type):
    result = validate_incident({"title": text, "description": "", "language": language})

    assert result.status == expected_status
    assert result.incident_type == expected_type
