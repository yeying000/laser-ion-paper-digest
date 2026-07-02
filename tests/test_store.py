from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from paper_digest.models import Paper, PaperSummary
from paper_digest.store import PaperStore


class StoreTests(unittest.TestCase):
    def test_store_saves_and_loads_summary_for_slots_dataclass(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = PaperStore(Path(tmpdir) / "papers.sqlite")
            now = datetime(2026, 1, 1, tzinfo=UTC)
            paper = Paper(
                paper_id="2601.00001",
                title="Laser ion acceleration",
                authors=["A. Researcher"],
                abstract="Abstract.",
                published=now,
                updated=now,
                url="https://arxiv.org/abs/2601.00001",
                categories=["physics.plasm-ph"],
            )
            summary = PaperSummary(
                research_category="实验",
        one_sentence="Finding.",
                mechanism="TNSA",
                study_type="experiment",
                laser_parameters="摘要中未明确说明",
                target="摘要中未明确说明",
                ion_species="proton",
                max_energy="摘要中未明确说明",
                main_contribution="Contribution.",
                limitations="Limitations.",
                why_it_matters="Importance.",
            )

            self.assertTrue(store.upsert_paper(paper))
            store.save_summary(paper.paper_id, summary)
            loaded = store.get_summary(paper.paper_id)
            store.close()

            self.assertEqual(loaded, summary)
