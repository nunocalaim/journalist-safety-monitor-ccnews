#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Optional


@dataclass(frozen=True)
class IncidentValidation:
    status: str
    incident_type: Optional[str]
    severity: Optional[str]
    reason: str
    evidence_text: str = ""
    matched_subject: str = ""
    matched_action: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


MEDIA_SUBJECT_TERMS = [
    "student journalist",
    "student journalists",
    "journalism student",
    "journalism students",
    "student reporter",
    "student reporters",
    "campus journalist",
    "campus journalists",
    "campus reporter",
    "campus reporters",
    "photojournalist",
    "photojournalists",
    "video journalist",
    "video journalists",
    "media worker",
    "media workers",
    "press worker",
    "press workers",
    "news crew",
    "news crews",
    "camera operator",
    "camera operators",
    "cameraman",
    "cameramen",
    "videographer",
    "videographers",
    "war correspondent",
    "war correspondents",
    "foreign correspondent",
    "foreign correspondents",
    "correspondent",
    "correspondents",
    "journalist",
    "journalists",
    "reporter",
    "reporters",
    "editor",
    "editors",
    "columnist",
    "columnists",
    "broadcaster",
    "broadcasters",
    "newspaper",
    "newsroom",
    "news outlet",
    "radio station",
    "tv station",
    "television station",
]


ACTION_TERMS_BY_TYPE = {
    "KILLING": [
        "shot dead",
        "shot and killed",
        "stabbed to death",
        "beaten to death",
        "found dead",
        "killed",
        "murdered",
        "assassinated",
        "slain",
        "fatally shot",
        "fatally stabbed",
    ],
    "DETENTION": [
        "taken into custody",
        "placed in custody",
        "detained",
        "detain",
        "detains",
        "arrest",
        "arrested",
        "arrests",
        "jailed",
        "imprisoned",
        "sentenced",
        "held by police",
    ],
    "ATTACK": [
        "physically attacked",
        "violently attacked",
        "beaten",
        "assaulted",
        "attacked",
        "shot",
        "stabbed",
        "wounded",
        "injured",
        "abducted",
        "kidnapped",
        "tortured",
    ],
    "THREAT": [
        "death threat",
        "death threats",
        "threatened",
        "harassed",
        "intimidated",
        "stalked",
    ],
    "CENSORSHIP": [
        "raided",
        "censored",
        "banned",
        "blocked",
        "shut down",
        "suspended",
        "license revoked",
        "licence revoked",
    ],
    "DISAPPEARANCE": [
        "forcibly disappeared",
        "went missing",
        "missing",
        "disappeared",
    ],
}


SEVERITY_BY_TYPE = {
    "KILLING": "CRITICAL",
    "DISAPPEARANCE": "CRITICAL",
    "DETENTION": "HIGH",
    "ATTACK": "HIGH",
    "THREAT": "MEDIUM",
    "CENSORSHIP": "MEDIUM",
}


SOURCE_ATTRIBUTION_PATTERNS = [
    r"\b(?:journalist|reporter|correspondent|editor)\s+(?:reports?|reported|says?|said|writes?|wrote|claims?|claimed|told)\b",
    r"\baccording to\s+(?:a|an|the)?\s*(?:journalist|reporter|correspondent|editor)\b",
    r"\bmedia reports?\b",
    r"\bpress release\b",
    r"\bpress conference\b",
]


RETROSPECTIVE_PATTERNS = [
    r"\b\d+\s+(?:years?|months?)\s+(?:ago|later|on)\b",
    r"\b(?:anniversary|commemorates?|remembering|look back|looking back)\b",
    r"\b(?:on this day|this day in history|history|historical)\b",
    r"\b(?:identified body|finally identifies body|remains identified)\b",
    r"\b(?:first journalist killed|battle of little bighorn)\b",
]


