from __future__ import annotations

import unittest
import urllib.error
from datetime import UTC, datetime
from unittest.mock import patch

from paper_digest.models import Paper
from paper_digest.sources import (
    _deduplicate_papers,
    _fetch_journal_watchlist,
    _fetch_query_pages,
    _parse_crossref_work,
    _parse_openalex_work,
    _parse_semantic_scholar_paper,
)


class SourceParsingTests(unittest.TestCase):
    def test_parse_openalex_work_reconstructs_abstract(self) -> None:
        paper = _parse_openalex_work(
            {
                "id": "https://openalex.org/W123",
                "doi": "https://doi.org/10.1234/example",
                "display_name": "Laser-driven proton acceleration",
                "authorships": [{"author": {"display_name": "A. Researcher"}}],
                "publication_date": "2026-07-01",
                "updated_date": "2026-07-02T00:00:00Z",
                "primary_location": {
                    "landing_page_url": "https://doi.org/10.1234/example",
                    "pdf_url": "https://example.org/paper.pdf",
                    "source": {"display_name": "Example Journal"},
                },
                "abstract_inverted_index": {"Laser-driven": [0], "ion": [1], "acceleration": [2]},
                "primary_topic": {"display_name": "Plasma Physics"},
                "type": "article",
            }
        )

        self.assertIsNotNone(paper)
        assert paper is not None
        self.assertEqual(paper.paper_id, "doi:10.1234/example")
        self.assertEqual(paper.source, "OpenAlex")
        self.assertEqual(paper.abstract, "Laser-driven ion acceleration")

    def test_parse_crossref_work_extracts_dates_and_authors(self) -> None:
        paper = _parse_crossref_work(
            {
                "DOI": "10.1234/example",
                "title": ["Laser ion acceleration in thin foils"],
                "author": [{"given": "A.", "family": "Researcher"}],
                "abstract": "<jats:p>Laser-driven proton beams are measured.</jats:p>",
                "published-online": {"date-parts": [[2026, 7, 1]]},
                "deposited": {"date-time": "2026-07-02T00:00:00Z"},
                "URL": "https://doi.org/10.1234/example",
                "subject": ["Physics"],
                "type": "journal-article",
            }
        )

        self.assertIsNotNone(paper)
        assert paper is not None
        self.assertEqual(paper.authors, ["A. Researcher"])
        self.assertEqual(paper.abstract, "Laser-driven proton beams are measured.")
        self.assertEqual(paper.published, datetime(2026, 7, 1, tzinfo=UTC))

    def test_parse_semantic_scholar_prefers_doi_identifier(self) -> None:
        paper = _parse_semantic_scholar_paper(
            {
                "paperId": "abc",
                "title": "Laser-driven proton source",
                "abstract": "A compact laser-driven proton source is demonstrated.",
                "authors": [{"name": "A. Researcher"}],
                "url": "https://www.semanticscholar.org/paper/abc",
                "publicationDate": "2026-07-01",
                "externalIds": {"DOI": "10.1234/example"},
                "publicationTypes": ["JournalArticle"],
                "venue": "Example Journal",
                "openAccessPdf": {"url": "https://example.org/paper.pdf"},
            }
        )

        self.assertIsNotNone(paper)
        assert paper is not None
        self.assertEqual(paper.paper_id, "doi:10.1234/example")
        self.assertEqual(paper.source, "Semantic Scholar")
        self.assertEqual(paper.pdf_url, "https://example.org/paper.pdf")

    def test_deduplicate_papers_merges_sources_by_doi(self) -> None:
        now = datetime(2026, 7, 2, tzinfo=UTC)
        first = Paper(
            paper_id="doi:10.1234/example",
            title="Laser ion acceleration",
            authors=["A"],
            abstract="Short.",
            published=now,
            updated=now,
            url="https://doi.org/10.1234/example",
            source="OpenAlex",
            doi="10.1234/example",
        )
        second = Paper(
            paper_id="doi:10.1234/example",
            title="Laser ion acceleration",
            authors=["A", "B"],
            abstract="Longer abstract about laser-driven proton acceleration.",
            published=now,
            updated=now,
            url="https://doi.org/10.1234/example",
            source="Crossref",
            doi="10.1234/example",
            categories=["Physics"],
        )

        papers = _deduplicate_papers([first, second])

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].source, "OpenAlex + Crossref")
        self.assertEqual(papers[0].authors, ["A", "B"])
        self.assertEqual(papers[0].categories, ["Physics"])

    def test_fetch_journal_watchlist_queries_crossref_by_issn(self) -> None:
        response = {
            "message": {
                "items": [
                    {
                        "DOI": "10.1234/watch",
                        "title": ["Laser-driven ion acceleration in a plasma journal"],
                        "author": [{"given": "A.", "family": "Researcher"}],
                        "abstract": "A laser-driven proton source is reported.",
                        "published-online": {"date-parts": [[2026, 7, 1]]},
                        "URL": "https://doi.org/10.1234/watch",
                        "container-title": ["Physics of Plasmas"],
                        "type": "journal-article",
                    }
                ]
            }
        }
        source_config = {
            "request_pause_seconds": 0,
            "journal_watchlist": {
                "max_results_per_journal": 3,
                "journals": [
                    {
                        "name": "Physics of Plasmas",
                        "publisher": "AIP Publishing",
                        "group": "aip",
                        "issn": ["1089-7674", "1070-664X"],
                        "tags": ["plasma", "laser-plasma"],
                    }
                ],
            },
        }

        with patch("paper_digest.sources._get_json", return_value=response) as get_json:
            papers = _fetch_journal_watchlist(
                datetime(2026, 7, 1, tzinfo=UTC),
                datetime(2026, 7, 2, tzinfo=UTC),
                10,
                source_config,
            )

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].source, "Crossref + Journal Watchlist")
        self.assertIn("Physics of Plasmas", papers[0].categories)
        self.assertIn("laser-plasma", papers[0].categories)
        params = get_json.call_args.args[1]
        self.assertIn("issn:1089-7674", params["filter"])

    def test_fetch_query_pages_skips_failed_query(self) -> None:
        def fetch_items(query: str, per_query: int) -> list[dict[str, object]]:
            if query == "bad":
                raise urllib.error.HTTPError("https://example.org", 429, "Too Many Requests", {}, None)
            return [
                {
                    "paperId": "abc",
                    "title": "Laser-driven proton source",
                    "abstract": "A compact laser-driven proton source is demonstrated.",
                    "authors": [{"name": "A. Researcher"}],
                    "url": "https://www.semanticscholar.org/paper/abc",
                    "publicationDate": "2026-07-01",
                    "externalIds": {"DOI": "10.1234/example"},
                }
            ]

        papers = _fetch_query_pages(["bad", "good"], 10, fetch_items, _parse_semantic_scholar_paper, 0)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].title, "Laser-driven proton source")
