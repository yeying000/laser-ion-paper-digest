from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import Paper, PaperSummary


def render_report(
    papers: list[tuple[Paper, PaperSummary]],
    title: str,
    report_date: datetime,
    timezone: str,
    warnings: list[str] | None = None,
) -> str:
    local_date = report_date.astimezone(ZoneInfo(timezone))
    date_text = local_date.strftime("%Y-%m-%d")
    lines = [
        f"# {title} - {date_text}",
        "",
        f"- 生成时间：{local_date.strftime('%Y-%m-%d %H:%M %Z')}",
        f"- 入选论文数：{len(papers)}",
        "- 说明：本报告基于 arXiv 元数据和摘要自动生成；未在摘要中出现的参数不会被推断。",
        "",
    ]

    if warnings:
        lines.extend(["## 数据源告警", ""])
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")

    lines.extend(["## 今日概览", ""])

    if not papers:
        lines.extend(["今日未检索到达到相关性阈值的新论文或更新论文。", ""])
        return "\n".join(lines)

    mechanisms = _count_by([summary.mechanism for _, summary in papers])
    study_types = _count_by([summary.study_type for _, summary in papers])
    research_categories = _count_by([summary.research_category for _, summary in papers])
    lines.extend(
        [
            f"- 主要机制：{_format_counts(mechanisms)}",
            f"- 研究类型：{_format_counts(study_types)}",
            f"- 方向分类：{_format_counts(research_categories)}",
            f"- 最高相关性分数：{max(paper.score for paper, _ in papers)}",
            "",
            "## 最值得优先阅读",
            "",
        ]
    )

    for index, (paper, summary) in enumerate(papers[:3], start=1):
        lines.extend(
            [
                f"{index}. [{paper.title}]({paper.url})",
                f"   - {summary.one_sentence}",
                f"   - 重要性：{summary.why_it_matters}",
            ]
        )

    lines.extend(["", "## 论文详情", ""])
    for index, (paper, summary) in enumerate(papers, start=1):
        lines.extend(_render_paper(index, paper, summary))

    lines.extend(["", "## 原始链接", ""])
    for paper, _ in papers:
        pdf = f" | [PDF]({paper.pdf_url})" if paper.pdf_url else ""
        lines.append(f"- [{paper.paper_id}]({paper.url}){pdf} - {paper.title}")

    return "\n".join(lines).rstrip() + "\n"


def write_report(markdown: str, reports_dir: str | Path, report_date: datetime, timezone: str) -> Path:
    local_date = report_date.astimezone(ZoneInfo(timezone))
    year_dir = Path(reports_dir) / local_date.strftime("%Y")
    year_dir.mkdir(parents=True, exist_ok=True)
    path = year_dir / f"{local_date:%Y-%m-%d}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


def _render_paper(index: int, paper: Paper, summary: PaperSummary) -> list[str]:
    authors = ", ".join(paper.authors[:8])
    if len(paper.authors) > 8:
        authors += " 等"
    return [
        f"### {index}. {paper.title}",
        "",
        f"- 链接：[{paper.paper_id}]({paper.url})",
        f"- 作者：{authors or '未提供'}",
        f"- 分类：{paper.primary_category or '未提供'}",
        f"- 发布/更新：{paper.published.date()} / {paper.updated.date()}",
        f"- 相关性分数：{paper.score}",
        f"- 命中词：{', '.join(paper.matched_terms) if paper.matched_terms else '无'}",
        f"- 一句话结论：{summary.one_sentence}",
        f"- 方向分类：{summary.research_category}",
        f"- 机制：{summary.mechanism}",
        f"- 研究类型：{summary.study_type}",
        f"- 激光参数：{summary.laser_parameters}",
        f"- 靶材：{summary.target}",
        f"- 离子种类：{summary.ion_species}",
        f"- 最高能量/关键结果：{summary.max_energy}",
        f"- 主要贡献：{summary.main_contribution}",
        f"- 局限或注意点：{summary.limitations}",
        f"- 为什么重要：{summary.why_it_matters}",
        "",
    ]


def _count_by(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: item[1], reverse=True))


def _format_counts(counts: dict[str, int]) -> str:
    return "；".join(f"{key} {value} 篇" for key, value in counts.items())
