#!/usr/bin/env python3
"""
Coverage verification (see PLAN.md / config.yaml TODO): scan real CC-NEWS
WARC files and count which domains actually appear, so the ccnews_domains
allowlist in config.yaml can be based on evidence instead of guesses.

Usage: python3 scan_domain_coverage.py <warc_url> [<warc_url> ...]

Not part of the production pipeline. Deliberately throwaway/inline.
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from urllib.parse import urlparse

import requests
from warcio.archiveiterator import ArchiveIterator


def scan_file(url: str, domain_counts: Counter) -> int:
    start = time.time()
    resp = requests.get(url, stream=True, timeout=120)
    resp.raise_for_status()

    records = 0
    for record in ArchiveIterator(resp.raw):
        if record.rec_type != "response":
            continue
        records += 1
        target = record.rec_headers.get_header("WARC-Target-URI")
        if not target:
            continue
        host = urlparse(target).netloc
        if host:
            domain_counts[host] += 1

    elapsed = time.time() - start
    print(f"  {url.rsplit('/', 1)[-1]}: {records} response records in {elapsed:.1f}s", file=sys.stderr)
    return records


def main() -> None:
    urls = sys.argv[1:]
    if not urls:
        print("usage: scan_domain_coverage.py <warc_url> [...]", file=sys.stderr)
        sys.exit(1)

    domain_counts: Counter = Counter()
    total_records = 0
    for url in urls:
        total_records += scan_file(url, domain_counts)

    print(f"\nTotal response records scanned: {total_records}")
    print(f"Unique domains seen: {len(domain_counts)}")
    print(f"\nTop 40 domains by article count:")
    for domain, count in domain_counts.most_common(40):
        print(f"  {count:5d}  {domain}")


if __name__ == "__main__":
    main()
