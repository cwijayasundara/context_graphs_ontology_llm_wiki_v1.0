"""Web pull connector with depth-limited link following.

Given a seed URL, fetches the page and recursively follows links from the
extracted main content (not nav/footer/ads) up to `--depth` levels deep,
saving each fetched page under `raw/web/<host>/<slug>.html` with a
companion `<slug>.meta.json` carrying URL/fetched_at/parent_url/depth/hash
provenance. The companion file is what the WebParser reads at parse time.

Polite-by-default:
  - same-domain restriction (use --allow-external to widen)
  - request delay between fetches (default 1s)
  - per-host max-pages budget
  - timeout per request
  - configurable User-Agent
  - skips already-fetched URLs by content hash (idempotent re-runs)

After pulling, the existing document path picks up the .html files
automatically — extension routing in document_parser.py:get_parser sends
`.html` to WebParser, and the LLM ingestor (or query_agent) handles the
rest. Each crawled page becomes one parsed document; downstream the LLM
ingestor decides what wiki entities/concepts the page describes.

CLI:
    python agents/source_pull/web.py crawl https://example.com/blog/X \
        --depth 2 --max-pages 30 --delay 1.0
    python agents/source_pull/web.py crawl https://example.com/about --depth 0
    python agents/source_pull/web.py crawl https://example.com/X --allow-external
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import time
from collections import deque
from pathlib import Path
from typing import Iterable
from urllib.parse import urldefrag, urljoin, urlparse

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agents"))

from logging_config import configure_logging, get_logger  # noqa: E402

log = get_logger("source_pull.web")

DEFAULT_USER_AGENT = "context-graphs-crawler/0.1 (+https://example.invalid/bot)"
RAW_WEB = ROOT / "raw" / "web"
HTML_CONTENT_TYPES = {"text/html", "application/xhtml+xml"}


class CrawlBudgetError(Exception):
    pass


def _slug_url(url: str) -> str:
    parsed = urlparse(url)
    path = (parsed.path or "/").rstrip("/")
    if not path:
        path = "/index"
    if parsed.query:
        path = f"{path}_{hashlib.sha1(parsed.query.encode()).hexdigest()[:8]}"
    slug = re.sub(r"[^a-z0-9]+", "_", path.lower()).strip("_") or "index"
    return slug[:120]


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


# HTML elements/classes that wrap chrome (nav, ads, related-posts) — links
# inside these are excluded from crawl follow-on. Stripping by tag is more
# robust than relying on trafilatura's main-content extraction, which drops
# <a href> entirely (it inlines link text only).
_CHROME_TAGS = {"nav", "footer", "header", "aside", "form", "noscript", "script", "style"}
_CHROME_CLASS_HINTS = ("nav", "menu", "footer", "header", "sidebar", "aside",
                       "related", "share", "social", "promo", "advert", "subscribe",
                       "comment", "pagination", "breadcrumb", "cookie")


def _extracted_links(html: str, base_url: str) -> list[str]:
    """Return absolute URLs from the page's main editorial content.

    Strategy: parse the raw HTML with BeautifulSoup, drop <nav>/<footer>/<aside>
    and chrome-classed elements, then collect <a href> from what remains.
    Filters out fragments, mailto/tel/javascript, and non-http(s) schemes.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise RuntimeError(
            "Install beautifulsoup4 for crawl link extraction: pip install beautifulsoup4"
        ) from exc

    soup = BeautifulSoup(html, "html.parser")
    for tag_name in _CHROME_TAGS:
        for tag in list(soup.find_all(tag_name)):
            tag.decompose()
    # Snapshot the list before mutating; decompose invalidates iterators.
    for el in list(soup.find_all(class_=True)):
        attrs = getattr(el, "attrs", None) or {}
        classes_attr = attrs.get("class") or []
        if isinstance(classes_attr, str):
            classes_attr = [classes_attr]
        classes = " ".join(classes_attr).lower()
        if any(hint in classes for hint in _CHROME_CLASS_HINTS):
            el.decompose()

    out: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("mailto:", "javascript:", "tel:", "#")):
            continue
        absolute, _ = urldefrag(urljoin(base_url, href))
        if absolute.startswith(("http://", "https://")):
            out.append(absolute)
    seen: set[str] = set()
    deduped = []
    for u in out:
        if u not in seen:
            seen.add(u)
            deduped.append(u)
    return deduped


def _is_html(content_type: str | None) -> bool:
    if not content_type:
        return False
    return any(ct in content_type.lower() for ct in HTML_CONTENT_TYPES)


