from __future__ import annotations

import unittest
from datetime import UTC, datetime

from paper_digest.models import Paper, PaperSummary
from paper_digest.report import render_report


class ReportTests(unittest.TestCase):
    def test_render_report_includes_core_sections(self) -> None:
        now = datetime(2026, 7, 2, 0, 30, tzinfo=UTC)
        paper = Paper(
            paper_id="2607.00001",
            title="Laser ion acceleration example",
            authors=["A. Researcher"],
            abstract="Example abstract.",
            published=now,
            updated=now,
            url="https://arxiv.org/abs/2607.00001",
            categories=["physics.plasm-ph"],
            score=8,
            matched_terms=["laser ion acceleration"],
        )
        summary = PaperSummary(
            research_category="实验",
        one_sentence="This is a concise finding.",
            mechanism="TNSA",
            study_type="experiment",
            laser_parameters="摘要中未明确说明",
            target="thin foil",
            ion_species="proton",
            max_energy="摘要中未明确说明",
            main_contribution="Improves beam quality.",
            limitations="Needs full text.",
            why_it_matters="Useful for tracking progress.",
        )

        markdown = render_report([(paper, summary)], "激光离子加速每日论文进展", now, "Asia/Shanghai")

        self.assertIn("# 激光离子加速每日论文进展 - 2026-07-02", markdown)
        self.assertIn("## 今日概览", markdown)
        self.assertIn("## 论文详情", markdown)
        self.assertIn("Laser ion acceleration example", markdown)
