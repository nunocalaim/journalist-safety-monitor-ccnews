#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Dict, List, Optional

from language_terms import LANGUAGE_ALIASES, LANGUAGE_TERMS as _TRANSLATED_LANGUAGE_TERMS, LanguageTerms


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
    # A small filler window (0-3 words) between the role noun and the verb --
    # real text often inserts a modifier ("journalist in Baghdad told...",
    # "reporter who witnessed the attack said...") that a strict \s+
    # adjacency requirement misses. Found 2026-08-26: 7 real incidents all
    # sharing "A journalist in Baghdad told Iran International..." (the
    # journalist is the source describing others' arrests, not a victim)
    # slipped through because "in Baghdad" broke the old immediate-adjacency
    # pattern.
    # Filler tokens must not cross a comma -- "journalist in Baghdad told" is
    # one clause (journalist is the subject of "told"), but "journalist in
    # Gaza, says he was..." has "says" belonging to a subject several words
    # further back (Israel's military), not "journalist" -- the comma marks
    # that clause boundary. Found and fixed together 2026-08-26: loosening
    # this from strict \s+ adjacency to fix the Baghdad-shaped cases first
    # broke this Gaza one, which is how the comma restriction was found.
    r"\b(?:journalist|reporter|correspondent|editor)(?:\s+[^\s,]+){0,3}\s+(?:reports?|reported|says?|said|writes?|wrote|claims?|claimed|told)\b",
    r"\baccording to\s+(?:a|an|the)?\s*(?:journalist|reporter|correspondent|editor)\b",
    # Object-position phrasing ("X told reporters that Y was killed") -- the
    # subject-first pattern above misses this, and it's common in full
    # article body text (rare in short titles, where this was first tuned).
    r"\btold\s+(?:reporters?|journalists?|correspondents?|the (?:press|media))\b",
    r"\bspoke\s+to\s+(?:reporters?|journalists?|correspondents?|the (?:press|media))\b",
    r"\b(?:said|says?)\s+to\s+(?:reporters?|journalists?)\b",
    r"\bmedia reports?\b",
    r"\bpress release\b",
    r"\bpress conference\b",
    # Organizational source terms (newspaper/broadcaster/outlet) cited as the
    # SOURCE of a report, not its subject -- e.g. "China's state broadcaster
    # said at least three people were killed" (a flood story, nothing to do
    # with journalists) or "the newspaper 'Israel Hayom' reported that two
    # people were injured" (a drone strike). These org nouns are also in
    # MEDIA_SUBJECT_TERMS because they can legitimately be victims ("the
    # newspaper's office was raided"), so this has to be attribution-shaped
    # (org term immediately driving a reporting verb) to disambiguate, not a
    # blanket exclusion. Found 2026-08-26: 15 real false positives across a
    # Nepal/Tibet flood story cluster, a drone-strike story, and 7 duplicate
    # Iran International articles all containing the same boilerplate
    # paragraph about a shipping-lane closure misread as CENSORSHIP.
    r"\b(?:newspaper|broadcasters?|news outlet|radio station|tv station|television station)\b(?:\s+[^\s,]+){0,5}\s+(?:reports?|reported|says?|said|writes?|wrote|claims?|claimed|confirms?|confirmed|states?|stated|notes?|noted)\b",
]


RETROSPECTIVE_PATTERNS = [
    r"\b(?:\d+|a|an|one)\s+(?:years?|months?)\s+(?:ago|later|on|after)\b",
    # Headline-style elliptical phrasing that drops the leading article,
    # e.g. "Year after Israeli strikes killed journalists..." -- common
    # enough in real headlines to be worth its own pattern rather than
    # relying on "a year after" always being spelled out.
    r"^\s*years?\s+after\b",
    r"\bit'?s been\s+(?:\d+|a|an|one)\s+(?:years?|months?)\s+since\b",
    r"\b(?:anniversary|commemorates?|remembering|look back|looking back)\b",
    r"\b(?:on this day|this day in history|history|historical)\b",
    r"\b(?:identified body|finally identifies body|remains identified)\b",
    r"\b(?:first journalist killed|battle of little bighorn)\b",
]

