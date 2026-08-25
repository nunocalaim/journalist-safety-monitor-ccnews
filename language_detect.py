#!/usr/bin/env python3
"""
Language detection for article text.

trafilatura only exposes a `language` field when you pass it a
`target_language` -- and that same argument doubles as a filter: if the
detected language doesn't match, extract() raises internally and returns
None, silently discarding the article. That's the opposite of what we want
(we need to know an article's language, not drop everything that isn't
English), so detection is done here instead, decoupled from extraction.
"""

from __future__ import annotations

import py3langid as langid

MIN_TEXT_LENGTH = 20


def detect_language(text: str) -> str:
    """Best-effort ISO 639-1 code for `text`, or '' if too short to classify reliably."""
    if not text or len(text.strip()) < MIN_TEXT_LENGTH:
        return ''
    code, _ = langid.classify(text)
    return code
