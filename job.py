import os
import sys
import hashlib
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
MAX_TEXT = int(os.getenv("MAX_TEXT", "100000"))

Q_CONSTRAINT = "CREATE CONSTRAINT page_url IF NOT EXISTS FOR (p:Page) REQUIRE p.url IS UNIQUE"

Q_PAGE = """
MERGE (p:Page {url: $url})
SET p.title = $title,
    p.description = $description,
    p.headings = $headings,
    p.text = $text,
    p.text_hash = $text_hash,
    p.status = $status,
    p.fetched_at = datetime()
WITH p
UNWIND $links AS l
MERGE (q:Page {url: l})
MERGE (p)-[:LINKS_TO]->(q)
"""

Q_PAGE_NO_LINKS = """
MERGE (p:Page {url: $url})
SET p.title = $title,
    p.description = $description,
    p.headings = $headings,
    p.text = $text,
    p.text_hash = $text_hash,
    p.status = $status,
    p.fetched_at = datetime()
"""


def fetch(url):
    if FETCH_MODE == "stealth":
        return StealthyFetcher.fetch(url, headless=True)
    return Fetcher.get(url)


def node_text(el):
    try:
        return el.get_all_text(separator=" ", strip=True)
    except Exception:
        return " ".join(t.strip() for t in el.css("::text").getall() if t.strip())


def parse(url, page):
    title = (page.css("title::text").get() or "").strip()
    description = (page.css('meta[name="description"]::attr(content)').get() or "").strip()

    headings = [node_text(h) for h in page.css("h1, h2, h3")]
    headings = [h for h in headings if h][:50]

    body = page.css("body")
    text = node_text(body[0]) if body else node_text(page)
    text = text[:MAX_TEXT]

    links = set()
    for h in page.css("a::attr(href)").getall():
        h = (h or "").strip()
        if not h or h.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        abs_url, _ = urldefrag(urljoin(url, h))
        if abs_url.startswith(("http://", "https://")) and abs_url != url:
            links.add(abs_url)

    return title, description, headings, text, sorted(links)[:MAX_LINKS]


def main():
    drv = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    drv.verify_connectivity()
    drv.execute_query(Q_CONSTRAINT, database_=NEO4J_DB)

    failed = 0
    for url in TARGET_URLS:
        try:
            page = fetch(url)
            status = getattr(page, "status", None)
            title, description, headings, text, links = parse(url, page)
            params = dict(
                url=url, title=title, description=description, headings=headings,
                text=text, text_hash=hashlib.sha256(text.encode()).hexdigest(),
                status=status, database_=NEO4J_DB,
            )
            if links:
                drv.execute_query(Q_PAGE, links=links, **params)
            else:
                drv.execute_query(Q_PAGE_NO_LINKS, **params)
            log.info("ok url=%s status=%s text=%d links=%d", url, status, len(text), len(links))
        except Exception:
            failed += 1
            log.exception("fail url=%s", url)

    drv.close()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
