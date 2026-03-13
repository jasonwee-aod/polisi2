"""
Quick live test — fetch and parse the kenyataan-media RSS feed.
Usage: python3 scripts/test_live_feed.py
"""

import sys
import json
from pathlib import Path

# Add project src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import requests
from mohe_scraper.parsers import RSSParser, DateParser

FEEDS = [
    {
        "name": "kenyataan_media_ms",
        "url": "https://www.mohe.gov.my/hebahan/kenyataan-media?format=feed&type=rss",
        "language": "ms",
    },
    {
        "name": "media_statements_en",
        "url": "https://www.mohe.gov.my/en/broadcast/media-statements?format=feed&type=rss",
        "language": "en",
    },
]

HEADERS = {"User-Agent": "MOHEScraper/1.0 (live-test)"}


def test_feed(feed: dict):
    print(f"\n{'='*60}")
    print(f"Feed : {feed['name']}")
    print(f"URL  : {feed['url']}")
    print(f"Lang : {feed['language']}")
    print("-" * 60)

    try:
        resp = requests.get(feed["url"], headers=HEADERS, timeout=15)
        resp.raise_for_status()
        print(f"HTTP : {resp.status_code}  Content-Type: {resp.headers.get('Content-Type','?')}")
    except requests.RequestException as e:
        print(f"FAIL : {e}")
        return

    items = RSSParser.parse_feed(resp.text)
    print(f"Items: {len(items)} parsed from feed")

    for i, item in enumerate(items[:5], 1):
        pub = RSSParser.parse_date(item.get("pubDate"))
        print(f"\n  [{i}] {item['title'][:80]}")
        print(f"       link : {item['link'][:80]}")
        print(f"       date : {pub or item.get('pubDate', 'n/a')}")
        print(f"       enc  : {len(item.get('enclosures', []))} enclosure(s)")

    if len(items) > 5:
        print(f"\n  ... and {len(items) - 5} more items")


if __name__ == "__main__":
    for feed in FEEDS:
        test_feed(feed)
    print(f"\n{'='*60}")
    print("Done.")