# Sentence-level exclusions: the sentence contains a media-subject term and
# a harm-action term close together, but not describing harm TO that
# subject. Two real shapes found 2026-08-26:
ENGLISH_EXCLUSION_PATTERNS = [
    # Relational/possessive: the media-subject term names someone RELATED
    # to the actual subject of the harm, not the harmed person themselves --
    # "the mother of NBC journalist Savannah Guthrie disappeared" means
    # Guthrie's mother disappeared, not Guthrie. 5 real duplicate incidents
    # (same ongoing story, re-collected across days) all matched "journalist"
    # + "disappeared"/"missing" this way.
    r"\b(?:mother|father|wife|husband|son|daughter|sister|brother|parent|relative|family member)s?\s+of(?:\s+(?:a|an|the))?(?:\s+[^\s,]+){0,3}\s+(?:journalist|reporter|correspondent|editor|photojournalist)\b",
    r"\b(?:journalist|reporter|correspondent|editor|photojournalist)(?:'s|s')\s+(?:mother|father|wife|husband|son|daughter|sister|brother|parent|relative)\b",
    # Word-sense: "missing" as in emotionally longing for someone, not
    # physically disappeared -- "journalists ran stories that Kasab was
    # missing his sister" is about homesickness, not a disappearance.
    r"\bmissing\s+(?:his|her|their|my|your)\s+(?:mother|father|sister|brother|wife|husband|family|home|children|kids|parents)\b",
]

# Negation attached directly to a harm-action term flips its meaning (e.g.
# "didn't harm them", "was never attacked"). Deliberately narrow: only
# triggers when the negation is immediately followed by a recognized
# action-like word, not just anywhere nearby in the sentence -- an earlier,
# broader "negation somewhere near the match" version incorrectly rejected
# "journalist shot dead, police have not named a suspect" (unrelated
# negation later in the sentence, about the investigation, not the killing).
# This structure -- a negator fragment, then a small filler window, then
# a recognized action term -- is shared across languages (see
# language_terms.py's negation_prefixes), so it's built once by
# _build_negated_action_re() below and reused for every language, English
# included.
ENGLISH_NEGATION_PREFIXES = [
    r"\b(?:did|does|do|has|have|had|is|are|was|were|will|wo|can|could|would|should)\s*(?:n['’]?t|not)",
    r"\bnever",
    r"\bno longer",
]
ENGLISH_EXTRA_NEGATABLE_ACTIONS = ["harm", "harmed", "hurt", "injure"]

# The "killing of a journalist"-style nominal frame ("harm-noun of subject")
# is only implemented for English for now -- it's a bonus pattern on top of
# the subject/action proximity match below, not required for basic
# validation, so it's not worth translating in this first non-English pass.
ENGLISH_NOMINAL_FRAME_PATTERN = (
    r"\b(?:killing|murder|assassination|arrest|detention|attack|abduction|disappearance)"
    r"\s+of\s+(?:a|an|the)?\s*{subject}"
)


@dataclass(frozen=True)
class _CompiledLanguage:
    terms: LanguageTerms
    negated_action_re: re.Pattern
    nominal_frame_pattern: Optional[str] = None


def _term_re(term: str) -> str:
    escaped = re.escape(term.lower())
    escaped = escaped.replace(r"\ ", r"\s+")
    return rf"\b{escaped}\b"


def _term_in_text(term: str, text: str) -> bool:
    return re.search(_term_re(term), text) is not None


