from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from socket import timeout as SocketTimeout
from typing import Any, Callable

from .arxiv import fetch_recent_papers as fetch_arxiv_papers
from .models import Paper


OPENALEX_API_URL = "https://api.openalex.org/works"
CROSSREF_API_URL = "https://api.crossref.org/works"
SEMANTIC_SCHOLAR_API_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
EUROPE_PMC_API_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

DEFAULT_EXTERNAL_QUERIES = [
    '"laser ion acceleration"',
    '"laser-driven ion acceleration"',
    '"laser proton acceleration"',
    '"laser-driven proton"',
    '"laser-plasma ion acceleration"',
    '"target normal sheath acceleration"',
    '"radiation pressure acceleration" laser ion',
    '"near-critical density target" laser ion',
    '"collisionless shock acceleration" laser ion',
    '"magnetic vortex acceleration" laser ion',
    '"laser-driven proton beam"',
    '"laser-driven proton irradiation"',
]


@dataclass(slots=True)
class FetchResult:
    papers: list[Paper]
    warnings: list[str]


def fetch_recent_papers(
    queries: list[str],
    arxiv_config: dict[str, Any],
    source_config: dict[str, Any] | None,
    lookback_days: int,
    max_results: int,
    pause_seconds: float | None = None,
) -> FetchResult:
    source_config = source_config or {}
    enabled_sources = source_config.get("enabled") or [
        "arxiv",
        "openalex",
        "crossref",
        "semantic_scholar",
        "europe_pmc",
        "journal_watchlist",
    ]
    enabled_sources = [str(source) for source in enabled_sources]
    external_queries = source_config.get("external_queries") or DEFAULT_EXTERNAL_QUERIES
    external_queries = [str(query) for query in external_queries if str(query).strip()]
    request_pause = float(source_config.get("request_pause_seconds", 2.0))
    if pause_seconds is not None:
        request_pause = pause_seconds
    effective_source_config = {**source_config, "request_pause_seconds": request_pause}

    all_papers: list[Paper] = []
    warnings: list[str] = []
    end = datetime.now(UTC)
    start = end - timedelta(days=lookback_days)

    for source in enabled_sources:
        try:
            if source == "arxiv":
                arxiv_pause = (
                    pause_seconds
                    if pause_seconds is not None
                    else float(arxiv_config.get("pause_seconds", 3.0))
                )
                all_papers.extend(
                    fetch_arxiv_papers(
                        queries=queries,
                        categories=arxiv_config["categories"],
                        lookback_days=lookback_days,
                        max_results=int(arxiv_config.get("max_results", max_results)),
                        pause_seconds=arxiv_pause,
                    )
                )
            elif source == "openalex":
                all_papers.extend(_fetch_openalex(external_queries, start, end, max_results, effective_source_config))
            elif source == "crossref":
                all_papers.extend(_fetch_crossref(external_queries, start, end, max_results, effective_source_config))
            elif source == "semantic_scholar":
                all_papers.extend(
                    _fetch_semantic_scholar(external_queries, start, end, max_results, effective_source_config)
                )
            elif source == "europe_pmc":
                all_papers.extend(_fetch_europe_pmc(external_queries, start, end, max_results, effective_source_config))
            elif source == "journal_watchlist":
                all_papers.extend(_fetch_journal_watchlist(start, end, max_results, effective_source_config))
            else:
                warnings.append(f"未知数据源 {source}，已跳过。")
        except Exception as exc:
            warnings.append(f"{_source_label(source)} 暂时不可用，本次已跳过该数据源：{exc}")

    return FetchResult(papers=_deduplicate_papers(all_papers), warnings=warnings)


