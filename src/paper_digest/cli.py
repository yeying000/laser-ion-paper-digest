from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from .arxiv import fetch_recent_papers
from .config import ensure_project_dirs, load_config
from .models import Paper, PaperSummary
from .ranking import rank_papers
from .report import render_report, write_report
from .store import PaperStore
from .summarizer import make_summarizer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a daily laser ion acceleration paper digest.")
    parser.add_argument("--config", default="configs/queries.json", help="Path to JSON config.")
    parser.add_argument("--db", default="data/papers.sqlite", help="Path to SQLite database.")
    parser.add_argument("--reports-dir", default="reports", help="Directory for generated reports.")
    parser.add_argument("--no-openai", action="store_true", help="Disable OpenAI summarization even if a key is set.")
    parser.add_argument("--max-papers", type=int, default=None, help="Override report max_papers.")
    parser.add_argument("--lookback-days", type=int, default=None, help="Override arXiv lookback_days.")
    parser.add_argument("--pause-seconds", type=float, default=3.0, help="Delay between arXiv requests.")
    parser.add_argument(
        "--allow-fetch-failure",
        action="store_true",
        help="Generate a warning report instead of failing when arXiv is temporarily unavailable.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print report instead of writing it.")
    args = parser.parse_args(argv)

    ensure_project_dirs()
    config = load_config(args.config)
    report_config = config["report"]
    arxiv_config = config["arxiv"]

    print("Fetching arXiv papers...", file=sys.stderr)
    warnings = []
    try:
        papers = fetch_recent_papers(
            queries=config["queries"],
            categories=arxiv_config["categories"],
            lookback_days=args.lookback_days or int(arxiv_config.get("lookback_days", 3)),
            max_results=int(arxiv_config.get("max_results", 80)),
            pause_seconds=args.pause_seconds,
        )
    except Exception as exc:
        if not args.allow_fetch_failure:
            raise
        warning = f"arXiv 暂时不可用，本次未能完成论文抓取：{exc}"
        print(f"Warning: {warning}", file=sys.stderr)
        warnings.append(warning)
        papers = []
    print(f"Fetched {len(papers)} unique papers.", file=sys.stderr)

    ranked = rank_papers(papers, config["ranking"])
    max_papers = args.max_papers or int(report_config.get("max_papers", 12))
    selected = ranked[:max_papers]
    print(f"Selected {len(selected)} papers after ranking.", file=sys.stderr)

    store = PaperStore(args.db)
    summarizer = make_summarizer(use_openai=not args.no_openai)
    paper_summaries: list[tuple[Paper, PaperSummary]] = []
    try:
        for paper in ranked:
            store.upsert_paper(paper)
        for paper in selected:
            summary = store.get_summary(paper.paper_id)
            if summary is None:
                try:
                    summary = summarizer.summarize(paper)
                except Exception as exc:
                    print(f"Warning: summarization failed for {paper.paper_id}: {exc}", file=sys.stderr)
                    summary = PaperSummary.fallback(paper)
                store.save_summary(paper.paper_id, summary)
            paper_summaries.append((paper, summary))
    finally:
        store.close()

    now = datetime.now(UTC)
    markdown = render_report(
        papers=paper_summaries,
        title=report_config.get("title", "Daily Paper Digest"),
        report_date=now,
        timezone=report_config.get("timezone", "UTC"),
        warnings=warnings,
    )

    if args.dry_run:
        print(markdown)
    else:
        path = write_report(
            markdown,
            reports_dir=Path(args.reports_dir),
            report_date=now,
            timezone=report_config.get("timezone", "UTC"),
        )
        print(f"Wrote report: {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
