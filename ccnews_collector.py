#!/usr/bin/env python3
"""
Streams CC-NEWS WARC files, filters to the configured domain allowlist, and
extracts article text. See PLAN.md: CC-NEWS has no keyword/domain search
API, so every WARC file has to be downloaded and scanned in full -- this
module shards that work across scheduled runs and tracks which files have
already been processed so repeated runs make forward progress instead of
reprocessing the same files.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests
import trafilatura
from warcio.archiveiterator import ArchiveIterator

from language_detect import detect_language
from sources import ccnews_domains

logger = logging.getLogger(__name__)

WARC_PATHS_INDEX_URL = "https://data.commoncrawl.org/crawl-data/CC-NEWS/{year}/{month:02d}/warc.paths.gz"
WARC_BASE_URL = "https://data.commoncrawl.org/"


class CCNewsCollector:
    def __init__(
        self,
        config: Dict,
        state_path: str = 'data/ccnews_state.json',
        shard_count: int = 1,
        shard_index: int = 0,
        timeout: int = 60,
    ):
        collection_config = config.get('ccnews_collection', {})
        self.shard_count = max(shard_count, 1)
        self.shard_index = shard_index % self.shard_count
        self.max_files_per_run = collection_config.get('max_warc_files_per_run', 1)
        self.timeout = timeout

        self.state_path = Path(state_path)
        self.domains_by_host = {d.domain: d for d in ccnews_domains(config)}
        self.last_files_processed: List[str] = []

    def _load_state(self) -> Dict:
        if not self.state_path.exists():
            return {'processed_files': []}
        try:
            return json.loads(self.state_path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read %s, starting fresh", self.state_path)
            return {'processed_files': []}

    def _save_state(self, state: Dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2))

    def _fetch_warc_paths(self, year: int, month: int) -> List[str]:
        url = WARC_PATHS_INDEX_URL.format(year=year, month=month)
        logger.info("Fetching WARC file index: %s", url)
        resp = requests.get(url, timeout=self.timeout)
        resp.raise_for_status()

        import gzip
        import io
        raw = gzip.GzipFile(fileobj=io.BytesIO(resp.content)).read()
        return [line for line in raw.decode('utf-8').splitlines() if line.strip()]

    def _next_files_to_process(self) -> List[str]:
        now = datetime.now(timezone.utc)
        all_paths = self._fetch_warc_paths(now.year, now.month)
        if now.day <= 2:
            # Cover the tail of the previous month near a month boundary.
            prev_year, prev_month = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
            try:
                all_paths = self._fetch_warc_paths(prev_year, prev_month) + all_paths
            except requests.RequestException:
                pass

        # Shard the whole path list by index so each shard has a stable,
        # disjoint slice of files to work through over time.
        shard_paths = [p for i, p in enumerate(all_paths) if i % self.shard_count == self.shard_index]

        state = self._load_state()
        processed = set(state.get('processed_files', []))
        unprocessed = [p for p in shard_paths if p not in processed]

        return unprocessed[:self.max_files_per_run]

    def _mark_processed(self, paths: List[str]) -> None:
        state = self._load_state()
        processed = state.get('processed_files', [])
        processed.extend(paths)
        # Keep the state file bounded -- we only need enough history to
        # avoid immediate reprocessing, not the full multi-year archive.
        state['processed_files'] = processed[-5000:]
        self._save_state(state)

    def collect(self) -> List[Dict]:
        files = self._next_files_to_process()
        self.last_files_processed = files
        if not files:
            logger.info("No new CC-NEWS WARC files to process for this shard")
            return []

        articles: List[Dict] = []
        for path in files:
            url = WARC_BASE_URL + path
            try:
                articles.extend(self._scan_file(url))
            except requests.RequestException as e:
                logger.error("Failed to stream %s: %s", url, e)
                continue

        self._mark_processed(files)
        return articles

    def _scan_file(self, warc_url: str) -> List[Dict]:
        logger.info("Streaming %s", warc_url)
        resp = requests.get(warc_url, stream=True, timeout=self.timeout)
        resp.raise_for_status()

        articles = []
        records_seen = 0
        for record in ArchiveIterator(resp.raw):
            if record.rec_type != 'response':
                continue
            records_seen += 1

            target = record.rec_headers.get_header('WARC-Target-URI')
            if not target:
                continue
            host = urlparse(target).netloc
            domain_source = self.domains_by_host.get(host)
            if not domain_source:
                continue

            content_type = record.http_headers.get_header('Content-Type', '') if record.http_headers else ''
            if content_type and 'html' not in content_type:
                continue

            html_bytes = record.content_stream().read()
            try:
                html = html_bytes.decode('utf-8', errors='replace')
            except Exception:
                continue

            article = self._extract_article(html, target, domain_source.country)
            if article:
                articles.append(article)

        logger.info("Scanned %d response records, matched %d from allowlisted domains", records_seen, len(articles))
        return articles

    def _extract_article(self, html: str, url: str, country: str) -> Optional[Dict]:
        extracted = trafilatura.extract(
            html, output_format='json', with_metadata=True, url=url,
        )
        if not extracted:
            return None

        data = json.loads(extracted)
        text = data.get('text') or ''
        if not text:
            return None

        return {
            'url': url,
            'title': data.get('title') or '',
            'description': text,
            'domain': urlparse(url).netloc,
            'country': country,
            'language': detect_language(text),
            'published_date': data.get('date') or '',
            'source': 'ccnews',
        }
