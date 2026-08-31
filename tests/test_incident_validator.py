import json
from pathlib import Path

import pytest

from incident_validator import validate_incident


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "articles.json"


@pytest.mark.parametrize("article", json.loads(FIXTURE_PATH.read_text()))
def test_validate_incident_fixture(article):
    result = validate_incident(article)

    assert result.status == article["expected"]


@pytest.mark.parametrize(
    ("article", "expected_status", "expected_type"),
    [
        (
            {
                "title": "Mexican journalist shot dead outside his home",
                "description": "",
            },
            "validated",
            "KILLING",
        ),
        (
            {
                "title": "Police detain reporter covering demonstration",
                "description": "",
            },
            "validated",
            "DETENTION",
        ),
        (
            {
                "title": "Sudanese journalists murdered after militia raid",
                "description": "",
            },
            "validated",
            "KILLING",
        ),
        (
            {
                "title": "Authorities arrest reporters covering the protest",
                "description": "",
            },
            "validated",
            "DETENTION",
        ),
        (
            {
                "title": "Newspaper office raided by security forces",
                "description": "",
            },
            "validated",
            "CENSORSHIP",
        ),
        (
            {
                "title": "Press conference held after deadly mine collapse",
                "description": "",
            },
            "rejected",
            None,
        ),
        (
            {
                "title": "Journalist writes about attacks on schools",
                "description": "",
            },
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
            "validated",
            "KILLING",
        ),
        (
            {
                "title": "AP first journalist killed in action was at the Battle of Little Bighorn 150 years ago",
                "description": "",
            },
            "candidate",
            None,
        ),
        (
            {
                "title": "Six Years Later, DNA Finally Identifies Body of Missing #EndSARS Reporter",
                "description": "",
            },
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
            "validated",
            "KILLING",
        ),
        # Real false positives found reviewing live CRITICAL alerts
        # (2026-08-26): MEDIA_SUBJECT_TERMS includes organizational nouns
        # (newspaper, broadcaster) that can legitimately be victims ("the
        # newspaper's office was raided") but far more often cite one --
        # "China's state broadcaster said at least three people were
        # killed" is a flood story, not a journalist-safety incident. Fixed
        # by extending SOURCE_ATTRIBUTION_PATTERNS to organizational roles,
        # not just person roles.
        (
            {
                "title": "",
                "description": "In Tibet, China's state broadcaster said at least three people were killed and 265 were missing.",
            },
            "rejected",
            None,
        ),
        (
            {
                "title": "",
                "description": "The newspaper \"Israel Hayom\" reported that two people were injured after a Hezbollah drone struck Misgav Am in the Galilee.",
            },
            "rejected",
            None,
        ),
        # Relational/possessive false positive: the media-subject term names
        # someone RELATED to the actual subject of the harm, not the harmed
        # person -- "the mother of NBC journalist Savannah Guthrie
        # disappeared" means Guthrie's mother disappeared, not Guthrie.
        (
            {
                "title": "",
                "description": "The 84-year-old mother of NBC journalist Savannah Guthrie disappeared from her Tucson, Arizona, home on January 31, 2026.",
            },
            "candidate",
            None,
        ),
        # Source-attribution pattern was too strict (required the reporting
        # verb to immediately follow the role noun) and missed real
        # modifier-phrase cases like this one, where the journalist is the
        # source describing OTHERS' arrests, not a detention victim
        # themselves.
        (
            {
                "title": "",
                "description": "A journalist in Baghdad told Iran International that the arrests included current and former members of parliament.",
            },
            "rejected",
            None,
        ),
        # Loosening that same pattern to fix the case above had to stop at a
        # comma, or it wrongly attaches a reporting verb belonging to a
        # different, distant clause: here "says" belongs to "Israel army"
        # from earlier in the sentence, not to "journalist" -- this is a
        # real validated KILLING (Al Jazeera's Ahmed Wishah) that a
        # comma-blind version of the fix above would have wrongly rejected.
        (
            {
                "title": "Israel army confirms killing of journalist in Gaza, says he was 'Hamas terrorist'",
                "description": "The Israeli military said Saturday it had carried out a strike that killed Al Jazeera journalist Ahmed Wishah in Gaza, saying he was a \"Hamas terrorist\".",
            },
            "validated",
            "KILLING",
        ),
    ],
)
def test_validate_incident_types(article, expected_status, expected_type):
    result = validate_incident(article)

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
        # Real false positive (2026-08-26): a flood story citing a
        # newspaper as its source ("según el periódico") was validating as
        # a DISAPPEARANCE incident -- "periódico" is in media_subject_terms
        # (can legitimately be a victim) but wasn't in the "según"
        # source-attribution pattern, so citing one as a source didn't
        # exclude the match the way citing a periodista/reportero already did.
        ("es", "Según el periódico Kathmandu Post, más de 934 personas siguen desaparecidas tras las inundaciones.", "rejected", None),

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

        # Turkish (added 2026-08-25, after es/pt/it/fr/ru): negates by
        # fusing a suffix into the verb itself (öldürüldü "was killed" ->
        # öldürülmedi "was not killed"), handled via negated_action_terms
        # instead of the negation_prefixes every other language uses -- see
        # language_terms.py.
        ("tr", "Gazeteci başkentte vurularak öldürüldü.", "validated", "KILLING"),
        ("tr", "Bir muhabir protesto sırasında polis tarafından gözaltına alındı.", "validated", "DETENTION"),
        ("tr", "Bir tanık gazetecilere konuştu: Oğlu saldırıda öldürüldü.", "rejected", None),
        ("tr", "Gazetecinin öldürülmesinin yıl dönümü, cezasızlığı hatırlatıyor.", "candidate", None),
        ("tr", "Gazeteci operasyon sırasında polise göre öldürülmedi.", "candidate", None),

        # No Arabic term list yet -- rejected rather than validated-or-not
        # (2026-08-26: unsupported languages now reject instead of being
        # capped at "candidate", see PLAN.md), the same gate every
        # unsupported language hits.
        ("arabic", "قُتل الصحفي على يد مسلحين في المدينة، وفقا لما أفاد به شهود محليون.", "rejected", None),
    ],
)
def test_validate_incident_multilanguage(language, text, expected_status, expected_type):
    result = validate_incident({"title": text, "description": "", "language": language})

    assert result.status == expected_status
    assert result.incident_type == expected_type


def test_build_negated_action_re_with_no_negation_config_never_matches():
    # A language with neither negation_prefixes nor negated_action_terms
    # set (Turkish, added for this mechanism, has the latter but not the
    # former) must not silently treat every sentence as negated:
    # "|".join([]) is "", and re.compile("") matches at position 0 of any
    # string, which would block every positive match for that language.
    from incident_validator import _build_negated_action_re
    from language_terms import LanguageTerms

    empty_terms = LanguageTerms(
        media_subject_terms=[],
        action_terms_by_type={},
        source_attribution_patterns=[],
        retrospective_patterns=[],
    )

    pattern = _build_negated_action_re(empty_terms)

    assert pattern.search("any text at all, including an empty string") is None
    assert pattern.search("") is None
