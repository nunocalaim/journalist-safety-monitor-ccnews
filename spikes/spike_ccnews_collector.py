#!/usr/bin/env python3
"""
Phase 1 spike (see PLAN.md): stream one real CC-NEWS WARC file, filter to a
handful of test domains, and extract article text -- to validate the
end-to-end approach before building the real collector.

Not part of the production pipeline. Deliberately throwaway/inline.
"""

from __future__ import annotations

from urllib.parse import urlparse

import requests
import trafilatura
from warcio.archiveiterator import ArchiveIterator

WARC_URL = "https://data.commoncrawl.org/crawl-data/CC-NEWS/2026/08/CC-NEWS-20260824090656-00330.warc.gz"

# Deliberately broad set of test domains, picked from the earlier manual
# sample of this same file, to prove filtering + extraction both work.
TEST_DOMAINS = {
    "www.finanznachrichten.de",
    "www.kommersant.ru",
    "economictimes.indiatimes.com",
    "www.haberler.com",
    "www.goal.com",
}

MAX_MATCHES = 5


def main() -> None:
    print(f"Streaming {WARC_URL}")
    resp = requests.get(WARC_URL, stream=True, timeout=60)
    resp.raise_for_status()
    resp.raw.decode_content = True

    seen = 0
    matched = 0

    for record in ArchiveIterator(resp.raw):
        if record.rec_type != "response":
            continue
        seen += 1

        url = record.rec_headers.get_header("WARC-Target-URI")
        if not url:
            continue
        host = urlparse(url).netloc

        if host not in TEST_DOMAINS:
            continue

        content_type = record.http_headers.get_header("Content-Type", "") if record.http_headers else ""
        if content_type and "html" not in content_type:
            continue

        html_bytes = record.content_stream().read()
        try:
            html = html_bytes.decode("utf-8", errors="replace")
        except Exception as exc:
            print(f"  [decode error] {url}: {exc}")
            continue

        extracted = trafilatura.extract(
            html,
            output_format="json",
            with_metadata=True,
            url=url,
        )

        matched += 1
        print(f"\n=== match {matched}: {url} ===")
        if extracted:
            import json

            data = json.loads(extracted)
            print("title:", data.get("title"))
            print("description:", data.get("description"))
            text = (data.get("text") or "")
            print("text (first 300 chars):", text[:300].replace("\n", " "))
            print("text length:", len(text))
        else:
            print("  trafilatura returned no extraction")

        if matched >= MAX_MATCHES:
            break

    print(f"\nScanned {seen} response records, matched {matched} from test domains.")


if __name__ == "__main__":
    main()