def _save_page(
    *,
    url: str,
    html: str,
    parent_url: str | None,
    depth: int,
    out_dir: Path,
) -> tuple[Path, dict, bool]:
    """Write the HTML + meta sidecar. Returns (html_path, meta, changed)."""
    host = urlparse(url).hostname or "unknown"
    host_dir = out_dir / re.sub(r"[^a-z0-9.\-]+", "_", host.lower())
    host_dir.mkdir(parents=True, exist_ok=True)
    slug = _slug_url(url)
    html_path = host_dir / f"{slug}.html"
    meta_path = html_path.with_suffix(".meta.json")
    new_hash = _content_hash(html)

    if meta_path.exists():
        try:
            old_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            old_meta = {}
        if old_meta.get("content_hash") == new_hash:
            return html_path, old_meta, False

    meta = {
        "url": url,
        "host": host,
        "depth": depth,
        "parent_url": parent_url,
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "content_hash": new_hash,
    }
    html_path.write_text(html, encoding="utf-8")
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    return html_path, meta, True


def crawl(
    seed_url: str,
    *,
    depth: int = 2,
    max_pages: int = 30,
    delay_sec: float = 1.0,
    same_domain: bool = True,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout_sec: int = 20,
    out_dir: Path = RAW_WEB,
) -> dict:
    """BFS from seed up to `depth` hops; honors `same_domain` and `max_pages`."""
    configure_logging()
    log.info("crawl.start seed=%s depth=%s max_pages=%s same_domain=%s",
             seed_url, depth, max_pages, same_domain)

    seed_host = (urlparse(seed_url).hostname or "").lower()
    visited: set[str] = set()
    queue: deque[tuple[str, int, str | None]] = deque([(seed_url, 0, None)])
    fetched: list[dict] = []
    skipped_unchanged: list[str] = []
    failed: list[dict] = []
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"})

    while queue:
        if len(fetched) + len(skipped_unchanged) >= max_pages:
            log.info("crawl.budget_reached fetched=%s skipped=%s", len(fetched), len(skipped_unchanged))
            break
        url, current_depth, parent = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        if same_domain and (urlparse(url).hostname or "").lower() != seed_host:
            continue

        try:
            time.sleep(delay_sec if fetched or skipped_unchanged else 0)  # no delay on first hit
            r = session.get(url, timeout=timeout_sec, allow_redirects=True)
        except requests.RequestException as exc:
            log.warning("crawl.fetch_error url=%s err=%s", url, exc)
            failed.append({"url": url, "error": str(exc)})
            continue

        if r.status_code != 200:
            log.warning("crawl.bad_status url=%s status=%s", url, r.status_code)
            failed.append({"url": url, "status": r.status_code})
            continue

        if not _is_html(r.headers.get("Content-Type")):
            log.info("crawl.skip_non_html url=%s content_type=%s",
                     url, r.headers.get("Content-Type"))
            continue

        html = r.text
        html_path, meta, changed = _save_page(
            url=url, html=html, parent_url=parent, depth=current_depth, out_dir=out_dir
        )
        try:
            rel = str(html_path.resolve().relative_to(ROOT))
        except ValueError:
            rel = str(html_path)
        if changed:
            fetched.append({"url": url, "depth": current_depth, "raw_path": rel,
                            "content_hash": meta["content_hash"]})
            log.info("crawl.fetched url=%s depth=%s raw_path=%s", url, current_depth, rel)
        else:
            skipped_unchanged.append(url)
            log.info("crawl.skipped_unchanged url=%s raw_path=%s", url, rel)

        if current_depth < depth:
            for link in _extracted_links(html, base_url=url):
                if link in visited:
                    continue
                queue.append((link, current_depth + 1, url))

    return {
        "seed": seed_url,
        "depth": depth,
        "max_pages": max_pages,
        "same_domain": same_domain,
        "fetched": fetched,
        "skipped_unchanged": skipped_unchanged,
        "failed": failed,
        "total_visited": len(visited),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("crawl", help="Pull a URL and follow links up to --depth.")
    p.add_argument("url")
    p.add_argument("--depth", type=int, default=2,
                   help="Link-following depth (0 = seed only, 1 = seed + direct links, 2 = +grandchildren).")
    p.add_argument("--max-pages", type=int, default=30,
                   help="Hard budget across the entire crawl.")
    p.add_argument("--delay", type=float, default=1.0,
                   help="Seconds to wait between requests (politeness).")
    p.add_argument("--allow-external", action="store_true",
                   help="Allow following links outside the seed's hostname.")
    p.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    p.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    result = crawl(
        args.url,
        depth=args.depth,
        max_pages=args.max_pages,
        delay_sec=args.delay,
        same_domain=not args.allow_external,
        user_agent=args.user_agent,
        timeout_sec=args.timeout,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
