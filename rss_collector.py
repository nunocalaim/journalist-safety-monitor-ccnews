#!/usr/bin/env python3
"""
Polls RSS/Atom feeds for the outlets that block CCBot in robots.txt (see
PLAN.md's 2026-08-24 update) but publish a public feed instead. Feeds only
carry recent items -- no historical archive like CC-NEWS -- so this just
polls on a schedule and relies on the database's URL/fingerprint dedup to
skip articles already seen on a previous run.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse

import feedparser
import requests
import trafilatura

from sources import rss_domains

logger = logging.getLogger(__name__)

USER_AGENT = "JournalistSafetyMonitor-CCNews/1.0 (+https://github.com/nunocalaim/journalist-safety-monitor-ccnews)"

_TAG_RE = re.compile(r'<[^>]+>')


def _strip_html(text: str) -> str:
    return _TAG_RE.sub(' ', text or '').strip()


class RSSCollector:
    def __init__(self, config: Dict, timeout: Optional[int] = None, fetch_full_text: bool = True):
        rss_config = config.get('rss_collection', {})
        self.sources = rss_domains(config)
        self.timeout = timeout if timeout is not None else rss_config.get('request_timeout_seconds', 20)
        self.max_entries_per_feed = rss_config.get('max_entries_per_feed', 25)
        self.fetch_full_text = fetch_full_text
        self.session = requests.Session()
        self.session.headers['User-Agent'] = USER_AGENT
        self.last_feeds_polled = 0

    def collect(self) -> List[Dict]:
        articles: List[Dict] = []
        self.last_feeds_polled = 0
        for source in self.sources:
            if not source.feed_url:
                continue
            try:
                articles.extend(self._collect_feed(source))
                self.last_feeds_polled += 1
            except Exception as e:
                logger.error("Failed to poll feed for %s: %s", source.domain, e)
        return articles

    def _collect_feed(self, source) -> List[Dict]:
        logger.info("Polling RSS feed for %s: %s", source.domain, source.feed_url)
        parsed = feedparser.parse(source.feed_url, agent=USER_AGENT)
        if parsed.bozo and not parsed.entries:
            logger.warning("Feed for %s did not parse: %s", source.domain, parsed.get('bozo_exception'))
            return []

        feed_language = parsed.feed.get('language', '') or ''

        articles = []
        for entry in parsed.entries[:self.max_entries_per_feed]:
            url = entry.get('link', '')
            if not url:
                continue

            summary = _strip_html(entry.get('summary', ''))
            text = summary
            if self.fetch_full_text and source.fetch_full_text:
                full_text = self._fetch_full_text(url)
                if full_text:
                    text = full_text

            articles.append({
                'url': url,
                'title': entry.get('title', ''),
                'description': text,
                'domain': source.domain,
                'country': source.country,
                'language': feed_language,
                'published_date': entry.get('published', '') or entry.get('updated', ''),
                'source': 'rss',
            })

        logger.info("Fetched %d entries from %s", len(articles), source.domain)
        return articles

    def _fetch_full_text(self, url: str) -> Optional[str]:
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning("Could not fetch article page %s: %s", url, e)
            return None

        extracted = trafilatura.extract(resp.text, url=url)
        return extracted or None

    def close(self) -> None:
        self.session.close()
