import os
import sys
import logging
from urllib.parse import urljoin, urldefrag

from neo4j import GraphDatabase
from scrapling.fetchers import Fetcher, StealthyFetcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("job")

NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USER = os.environ["NEO4J_USER"]
NEO4J_PASS = os.environ["NEO4J_PASS"]
NEO4J_DB = os.getenv("NEO4J_DB", "neo4j")
TARGET_URLS = [u.strip() for u in os.environ["TARGET_URLS"].split(",") if u.strip()]
FETCH_MODE = os.getenv("FETCH_MODE", "http")  # http | stealth
MAX_LINKS = int(os.getenv("MAX_LINKS", "500"))

Q_CONSTRAINT = "CREATE CONSTRAINT page_url IF NOT EXISTS FOR (p:Page) REQUIRE p.url IS UNIQUE"

Q_PAGE = """
MERGE (p:Page {url: $url})
SET p.title = $title, p.status = $status, p.fetched_at = datetime()
WITH p
UNWIND $links AS l
MERGE (q:Page {url: l})
MERGE (p)-[:LINKS_TO]->(q)
"""

Q_PAGE_NO_LINKS = """
MERGE (p:Page {url: $url})
SET p.title = $title, p.status = $status, p.fetched_at = datetime()
"""


def fetch(url):
    if FETCH_MODE == "stealth":
        return StealthyFetcher.fetch(url, headless=True)
    return Fetcher.get(url)


def parse(url, page):
    title = page.css("title::text").get()
    hrefs = page.css("a::attr(href)").getall()
    links = set()
    for h in hrefs:
        h = (h or "").strip()
        if not h or h.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        abs_url, _ = urldefrag(urljoin(url, h))
        if abs_url.startswith(("http://", "https://")) and abs_url != url:
            links.add(abs_url)
    return (title or "").strip(), sorted(links)[:MAX_LINKS]


def main():
    drv = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    drv.verify_connectivity()
    drv.execute_query(Q_CONSTRAINT, database_=NEO4J_DB)

    failed = 0
    for url in TARGET_URLS:
        try:
            page = fetch(url)
            status = getattr(page, "status", None)
            title, links = parse(url, page)
            if links:
                drv.execute_query(Q_PAGE, url=url, title=title, status=status,
                                  links=links, database_=NEO4J_DB)
            else:
                drv.execute_query(Q_PAGE_NO_LINKS, url=url, title=title,
                                  status=status, database_=NEO4J_DB)
            log.info("ok url=%s status=%s links=%d", url, status, len(links))
        except Exception:
            failed += 1
            log.exception("fail url=%s", url)

    drv.close()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
