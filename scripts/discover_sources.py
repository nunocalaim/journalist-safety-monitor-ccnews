#!/usr/bin/env python3
"""
Domain classification tool for building/maintaining the ccnews_domains
allowlist in config.yaml. For each candidate domain:

1. Checks robots.txt for a CCBot disallow rule (-> source: ccnews if
   allowed, otherwise it structurally can never appear in CC-NEWS).
2. Auto-discovers an RSS/Atom feed the standard way -- a
   <link rel="alternate" type="application/rss+xml"|"application/atom+xml">
   tag on the homepage, same mechanism browsers/feed readers use -- rather
   than guessing common feed URL paths.
3. Validates the discovered feed actually parses with feedparser and has
   entries.
4. Checks whether a generic (non-CCBot) user agent is allowed to fetch full
   article pages (-> fetch_full_text).

Only classifies candidates; does not touch config.yaml itself. Input is a
CSV/text list of "domain,country" (one per line, '#' comments allowed) via
--input, or positional domains on the command line. Output is printed as
YAML-ready ccnews_domains entries plus a plain-text summary.

Usage:
    python3 scripts/discover_sources.py --input candidate_domains.txt
    python3 scripts/discover_sources.py www.example.com:MX
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.robotparser
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import feedparser
import requests

USER_AGENT = "JournalistSafetyMonitor-CCNews/1.0 (+https://github.com/nunocalaim/journalist-safety-monitor-ccnews)"
TIMEOUT = 15

_FEED_LINK_RE = re.compile(
    r'<link[^>]+type=["\'](?:application/rss\+xml|application/atom\+xml)["\'][^>]*>',
    re.IGNORECASE,
)
_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)


@dataclass
class DomainReport:
    domain: str
    country: str
    ccbot_blocked: Optional[bool] = None
    generic_agent_blocked: Optional[bool] = None
    feed_url: Optional[str] = None
    feed_entry_count: int = 0
    notes: List[str] = field(default_factory=list)

    @property
    def recommended_source(self) -> Optional[str]:
        if self.ccbot_blocked is False:
            return "ccnews"
        if self.feed_url and self.feed_entry_count > 0:
            return "rss"
        return None


def check_robots(domain: str) -> tuple[Optional[bool], Optional[bool]]:
    """Returns (ccbot_blocked, generic_agent_blocked)."""
    for scheme in ("https", "http"):
        url = f"{scheme}://{domain}/robots.txt"
        try:
            resp = requests.get(url, timeout=TIMEOUT)
        except requests.RequestException:
            continue
        if resp.status_code >= 400:
            continue

        rp = urllib.robotparser.RobotFileParser()
        rp.parse(resp.text.splitlines())
        # Check a representative path, not just "/", since some sites
        # allow "/" broadly but disallow via a wildcard pattern instead.
        sample_url = f"{scheme}://{domain}/"
        ccbot_blocked = not rp.can_fetch("CCBot", sample_url)
        generic_blocked = not rp.can_fetch(USER_AGENT, sample_url)
        return ccbot_blocked, generic_blocked
    return None, None


COMMON_FEED_PATHS = [
    "feed/", "feed", "rss.xml", "rss/", "rss", "arc/outboundfeeds/rss/",
    "rss/index.xml", "index.rss",
]


def discover_feed(domain: str) -> Optional[str]:
    for scheme in ("https", "http"):
        url = f"{scheme}://{domain}/"
        try:
            resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
        except requests.RequestException:
            continue
        if resp.status_code >= 400:
            continue

        for tag in _FEED_LINK_RE.findall(resp.text):
            href_match = _HREF_RE.search(tag)
            if href_match:
                return urljoin(url, href_match.group(1))
        break

    # Fallback: the <link rel=alternate> tag is often missing even when a
    # feed still exists at a conventional path (many sites dropped feed
    # auto-discovery markup from their HTML head years ago).
    for scheme in ("https",):
        for path in COMMON_FEED_PATHS:
            url = f"{scheme}://{domain}/{path}"
            try:
                resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
            except requests.RequestException:
                continue
            if resp.status_code == 200:
                return url
    return None


def validate_feed(feed_url: str) -> int:
    try:
        parsed = feedparser.parse(feed_url, agent=USER_AGENT)
    except Exception:
        return 0
    return len(parsed.entries)


def classify(domain: str, country: str) -> DomainReport:
    report = DomainReport(domain=domain, country=country)

    ccbot_blocked, generic_blocked = check_robots(domain)
    report.ccbot_blocked = ccbot_blocked
    report.generic_agent_blocked = generic_blocked
    if ccbot_blocked is None:
        report.notes.append("robots.txt unreachable")

    if ccbot_blocked is False:
        report.notes.append("allowed in CC-NEWS (not CCBot-blocked)")
        return report

    feed_url = discover_feed(domain)
    if not feed_url:
        report.notes.append("CCBot-blocked, no <link rel=alternate> feed found")
        return report

    entry_count = validate_feed(feed_url)
    report.feed_url = feed_url
    report.feed_entry_count = entry_count
    if entry_count == 0:
        report.notes.append("feed discovered but did not parse / no entries")

    return report


def parse_input_line(line: str) -> Optional[tuple[str, str]]:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if ":" in line:
        domain, country = line.split(":", 1)
    elif "," in line:
        domain, country = line.split(",", 1)
    else:
        domain, country = line, ""
    return domain.strip(), country.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("domains", nargs="*", help="domain:country pairs, e.g. www.example.com:MX")
    parser.add_argument("--input", help="file with one domain:country per line")
    args = parser.parse_args()

    candidates: List[tuple[str, str]] = []
    if args.input:
        with open(args.input) as f:
            for line in f:
                parsed = parse_input_line(line)
                if parsed:
                    candidates.append(parsed)
    for d in args.domains:
        parsed = parse_input_line(d)
        if parsed:
            candidates.append(parsed)

    if not candidates:
        print("No candidates given.", file=sys.stderr)
        sys.exit(1)

    reports = []
    for domain, country in candidates:
        print(f"Checking {domain} ({country})...", file=sys.stderr)
        reports.append(classify(domain, country))

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    for r in reports:
        status = r.recommended_source or "UNCOVERED"
        print(f"{status:10s} {r.domain:35s} {r.country:4s} "
              f"ccbot_blocked={r.ccbot_blocked} feed={r.feed_url or '-'} "
              f"entries={r.feed_entry_count} full_text_ok={r.generic_agent_blocked is False} "
              f"{'; '.join(r.notes)}")

    print("\n" + "=" * 80)
    print("config.yaml-ready entries (ccnews source)")
    print("=" * 80)
    for r in reports:
        if r.recommended_source == "ccnews":
            print(f"  - domain: \"{r.domain}\"  # {r.country}\n    source: \"ccnews\"")

    print("\n" + "=" * 80)
    print("config.yaml-ready entries (rss source)")
    print("=" * 80)
    for r in reports:
        if r.recommended_source == "rss":
            fetch_full_text = "true" if r.generic_agent_blocked is False else "false"
            print(
                f"  - domain: \"{r.domain}\"  # {r.country}\n"
                f"    source: \"rss\"\n"
                f"    feed_url: \"{r.feed_url}\"\n"
                f"    fetch_full_text: {fetch_full_text}"
            )


if __name__ == "__main__":
    main()
