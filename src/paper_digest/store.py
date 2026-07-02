from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .models import Paper, PaperSummary


SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    paper_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    authors_json TEXT NOT NULL,
    abstract TEXT NOT NULL,
    published TEXT NOT NULL,
    updated TEXT NOT NULL,
    url TEXT NOT NULL,
    pdf_url TEXT,
    doi TEXT,
    primary_category TEXT,
    categories_json TEXT NOT NULL,
    comment TEXT,
    score INTEGER NOT NULL DEFAULT 0,
    matched_terms_json TEXT NOT NULL DEFAULT '[]',
    summary_json TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
"""


class PaperStore:
    def __init__(self, path: str | Path = "data/papers.sqlite") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def upsert_paper(self, paper: Paper) -> bool:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        existing = self.connection.execute(
            "SELECT paper_id FROM papers WHERE paper_id = ?",
            (paper.paper_id,),
        ).fetchone()
        self.connection.execute(
            """
            INSERT INTO papers (
                paper_id, title, authors_json, abstract, published, updated, url, pdf_url,
                doi, primary_category, categories_json, comment, score, matched_terms_json,
                first_seen, last_seen
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(paper_id) DO UPDATE SET
                title = excluded.title,
                authors_json = excluded.authors_json,
                abstract = excluded.abstract,
                published = excluded.published,
                updated = excluded.updated,
                url = excluded.url,
                pdf_url = excluded.pdf_url,
                doi = excluded.doi,
                primary_category = excluded.primary_category,
                categories_json = excluded.categories_json,
                comment = excluded.comment,
                score = excluded.score,
                matched_terms_json = excluded.matched_terms_json,
                last_seen = excluded.last_seen
            """,
            (
                paper.paper_id,
                paper.title,
                json.dumps(paper.authors, ensure_ascii=False),
                paper.abstract,
                paper.published.isoformat(),
                paper.updated.isoformat(),
                paper.url,
                paper.pdf_url,
                paper.doi,
                paper.primary_category,
                json.dumps(paper.categories, ensure_ascii=False),
                paper.comment,
                paper.score,
                json.dumps(paper.matched_terms, ensure_ascii=False),
                now,
                now,
            ),
        )
        self.connection.commit()
        return existing is None

    def get_summary(self, paper_id: str) -> PaperSummary | None:
        row = self.connection.execute(
            "SELECT summary_json FROM papers WHERE paper_id = ?",
            (paper_id,),
        ).fetchone()
        if not row or not row["summary_json"]:
            return None
        payload = json.loads(row["summary_json"])
        payload.setdefault("research_category", "其他")
        return PaperSummary(**payload)

    def save_summary(self, paper_id: str, summary: PaperSummary) -> None:
        self.connection.execute(
            "UPDATE papers SET summary_json = ? WHERE paper_id = ?",
            (json.dumps(asdict(summary), ensure_ascii=False), paper_id),
        )
        self.connection.commit()