def _build_negated_action_re(terms: LanguageTerms) -> re.Pattern:
    actions = sorted(
        {action for actions in terms.action_terms_by_type.values() for action in actions}
        | set(terms.extra_negatable_actions),
        key=len,
        reverse=True,
    )
    actions_re = "|".join(re.escape(a).replace(r"\ ", r"\s+") for a in actions)
    alternatives = [
        rf"{prefix}(?:\s+\w+){{0,2}}\s+(?:{actions_re})\b" for prefix in terms.negation_prefixes
    ]
    # Languages that negate by fusing the negation into the verb itself
    # (Turkish: öldürüldü "was killed" -> öldürülmedi "was not killed") have
    # no preceding word to anchor a prefix+window match against, so they
    # list the fully-inflected negated forms directly instead.
    alternatives += [_term_re(term) for term in terms.negated_action_terms]
    if not alternatives:
        # `"|".join([])` is "", and re.compile("") matches every position in
        # any string -- which would make every sentence look "negated" and
        # silently block all validation for a language with neither
        # mechanism configured. Use a pattern that never matches instead.
        return re.compile(r"(?!)")
    return re.compile("|".join(alternatives))


def _compile_language(terms: LanguageTerms, nominal_frame_pattern: Optional[str] = None) -> _CompiledLanguage:
    return _CompiledLanguage(
        terms=terms,
        negated_action_re=_build_negated_action_re(terms),
        nominal_frame_pattern=nominal_frame_pattern,
    )


_ENGLISH_TERMS = LanguageTerms(
    media_subject_terms=MEDIA_SUBJECT_TERMS,
    action_terms_by_type=ACTION_TERMS_BY_TYPE,
    source_attribution_patterns=SOURCE_ATTRIBUTION_PATTERNS,
    retrospective_patterns=RETROSPECTIVE_PATTERNS,
    negation_prefixes=ENGLISH_NEGATION_PREFIXES,
    extra_negatable_actions=ENGLISH_EXTRA_NEGATABLE_ACTIONS,
    exclusion_patterns=ENGLISH_EXCLUSION_PATTERNS,
)

# Language code -> compiled term set. "en" plus the 2026-08-25 non-English
# addition (see PLAN.md and language_terms.py). Any language not in this
# dict falls back to the pre-2026-08-25 behavior: validated against English
# terms only (in case metadata is wrong/missing but the text is actually
# English) and capped at "candidate" if it looks non-English (see
# _is_language_supported below).
LANGUAGES: Dict[str, _CompiledLanguage] = {
    "en": _compile_language(_ENGLISH_TERMS, nominal_frame_pattern=ENGLISH_NOMINAL_FRAME_PATTERN),
    **{code: _compile_language(terms) for code, terms in _TRANSLATED_LANGUAGE_TERMS.items()},
}

_ENGLISH_ALIASES = {"", "en", "eng", "english"}