def _fetch_openalex(
    queries: list[str],
    start: datetime,
    end: datetime,
    max_results: int,
    source_config: dict[str, Any],
) -> list[Paper]:
    config = source_config.get("openalex", {})
    params_extra = {}
    api_key = os.getenv("OPENALEX_API_KEY") or config.get("api_key")
    if api_key:
        params_extra["api_key"] = api_key
    mailto = os.getenv("CONTACT_EMAIL") or config.get("mailto")
    if mailto:
        params_extra["mailto"] = mailto

    select = ",".join(
        [
            "id",
            "doi",
            "display_name",
            "authorships",
            "publication_date",
            "updated_date",
            "primary_location",
            "open_access",
            "abstract_inverted_index",
            "primary_topic",
            "type",
        ]
    )
    return _fetch_query_pages(
        queries,
        max_results,
        lambda query, per_query: _get_json(
            OPENALEX_API_URL,
            {
                "search": query,
                "filter": (
                    f"from_publication_date:{start:%Y-%m-%d},"
                    f"to_publication_date:{end:%Y-%m-%d}"
                ),
                "sort": "publication_date:desc",
                "per_page": str(per_query),
                "select": select,
                **params_extra,
            },
        ).get("results", []),
        _parse_openalex_work,
        float(source_config.get("request_pause_seconds", 0.5)),
    )


def _fetch_crossref(
    queries: list[str],
    start: datetime,
    end: datetime,
    max_results: int,
    source_config: dict[str, Any],
) -> list[Paper]:
    headers = _default_headers()
    return _fetch_query_pages(
        queries,
        max_results,
        lambda query, per_query: _get_json(
            CROSSREF_API_URL,
            {
                "query.bibliographic": query,
                "filter": f"from-pub-date:{start:%Y-%m-%d},until-pub-date:{end:%Y-%m-%d}",
                "sort": "published",
                "order": "desc",
                "rows": str(per_query),
            },
            headers=headers,
        )
        .get("message", {})
        .get("items", []),
        _parse_crossref_work,
        float(source_config.get("request_pause_seconds", 0.5)),
    )


def _fetch_semantic_scholar(
    queries: list[str],
    start: datetime,
    end: datetime,
    max_results: int,
    source_config: dict[str, Any],
) -> list[Paper]:
    headers = _default_headers()
    api_key = os.getenv("S2_API_KEY") or source_config.get("semantic_scholar", {}).get("api_key")
    if api_key:
        headers["x-api-key"] = str(api_key)
    fields = ",".join(
        [
            "paperId",
            "title",
            "abstract",
            "authors",
            "url",
            "year",
            "publicationDate",
            "externalIds",
            "publicationTypes",
            "venue",
            "openAccessPdf",
        ]
    )
    return _fetch_query_pages(
        queries,
        max_results,
        lambda query, per_query: _get_json(
            SEMANTIC_SCHOLAR_API_URL,
            {
                "query": query,
                "limit": str(min(per_query, 100)),
                "fields": fields,
                "publicationDateOrYear": f"{start:%Y-%m-%d}:{end:%Y-%m-%d}",
            },
            headers=headers,
        ).get("data", []),
        _parse_semantic_scholar_paper,
        float(source_config.get("request_pause_seconds", 0.5)),
    )


def _fetch_europe_pmc(
    queries: list[str],
    start: datetime,
    end: datetime,
    max_results: int,
    source_config: dict[str, Any],
) -> list[Paper]:
    return _fetch_query_pages(
        queries,
        max_results,
        lambda query, per_query: _get_json(
            EUROPE_PMC_API_URL,
            {
                "query": f'({query}) AND FIRST_PDATE:[{start:%Y-%m-%d} TO {end:%Y-%m-%d}]',
                "format": "json",
                "resultType": "core",
                "pageSize": str(per_query),
                "sort": "FIRST_PDATE desc",
            },
        )
        .get("resultList", {})
        .get("result", []),
        _parse_europe_pmc_work,
        float(source_config.get("request_pause_seconds", 0.5)),
    )


