#!/usr/bin/env python3
"""
Phase 2 spike (see PLAN.md): confirm incident_validator.py -- tuned against
short GDELT titles/snippets -- still behaves correctly when given full
article body text extracted from CC-NEWS HTML, not just a title.

Not part of the production pipeline. Deliberately throwaway/inline.
"""

from incident_validator import validate_incident

# Negative controls: real full text extracted from today's CC-NEWS sample in
# spike_ccnews_collector.py. Neither is a journalist-safety incident -- both
# should stay rejected/candidate even with thousands of characters of
# unrelated surrounding prose.
NZ_SOCIAL_MEDIA_TEXT = (
    "WELLINGTON (dpa-AFX) - Die Partei von Neuseelands Regierungschef "
    "Christopher Luxon will den Zugang Jugendlicher unter 16 Jahren zu "
    "sozialen Medien beschraenken. Bildungsministerin Erica Stanford "
    "kuendigte am Montag einen entsprechenden Gesetzentwurf an. Wir "
    "schuetzen Kinder in der realen Welt vor Gefahren, das sollte auch "
    "online gelten, sagte sie in einem Interview. Der Vorschlag orientiert "
    "sich an einem aehnlichen Gesetz in Australien."
)

STOCK_PICKS_TEXT = (
    "As long as geopolitical uncertainty remains, volatility will be an "
    "inevitable part of the equity market. In such a scenario, stick with "
    "domestic-focused stocks that hold the promise of growth and are far "
    "removed from global supply chain disruptions. Analysts recommend "
    "reviewing quarterly earnings before making a decision."
)

# Positive control: a realistic full-length article body (not a short
# title) with the incident sentence buried in the middle, to prove sentence
# splitting + proximity matching still finds it in a longer document.
JOURNALIST_KILLED_ARTICLE = (
    "GAZIANTEP (Reuters) - Local authorities said Tuesday that a curfew "
    "remains in effect in the border region following days of unrest. "
    "Officials have not commented on the extent of damage to "
    "infrastructure. A photojournalist was shot dead while covering "
    "clashes near the market district on Monday afternoon, according to "
    "his employer and two witnesses. The health ministry said at least "
    "twelve other people were wounded in the same incident. International "
    "press freedom groups called for an independent investigation into "
    "the shooting. The regional governor's office did not respond to "
    "requests for comment by the time of publication."
)

# Retrospective control: should NOT validate even though it contains both a
# media-subject term and a harm-action term, because it's framed as history.
RETROSPECTIVE_ARTICLE = (
    "Twenty years ago this week, a war correspondent was killed while "
    "reporting from the front lines, an event that shaped a generation of "
    "conflict journalism. On this day in history, colleagues gathered to "
    "remember his work and legacy."
)


def run(label: str, text: str) -> None:
    result = validate_incident({"title": "", "description": text})
    print(f"{label}: status={result.status} type={result.incident_type} reason={result.reason!r}")


if __name__ == "__main__":
    run("NZ social media (expect rejected/candidate)", NZ_SOCIAL_MEDIA_TEXT)
    run("Stock picks (expect rejected/candidate)", STOCK_PICKS_TEXT)
    run("Journalist killed, buried in long article (expect validated/KILLING)", JOURNALIST_KILLED_ARTICLE)
    run("Retrospective anniversary piece (expect candidate, not validated)", RETROSPECTIVE_ARTICLE)