def validate_incident(article: dict) -> IncidentValidation:
    """
    Validate the full extracted article text (title + body).

    Note: this originally took a `matched_query` argument, from when this
    validator was shared with the GDELT-based sibling repo -- there, a
    keyword-search match on a title/snippet with no other evidence was
    genuinely ambiguous (the full article, which GDELT doesn't return, might
    have confirmed it), so it was treated as a candidate rather than
    rejected. This repo already validates the full extracted article body,
    not a snippet, so "matched_query" carried no real signal here -- both
    CC-NEWS and RSS collectors always set it to a constant per-domain label,
    never a real search match -- and "no evidence anywhere in the full
    text" is a confident rejection, not genuine uncertainty. Removed
    2026-08-26 (see PLAN.md); see git history if the GDELT-style behavior
    is ever needed again.
    """
    text = _article_text(article)
    if not text:
        return IncidentValidation(
            status="candidate",
            incident_type=None,
            severity=None,
            reason="no returned title/snippet text available",
        )

    language_code = _article_language(article)
    supported = language_code in LANGUAGES or language_code in _ENGLISH_ALIASES
    compiled = LANGUAGES.get(language_code, LANGUAGES["en"])

    sentences = _split_sentences(text)

    retrospective_sentence = _matching_sentence(
        sentences, lambda s: _is_retrospective_context(s, compiled.terms)
    )
    if retrospective_sentence:
        return IncidentValidation(
            status="candidate",
            incident_type=None,
            severity=None,
            reason="returned text appears retrospective or historical",
            evidence_text=retrospective_sentence,
        )

    for sentence in sentences:
        positive = _find_positive_incident_frame(sentence, compiled)
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

    if _has_source_attribution(text, compiled.terms) and _has_any_harm_action(text, compiled.terms):
        return IncidentValidation(
            status="rejected",
            incident_type=None,
            severity=None,
            reason="media term appears to be source/attribution, not victim",
            evidence_text=_first_matching_sentence(
                sentences, lambda s: _has_source_attribution(s, compiled.terms)
            ),
        )

    if _has_source_attribution(text, compiled.terms) and not _has_media_subject(text, compiled.terms):
        return IncidentValidation(
            status="rejected",
            incident_type=None,
            severity=None,
            reason="source/attribution phrase found without media subject incident evidence",
            evidence_text=_first_matching_sentence(
                sentences, lambda s: _has_source_attribution(s, compiled.terms)
            ),
        )

    if not supported:
        return IncidentValidation(
            status="rejected",
            incident_type=None,
            severity=None,
            reason="unsupported language; no term list to validate against yet",
            evidence_text=sentences[0].strip() if sentences else "",
        )

    if _has_any_harm_action(text, compiled.terms) and not _has_media_subject(text, compiled.terms):
        return IncidentValidation(
            status="rejected",
            incident_type=None,
            severity=None,
            reason="harm action found but no media subject in returned text",
            evidence_text=_first_matching_sentence(
                sentences, lambda s: _has_any_harm_action(s, compiled.terms)
            ),
        )

    if _has_media_subject(text, compiled.terms):
        return IncidentValidation(
            status="candidate",
            incident_type=None,
            severity=None,
            reason="media subject found but no clear harm action in returned text",
            evidence_text=_first_matching_sentence(
                sentences, lambda s: _has_media_subject(s, compiled.terms)
            ),
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


def _article_language(article: dict) -> str:
    raw = str(article.get("language", "") or article.get("sourcelang", "")).strip().lower()
    return LANGUAGE_ALIASES.get(raw, raw)


def _normalize(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _split_sentences(text: str) -> list[str]:
    chunks = re.split(r"(?<=[.!?])\s+| \| | - ", text)
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _has_media_subject(text: str, terms: LanguageTerms) -> bool:
    lowered = text.lower()
    return any(_term_in_text(term, lowered) for term in terms.media_subject_terms)


def _has_any_harm_action(text: str, terms: LanguageTerms) -> bool:
    lowered = text.lower()
    return any(
        _term_in_text(action, lowered)
        for actions in terms.action_terms_by_type.values()
        for action in actions
    )


def _has_source_attribution(text: str, terms: LanguageTerms) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in terms.source_attribution_patterns)


def _has_exclusion(text: str, terms: LanguageTerms) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in terms.exclusion_patterns)


def _is_retrospective_context(text: str, terms: LanguageTerms) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in terms.retrospective_patterns)


def _find_positive_incident_frame(sentence: str, compiled: _CompiledLanguage) -> Optional[tuple[str, str, str]]:
    terms = compiled.terms
    lowered = sentence.lower()

    if _has_source_attribution(lowered, terms) or _has_exclusion(lowered, terms):
        return None

    for incident_type, actions in terms.action_terms_by_type.items():
        for subject in terms.media_subject_terms:
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
                nominal_frame = None
                if compiled.nominal_frame_pattern:
                    nominal_frame = re.search(
                        compiled.nominal_frame_pattern.format(subject=subject_re),
                        lowered,
                    )

                if subject_before_action or action_before_subject or nominal_frame:
                    if compiled.negated_action_re.search(lowered):
                        continue
                    return incident_type, subject, action

    return None


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