def _fetch_journal_watchlist(
    start: datetime,
    end: datetime,
    max_results: int,
    source_config: dict[str, Any],
) -> list[Paper]:
    config = source_config.get("journal_watchlist", {})
    journals = config.get("journals") or []
    if not journals:
        return []

    headers = _default_headers()
    per_journal = int(config.get("max_results_per_journal", 5))
    source_limit = int(config.get("max_results", max_results * 3))
    pause_seconds = float(source_config.get("request_pause_seconds", 2.0))
    papers: list[Paper] = []

    for journal in journals:
        issns = _journal_issns(journal)
        if not issns:
            continue
        try:
            items = _get_json(
                CROSSREF_API_URL,
                {
                    "filter": (
                        f"issn:{issns[0]},"
                        f"from-pub-date:{start:%Y-%m-%d},"
                        f"until-pub-date:{end:%Y-%m-%d}"
                    ),
                    "sort": "published",
                    "order": "desc",
                    "rows": str(per_journal),
                },
                headers=headers,
            ).get("message", {}).get("items", [])
        except (TimeoutError, SocketTimeout, urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
            if pause_seconds > 0:
                time.sleep(pause_seconds)
            continue
        for item in items:
            paper = _parse_crossref_work(item)
            if paper is None:
                continue
            paper.source = _combine_sources(paper.source, "Journal Watchlist")
            _tag_watchlist_paper(paper, journal)
            papers.append(paper)
        if len(papers) >= source_limit:
            break
        if pause_seconds > 0:
            time.sleep(pause_seconds)

    return papers[:source_limit]


def _fetch_query_pages(
    queries: list[str],
    max_results: int,
    fetch_items: Callable[[str, int], list[dict[str, Any]]],
    parse_item: Callable[[dict[str, Any]], Paper | None],
    pause_seconds: float,
) -> list[Paper]:
    papers = []
    per_query = max(1, min(max_results, 10))
    for query in queries:
        try:
            items = fetch_items(query, per_query)
        except (TimeoutError, SocketTimeout, urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
            if pause_seconds > 0:
                time.sleep(pause_seconds)
            continue
        for item in items:
            paper = parse_item(item)
            if paper is not None:
                papers.append(paper)
        if len(papers) >= max_results:
            break
        if pause_seconds > 0:
            time.sleep(pause_seconds)
    return papers[:max_results]


def _parse_openalex_work(work: dict[str, Any]) -> Paper | None:
    title = _clean_text(work.get("display_name") or "")
    if not title:
        return None
    doi = _normalize_doi(work.get("doi"))
    work_id = str(work.get("id") or "").rstrip("/").split("/")[-1]
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    url = location.get("landing_page_url") or (f"https://doi.org/{doi}" if doi else work.get("id"))
    pdf_url = location.get("pdf_url")
    open_access = work.get("open_access") or {}
    if not pdf_url:
        pdf_url = open_access.get("oa_url")
    authors = [
        _clean_text((authorship.get("author") or {}).get("display_name") or "")
        for authorship in work.get("authorships") or []
    ]
    categories = [
        _clean_text(source.get("display_name") or ""),
        _clean_text((work.get("primary_topic") or {}).get("display_name") or ""),
        _clean_text(work.get("type") or ""),
    ]
    published = _parse_date(work.get("publication_date")) or datetime.now(UTC)
    return Paper(
        paper_id=_paper_id("openalex", doi, work_id),
        title=title,
        authors=[author for author in authors if author],
        abstract=_abstract_from_inverted_index(work.get("abstract_inverted_index") or {}),
        published=published,
        updated=_parse_date(work.get("updated_date"), fallback=published),
        url=str(url),
        source="OpenAlex",
        pdf_url=pdf_url,
        doi=doi,
        primary_category=categories[1] or categories[0] or None,
        categories=[category for category in categories if category],
    )


def _parse_crossref_work(work: dict[str, Any]) -> Paper | None:
    title = _clean_text(_first(work.get("title")) or "")
    if not title:
        return None
    doi = _normalize_doi(work.get("DOI"))
    published = _date_from_crossref(work) or datetime.now(UTC)
    authors = []
    for author in work.get("author") or []:
        name = " ".join(str(part) for part in [author.get("given"), author.get("family")] if part)
        if not name and author.get("name"):
            name = str(author["name"])
        if name:
            authors.append(_clean_text(name))
    categories = [_clean_text(subject) for subject in work.get("subject") or []]
    container_title = _clean_text(_first(work.get("container-title")) or "")
    if container_title:
        categories.append(container_title)
    work_type = _clean_text(work.get("type") or "")
    if work_type:
        categories.append(work_type)
    return Paper(
        paper_id=_paper_id("crossref", doi, work.get("DOI") or work.get("URL") or title),
        title=title,
        authors=authors,
        abstract=_clean_html(work.get("abstract") or ""),
        published=published,
        updated=_parse_crossref_deposited(work.get("deposited")) or published,
        url=str(work.get("URL") or (f"https://doi.org/{doi}" if doi else "")),
        source="Crossref",
        doi=doi,
        primary_category=categories[0] if categories else None,
        categories=categories,
    )


def _parse_semantic_scholar_paper(work: dict[str, Any]) -> Paper | None:
    title = _clean_text(work.get("title") or "")
    if not title:
        return None
    external_ids = work.get("externalIds") or {}
    doi = _normalize_doi(external_ids.get("DOI"))
    arxiv_id = external_ids.get("ArXiv")
    paper_id = _paper_id("semantic_scholar", doi, arxiv_id or work.get("paperId") or title)
    pdf = work.get("openAccessPdf") or {}
    categories = [_clean_text(work.get("venue") or "")]
    categories.extend(_clean_text(item) for item in work.get("publicationTypes") or [])
    published = _parse_date(work.get("publicationDate"))
    if published is None and work.get("year"):
        published = datetime(int(work["year"]), 1, 1, tzinfo=UTC)
    published = published or datetime.now(UTC)
    return Paper(
        paper_id=paper_id,
        title=title,
        authors=[
            _clean_text(author.get("name") or "")
            for author in work.get("authors") or []
            if author.get("name")
        ],
        abstract=_clean_text(work.get("abstract") or ""),
        published=published,
        updated=published,
        url=str(work.get("url") or (f"https://doi.org/{doi}" if doi else "")),
        source="Semantic Scholar",
        pdf_url=pdf.get("url"),
        doi=doi,
        primary_category=categories[0] if categories and categories[0] else None,
        categories=[category for category in categories if category],
    )


def _parse_europe_pmc_work(work: dict[str, Any]) -> Paper | None:
    title = _clean_text(work.get("title") or "")
    if not title:
        return None
    doi = _normalize_doi(work.get("doi"))
    source = str(work.get("source") or "MED")
    record_id = str(work.get("id") or work.get("pmid") or work.get("pmcid") or title)
    authors = [
        _clean_text(author)
        for author in re.split(r",\s*", work.get("authorString") or "")
        if author.strip()
    ]
    categories = [
        _clean_text(work.get("journalTitle") or ""),
        _clean_text(work.get("pubType") or ""),
        source,
    ]
    published = _parse_date(work.get("firstPublicationDate") or work.get("firstIndexDate"))
    published = published or datetime.now(UTC)
    return Paper(
        paper_id=_paper_id("europe_pmc", doi, record_id),
        title=title,
        authors=authors,
        abstract=_clean_html(work.get("abstractText") or ""),
        published=published,
        updated=_parse_date(work.get("firstIndexDate"), fallback=published),
        url=f"https://europepmc.org/article/{source}/{record_id}",
        source="Europe PMC",
        doi=doi,
        primary_category=categories[0] if categories and categories[0] else None,
        categories=[category for category in categories if category],
    )


def _get_json(
    url: str,
    params: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout_seconds: int = 45,
    retries: int = 1,
) -> dict[str, Any]:
    query = urllib.parse.urlencode({key: value for key, value in params.items() if value is not None})
    request = urllib.request.Request(f"{url}?{query}", headers=headers or _default_headers())
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt >= retries:
                raise
            retry_after = exc.headers.get("Retry-After")
            delay = int(retry_after) if retry_after and retry_after.isdigit() else 20 * (attempt + 1)
            time.sleep(delay)
        except (TimeoutError, SocketTimeout, urllib.error.URLError):
            if attempt >= retries:
                raise
            time.sleep(20 * (attempt + 1))
    return {}


def _journal_issns(journal: dict[str, Any]) -> list[str]:
    issns = journal.get("issn") or journal.get("issns") or []
    if isinstance(issns, str):
        issns = [issns]
    return [_clean_text(issn) for issn in issns if _clean_text(issn)]


def _tag_watchlist_paper(paper: Paper, journal: dict[str, Any]) -> None:
    tags = []
    for key in ["name", "publisher", "group"]:
        value = _clean_text(journal.get(key) or "")
        if value:
            tags.append(value)
    raw_tags = journal.get("tags") or []
    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]
    tags.extend(_clean_text(tag) for tag in raw_tags if _clean_text(tag))
    paper.categories = sorted(set(paper.categories + tags))
    if not paper.primary_category:
        paper.primary_category = _clean_text(journal.get("name") or "") or None


def _deduplicate_papers(papers: list[Paper]) -> list[Paper]:
    by_key: dict[str, Paper] = {}
    for paper in papers:
        key = _dedupe_key(paper)
        if key in by_key:
            _merge_paper(by_key[key], paper)
        else:
            by_key[key] = paper
    return sorted(by_key.values(), key=lambda paper: paper.updated, reverse=True)


def _merge_paper(target: Paper, incoming: Paper) -> None:
    if len(incoming.abstract) > len(target.abstract):
        target.abstract = incoming.abstract
    if not target.pdf_url and incoming.pdf_url:
        target.pdf_url = incoming.pdf_url
    if not target.doi and incoming.doi:
        target.doi = incoming.doi
    if len(incoming.authors) > len(target.authors):
        target.authors = incoming.authors
    if incoming.updated > target.updated:
        target.updated = incoming.updated
    target.categories = sorted(set(target.categories + incoming.categories))
    target.source = _combine_sources(target.source, incoming.source)


def _dedupe_key(paper: Paper) -> str:
    doi = _normalize_doi(paper.doi)
    if doi:
        return f"doi:{doi}"
    if paper.source == "arXiv":
        return f"arxiv:{paper.paper_id.lower()}"
    return f"{paper.source.lower()}:{paper.paper_id.lower()}"


def _combine_sources(first: str, second: str) -> str:
    sources = []
    for source in [*first.split(" + "), *second.split(" + ")]:
        if source and source not in sources:
            sources.append(source)
    return " + ".join(sources)


def _paper_id(source: str, doi: str | None, fallback: Any) -> str:
    if doi:
        return f"doi:{doi}"
    fallback_text = _clean_text(str(fallback or "unknown")).replace("/", "_")
    return f"{source}:{fallback_text}"


def _normalize_doi(value: Any) -> str | None:
    if not value:
        return None
    doi = str(value).strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    doi = doi.removeprefix("doi:")
    return doi.lower() or None


def _abstract_from_inverted_index(index: dict[str, list[int]]) -> str:
    if not index:
        return ""
    positions = [position for word_positions in index.values() for position in word_positions]
    if not positions:
        return ""
    max_position = max(positions)
    words = [""] * (max_position + 1)
    for word, positions in index.items():
        for position in positions:
            words[position] = word
    return _clean_text(" ".join(words))


def _date_from_crossref(work: dict[str, Any]) -> datetime | None:
    for key in ["published-print", "published-online", "published", "issued", "created"]:
        date = _parse_crossref_date_parts(work.get(key))
        if date is not None:
            return date
    return None


def _parse_crossref_date_parts(value: dict[str, Any] | None) -> datetime | None:
    if not value:
        return None
    date_parts = value.get("date-parts") or []
    if not date_parts or not date_parts[0]:
        return None
    parts = [int(part) for part in date_parts[0]]
    year = parts[0]
    month = parts[1] if len(parts) > 1 else 1
    day = parts[2] if len(parts) > 2 else 1
    return datetime(year, month, day, tzinfo=UTC)


def _parse_crossref_deposited(value: dict[str, Any] | None) -> datetime | None:
    if not value:
        return None
    if value.get("date-time"):
        return _parse_date(value["date-time"])
    return _parse_crossref_date_parts(value)


def _parse_date(value: Any, fallback: datetime | None = None) -> datetime | None:
    if not value:
        return fallback
    text = str(value).strip()
    try:
        if re.fullmatch(r"\d{4}", text):
            return datetime(int(text), 1, 1, tzinfo=UTC)
        if re.fullmatch(r"\d{4}-\d{2}", text):
            return datetime.fromisoformat(f"{text}-01").replace(tzinfo=UTC)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        return fallback


def _clean_html(value: str) -> str:
    return _clean_text(re.sub(r"<[^>]+>", " ", html.unescape(value)))


def _clean_text(value: Any) -> str:
    return " ".join(str(value).replace("\n", " ").split())


def _first(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _default_headers() -> dict[str, str]:
    mailto = os.getenv("CONTACT_EMAIL", "example@example.com")
    return {"User-Agent": f"laser-ion-paper-digest/0.1 (mailto:{mailto})"}


def _source_label(source: str) -> str:
    return {
        "arxiv": "arXiv",
        "openalex": "OpenAlex",
        "crossref": "Crossref",
        "semantic_scholar": "Semantic Scholar",
        "europe_pmc": "Europe PMC",
        "journal_watchlist": "Journal Watchlist",
    }.get(source, source)
