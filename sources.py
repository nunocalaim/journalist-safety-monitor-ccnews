#!/usr/bin/env python3
"""
Parses the ccnews_domains section of config.yaml into flat lists of
CC-NEWS-source and RSS-source domains, each tagged with its priority
country. Shared by ccnews_collector.py, rss_collector.py, and
journalist_safety_monitor.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class DomainSource:
    domain: str
    country: str
    source: str  # "ccnews" or "rss"
    feed_url: Optional[str] = None
    fetch_full_text: bool = False


def load_domain_sources(config: Dict) -> List[DomainSource]:
    sources = []
    for country, entries in config.get('ccnews_domains', {}).items():
        for entry in entries:
            sources.append(DomainSource(
                domain=entry['domain'],
                country=country,
                source=entry['source'],
                feed_url=entry.get('feed_url'),
                fetch_full_text=entry.get('fetch_full_text', False),
            ))
    return sources


def ccnews_domains(config: Dict) -> List[DomainSource]:
    return [s for s in load_domain_sources(config) if s.source == 'ccnews']


def rss_domains(config: Dict) -> List[DomainSource]:
    return [s for s in load_domain_sources(config) if s.source == 'rss']
