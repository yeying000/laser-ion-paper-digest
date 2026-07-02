from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from socket import timeout as SocketTimeout

from .models import Paper


ARXIV_API_URL = "https://export.arxiv.org/api/query"
MAX_ARXIV_QUERY_URL_LENGTH = 1800
ATOM_NS = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"


def build_search_query(query: str, categories: list[str], start: datetime, end: datetime) -> str:
    category_query = " OR ".join(f"cat:{category}" for category in categories)
    submitted = _format_date_filter(start, end)
    return f"({query}) AND ({category_query}) AND submittedDate:{submitted}"


def build_combined_search_query(queries: list[str], categories: list[str], start: datetime, end: datetime) -> str:
    query_part = " OR ".join(f"({query})" for query in queries)
    category_query = " OR ".join(f"cat:{category}" for category in categories)
    submitted = _format_date_filter(start, end)
    return f"({query_part}) AND ({category_query}) AND submittedDate:{submitted}"


def fetch_recent_papers(
    queries: list[str],
    categories: list[str],
    lookback_days: int,
    max_results: int,
    pause_seconds: float = 3.0,
) -> list[Paper]:
    end = datetime.now(UTC)
    start = end - timedelta(days=lookback_days)
    papers_by_id: dict[str, Paper] = {}
    for query_group in _chunk_queries_for_url(queries, categories, start, end):
        search_query = build_combined_search_query(query_group, categories, start, end)
        for paper in fetch_query(search_query, max_results=max_results):
            papers_by_id[paper.paper_id] = paper
        if pause_seconds > 0:
            time.sleep(pause_seconds)

    return sorted(papers_by_id.values(), key=lambda paper: paper.updated, reverse=True)


def fetch_query(
    search_query: str,
    max_results: int = 50,
    retries: int = 2,
    timeout_seconds: int = 60,
) -> list[Paper]:
    params = {
        "search_query": search_query,
        "start": "0",
        "max_results": str(max_results),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = f"{ARXIV_API_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "laser-ion-paper-digest/0.1 (mailto:example@example.com)"},
    )
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = response.read()
            return parse_arxiv_feed(body)
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 503} or attempt >= retries:
                raise
            retry_after = exc.headers.get("Retry-After")
            _sleep_before_retry(attempt, retry_after)
        except (TimeoutError, SocketTimeout, urllib.error.URLError):
            if attempt >= retries:
                raise
            _sleep_before_retry(attempt)
    return []


def parse_arxiv_feed(feed_bytes: bytes) -> list[Paper]:
    root = ET.fromstring(feed_bytes)
    papers = []
    for entry in root.findall(f"{ATOM_NS}entry"):
        paper = _parse_entry(entry)
        if paper is not None:
            papers.append(paper)
    return papers


def _parse_entry(entry: ET.Element) -> Paper | None:
    paper_id_url = _text(entry, "id")
    if not paper_id_url or "/abs/" not in paper_id_url:
        return None

    paper_id = paper_id_url.rstrip("/").split("/abs/")[-1]
    title = _clean_text(_text(entry, "title") or "")
    abstract = _clean_text(_text(entry, "summary") or "")
    authors = [
        _clean_text(author.findtext(f"{ATOM_NS}name") or "")
        for author in entry.findall(f"{ATOM_NS}author")
    ]
    authors = [author for author in authors if author]

    links = entry.findall(f"{ATOM_NS}link")
    pdf_url = None
    for link in links:
        if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
            pdf_url = link.attrib.get("href")
            break

    categories = [category.attrib.get("term", "") for category in entry.findall(f"{ATOM_NS}category")]
    categories = [category for category in categories if category]
    primary_category_el = entry.find(f"{ARXIV_NS}primary_category")
    primary_category = primary_category_el.attrib.get("term") if primary_category_el is not None else None

    return Paper(
        paper_id=paper_id,
        title=title,
        authors=authors,
        abstract=abstract,
        published=_parse_datetime(_text(entry, "published")),
        updated=_parse_datetime(_text(entry, "updated")),
        url=paper_id_url,
        source="arXiv",
        pdf_url=pdf_url,
        doi=_clean_text(entry.findtext(f"{ARXIV_NS}doi") or "") or None,
        primary_category=primary_category,
        categories=categories,
        comment=_clean_text(entry.findtext(f"{ARXIV_NS}comment") or "") or None,
    )


def _text(entry: ET.Element, tag: str) -> str | None:
    return entry.findtext(f"{ATOM_NS}{tag}")


def _clean_text(value: str) -> str:
    return " ".join(value.replace("\n", " ").split())


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return parsedate_to_datetime(value).astimezone(UTC)


def _format_date_filter(start: datetime, end: datetime) -> str:
    return f"[{start:%Y%m%d%H%M} TO {end:%Y%m%d%H%M}]"


def _chunk_queries_for_url(
    queries: list[str],
    categories: list[str],
    start: datetime,
    end: datetime,
) -> list[list[str]]:
    chunks: list[list[str]] = []
    current: list[str] = []
    for query in queries:
        candidate = [*current, query]
        if current and _query_url_length(candidate, categories, start, end) > MAX_ARXIV_QUERY_URL_LENGTH:
            chunks.append(current)
            current = [query]
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _query_url_length(queries: list[str], categories: list[str], start: datetime, end: datetime) -> int:
    search_query = build_combined_search_query(queries, categories, start, end)
    params = {
        "search_query": search_query,
        "start": "0",
        "max_results": "1",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    return len(f"{ARXIV_API_URL}?{urllib.parse.urlencode(params)}")


def _sleep_before_retry(attempt: int, retry_after: str | None = None) -> None:
    delay = int(retry_after) if retry_after and retry_after.isdigit() else 15 * (attempt + 1)
    time.sleep(delay)
