from __future__ import annotations

import unittest
from datetime import UTC, datetime

from paper_digest.arxiv import MAX_ARXIV_QUERY_URL_LENGTH, _chunk_queries_for_url, _query_url_length, parse_arxiv_feed


class ArxivParsingTests(unittest.TestCase):
    def test_parse_arxiv_feed_extracts_core_fields(self) -> None:
        feed = b"""<?xml version="1.0" encoding="utf-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
          <entry>
            <id>http://arxiv.org/abs/2601.01234</id>
            <updated>2026-01-02T03:04:05Z</updated>
            <published>2026-01-01T03:04:05Z</published>
            <title>Laser-driven proton acceleration from structured targets</title>
            <summary>We demonstrate laser-driven ion acceleration with improved proton cutoff energy.</summary>
            <author><name>A. Researcher</name></author>
            <author><name>B. Scientist</name></author>
            <link href="http://arxiv.org/abs/2601.01234" rel="alternate" type="text/html"/>
            <link title="pdf" href="http://arxiv.org/pdf/2601.01234" rel="related" type="application/pdf"/>
            <category term="physics.plasm-ph" scheme="http://arxiv.org/schemas/atom"/>
            <arxiv:primary_category term="physics.plasm-ph" scheme="http://arxiv.org/schemas/atom"/>
            <arxiv:doi>10.1234/example</arxiv:doi>
          </entry>
        </feed>
        """

        papers = parse_arxiv_feed(feed)

        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper.paper_id, "2601.01234")
        self.assertEqual(paper.title, "Laser-driven proton acceleration from structured targets")
        self.assertEqual(paper.authors, ["A. Researcher", "B. Scientist"])
        self.assertEqual(paper.pdf_url, "http://arxiv.org/pdf/2601.01234")
        self.assertEqual(paper.primary_category, "physics.plasm-ph")
        self.assertEqual(paper.doi, "10.1234/example")

    def test_chunk_queries_keeps_arxiv_urls_short(self) -> None:
        queries = [f'all:"laser-driven proton irradiation damage query {index}"' for index in range(80)]
        categories = [
            "physics.plasm-ph",
            "physics.acc-ph",
            "physics.optics",
            "physics.comp-ph",
            "physics.med-ph",
            "nucl-ex",
            "cs.LG",
            "cond-mat.mtrl-sci",
        ]
        start = datetime(2026, 7, 1, tzinfo=UTC)
        end = datetime(2026, 7, 2, tzinfo=UTC)

        chunks = _chunk_queries_for_url(queries, categories, start, end)

        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(_query_url_length(chunk, categories, start, end), MAX_ARXIV_QUERY_URL_LENGTH)
