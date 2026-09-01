#!/usr/bin/env python3
"""
Queries GDELT's DOC 2.0 API (keyword search over a huge, uncontrolled slice
of the web) and, for each hit, fetches the full article page ourselves
before validating -- see PLAN.md's 2026-09-01 update for why: GDELT's API
only ever returns a title (confirmed against a live query -- no body text,
no snippet field at all), and this repo's validator was deliberately built
around always having full article text. Fetching it ourselves makes GDELT
"just another URL source" feeding the same full-text pipeline CC-NEWS and
RSS already use, rather than a second, structurally weaker-evidence path.
If the fetch fails, this falls back to GDELT's own title text rather than
dropping the article -- same graceful-degradation shape as RSSCollector's
feed-summary fallback.

Query construction and the API wrapper itself are ported from
RoyKrovel/journalist-safety-monitor's journalist_safety_monitor.py
(GDELTAPIWrapper, build_gdelt_queries) -- both already solid and
battle-tested there: no API key needed (GDELT's DOC API is public), and
the wrapper already handles 429 rate-limiting with backoff.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

import requests
import trafilatura

from language_detect import detect_language

logger = logging.getLogger(__name__)

USER_AGENT = "JournalistSafetyMonitor-CCNews/1.0 (+https://github.com/nunocalaim/journalist-safety-monitor-ccnews)"

GDELT_BASE_URL = "http://api.gdeltproject.org/api/v2/doc/doc"


def build_gdelt_queries(config: Dict, lookback_days: Optional[int] = None) -> List[Dict]:
    gdelt_config = config.get('gdelt_queries', {})
    lookback_days = lookback_days or config.get('lookback_days', 1)
    proximity_distance = gdelt_config.get('proximity_distance', 10)
    max_results = gdelt_config.get('max_results_per_query', 50)

    subject_terms = gdelt_config.get('subject_terms', [])
    action_terms = gdelt_config.get('action_terms', [])
    keywords = [
        f'near{proximity_distance}:"{subject} {action}"'
        for subject in subject_terms
        for action in action_terms
    ]
    keywords.extend(gdelt_config.get('exact_queries', []))
    keywords.extend(gdelt_config.get('context_queries', []))

    # Preserve order while avoiding accidental duplicate API calls.
    unique_keywords = list(dict.fromkeys(keywords))

    return [
        {
            "description": keyword,
            "params": {
                "keyword": keyword,
                "timespan": f"{lookback_days}d",
                "max_results": max_results,
            },
        }
        for keyword in unique_keywords
    ]


class GDELTAPIWrapper:
    def __init__(self, timeout: int = 30, max_retries: int = 1, retry_backoff_seconds: int = 60):
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.session = requests.Session()

    def search_articles(self, params: Dict) -> Dict:
        keyword = params.get('keyword', '')
        timespan = params.get('timespan', '1d')
        max_results = min(params.get('max_results', 50), 250)

        if not keyword:
            logger.error("Keyword is required")
            return {'articles': []}

        request_params = {
            'query': keyword,
            'mode': 'artlist',
            'maxrecords': max_results,
            'timespan': timespan,
            'format': 'json',
        }
        logger.info("GDELT API: %s... timespan=%s", keyword, timespan)

        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(GDELT_BASE_URL, params=request_params, timeout=self.timeout)

                if response.status_code == 429 and attempt < self.max_retries:
                    wait_seconds = self._retry_wait_seconds(response, attempt)
                    logger.warning("GDELT rate limited request; retrying in %ds", wait_seconds)
                    time.sleep(wait_seconds)
                    continue

                response.raise_for_status()
                data = response.json()
                articles = data.get('articles', [])
                logger.info("Retrieved %d articles", len(articles))
                return {'articles': articles}

            except requests.RequestException as e:
                if attempt < self.max_retries:
                    wait_seconds = self.retry_backoff_seconds * (2 ** attempt)
                    logger.warning("GDELT request failed; retrying in %ds: %s", wait_seconds, e)
                    time.sleep(wait_seconds)
                    continue

                logger.error("GDELT API error: %s", e)
                return {'articles': []}
            except ValueError as e:
                logger.error("GDELT API JSON error: %s", e)
                return {'articles': []}

        return {'articles': []}

    def _retry_wait_seconds(self, response: requests.Response, attempt: int) -> int:
        retry_after = response.headers.get('Retry-After')
        if retry_after and retry_after.isdigit():
            return int(retry_after)
        return self.retry_backoff_seconds * (2 ** attempt)

    def close(self) -> None:
        self.session.close()


class GDELTCollector:
    def __init__(
        self,
        config: Dict,
        shard_count: int = 1,
        shard_index: int = 0,
        timeout: Optional[int] = None,
    ):
        gdelt_config = config.get('gdelt_queries', {})
        self.config = config
        self.shard_count = max(shard_count, 1)
        self.shard_index = shard_index % self.shard_count
        self.rate_limit_seconds = gdelt_config.get('rate_limit_seconds', 30)

        self.api = GDELTAPIWrapper(
            timeout=gdelt_config.get('request_timeout_seconds', 30),
            max_retries=gdelt_config.get('max_retries', 2),
            retry_backoff_seconds=gdelt_config.get('retry_backoff_seconds', 120),
        )

        fetch_timeout = timeout if timeout is not None else gdelt_config.get('fetch_timeout_seconds', 20)
        self.fetch_timeout = fetch_timeout
        self.session = requests.Session()
        self.session.headers['User-Agent'] = USER_AGENT

        self.last_queries_executed = 0

    def _queries(self) -> List[Dict]:
        queries = build_gdelt_queries(self.config)
        if self.shard_count <= 1:
            return queries
        return [q for i, q in enumerate(queries) if i % self.shard_count == self.shard_index]

    def collect(self) -> List[Dict]:
        articles: List[Dict] = []
        self.last_queries_executed = 0

        queries = self._queries()
        for i, query in enumerate(queries, 1):
            logger.info("GDELT query %d/%d: %s", i, len(queries), query['description'])
            try:
                result = self.api.search_articles(query['params'])
                self.last_queries_executed += 1
                for raw in result.get('articles', []):
                    article = self._to_article(raw)
                    if article:
                        articles.append(article)
            except Exception as e:
                logger.error("GDELT query failed (%s): %s", query['description'], e)
            time.sleep(self.rate_limit_seconds)

        logger.info("Collected %d articles from %d GDELT queries", len(articles), self.last_queries_executed)
        return articles

    def _to_article(self, raw: Dict) -> Optional[Dict]:
        url = raw.get('url', '')
        title = raw.get('title', '')
        if not url or not title:
            return None

        text = self._fetch_full_text(url)
        if not text:
            # GDELT's DOC API returns metadata only -- no body text, no
            # snippet field -- so the only fallback available is the title
            # itself. See module docstring for why this repo fetches the
            # full page rather than validating GDELT's response as-is.
            text = title

        return {
            'url': url,
            'title': title,
            'description': text,
            'domain': raw.get('domain', ''),
            'country': raw.get('sourcecountry', ''),
            'language': detect_language(text),
            'published_date': raw.get('seendate', ''),
            'source': 'gdelt',
        }

    def _fetch_full_text(self, url: str) -> Optional[str]:
        try:
            resp = self.session.get(url, timeout=self.fetch_timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning("Could not fetch article page %s: %s", url, e)
            return None

        extracted = trafilatura.extract(resp.text, url=url)
        return extracted or None

    def close(self) -> None:
        self.api.close()
        self.session.close()