def validate_incident(article: dict, matched_query: str = "") -> IncidentValidation:
    """
    Validate only the article-list text returned by GDELT.

    A GDELT query match can come from article body text that is not returned to
    this app, so query-only matches are candidates rather than incidents.
    """
    text = _article_text(article)
    if not text:
        return IncidentValidation(
            status="candidate",
            incident_type=None,
            severity=None,
            reason="no returned title/snippet text available",
        )

    sentences = _split_sentences(text)

    retrospective_sentence = _matching_sentence(sentences, _is_retrospective_context)
    if retrospective_sentence:
        return IncidentValidation(
            status="candidate",
            incident_type=None,
            severity=None,
            reason="returned text appears retrospective or historical",
            evidence_text=retrospective_sentence,
        )

    for sentence in sentences:
        positive = _find_positive_incident_frame(sentence)
        if positive:
            incident_type, subject, action = positive
            return IncidentValidation(
                status="validated",
                incident_type=incident_type,
                severity=SEVERITY_BY_TYPE[incident_type],
                reason="media subject and harm action found in returned text",
                evidence_text=sentence.strip(),
                matched_subject=subject,
                matched_action=action,
            )

    if _has_source_attribution(text) and _has_any_harm_action(text):
        return IncidentValidation(
            status="rejected",
            incident_type=None,
            severity=None,
            reason="media term appears to be source/attribution, not victim",
            evidence_text=_first_matching_sentence(sentences, _has_source_attribution),
        )

    if _has_source_attribution(text) and not _has_media_subject(text):
        return IncidentValidation(
            status="rejected",
            incident_type=None,
            severity=None,
            reason="source/attribution phrase found without media subject incident evidence",
            evidence_text=_first_matching_sentence(sentences, _has_source_attribution),
        )

    if _is_non_english(article):
        return IncidentValidation(
            status="candidate",
            incident_type=None,
            severity=None,
            reason="non-English returned text lacks English validation evidence",
            evidence_text=sentences[0].strip() if sentences else "",
        )

    if _has_any_harm_action(text) and not _has_media_subject(text):
        return IncidentValidation(
            status="rejected",
            incident_type=None,
            severity=None,
            reason="harm action found but no media subject in returned text",
            evidence_text=_first_matching_sentence(sentences, _has_any_harm_action),
        )

    if _has_media_subject(text):
        return IncidentValidation(
            status="candidate",
            incident_type=None,
            severity=None,
            reason="media subject found but no clear harm action in returned text",
            evidence_text=_first_matching_sentence(sentences, _has_media_subject),
        )

    if matched_query:
        return IncidentValidation(
            status="candidate",
            incident_type=None,
            severity=None,
            reason="query-only match; returned text lacks validation evidence",
        )

    return IncidentValidation(
        status="rejected",
        incident_type=None,
        severity=None,
        reason="no media subject or harm action found",
    )


def _article_text(article: dict) -> str:
    fields = [
        article.get("title", ""),
        article.get("description", ""),
        article.get("snippet", ""),
        article.get("summary", ""),
    ]
    return _normalize(" ".join(str(field) for field in fields if field))


def _is_non_english(article: dict) -> bool:
    language = str(article.get("language", "") or article.get("sourcelang", "")).strip().lower()
    return bool(language and language not in {"en", "eng", "english"})


def _normalize(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _split_sentences(text: str) -> list[str]:
    chunks = re.split(r"(?<=[.!?])\s+| \| | - ", text)
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _has_media_subject(text: str) -> bool:
    lowered = text.lower()
    return any(_term_in_text(term, lowered) for term in MEDIA_SUBJECT_TERMS)


def _has_any_harm_action(text: str) -> bool:
    lowered = text.lower()
    return any(
        _term_in_text(action, lowered)
        for actions in ACTION_TERMS_BY_TYPE.values()
        for action in actions
    )


def _has_source_attribution(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in SOURCE_ATTRIBUTION_PATTERNS)


def _is_retrospective_context(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in RETROSPECTIVE_PATTERNS)


def _find_positive_incident_frame(sentence: str) -> Optional[tuple[str, str, str]]:
    lowered = sentence.lower()

    if _has_source_attribution(lowered):
        return None

    for incident_type, actions in ACTION_TERMS_BY_TYPE.items():
        for subject in MEDIA_SUBJECT_TERMS:
            for action in actions:
                if not _term_in_text(subject, lowered) or not _term_in_text(action, lowered):
                    continue

                subject_re = _term_re(subject)
                action_re = _term_re(action)
                subject_before_action = re.search(
                    rf"{subject_re}(?:\W+\w+){{0,10}}\W+{action_re}",
                    lowered,
                )
                action_before_subject = re.search(
                    rf"{action_re}(?:\W+\w+){{0,8}}\W+{subject_re}",
                    lowered,
                )
                nominal_frame = re.search(
                    rf"\b(?:killing|murder|assassination|arrest|detention|attack|abduction|disappearance)\s+of\s+(?:a|an|the)?\s*{subject_re}",
                    lowered,
                )

                if subject_before_action or action_before_subject or nominal_frame:
                    return incident_type, subject, action

    return None


def _term_in_text(term: str, text: str) -> bool:
    return re.search(_term_re(term), text) is not None


def _term_re(term: str) -> str:
    escaped = re.escape(term.lower())
    escaped = escaped.replace(r"\ ", r"\s+")
    return rf"\b{escaped}\b"


def _first_matching_sentence(sentences: list[str], predicate) -> str:
    for sentence in sentences:
        if predicate(sentence):
            return sentence.strip()
    return sentences[0].strip() if sentences else ""


def _matching_sentence(sentences: list[str], predicate) -> str:
    for sentence in sentences:
        if predicate(sentence):
            return sentence.strip()
    return ""
