from __future__ import annotations

import unittest

from paper_digest.models import infer_ion_species, infer_mechanism, infer_research_category, infer_study_type


class ModelInferenceTests(unittest.TestCase):
    def test_infers_new_mechanism_and_cross_direction_terms(self) -> None:
        self.assertEqual(infer_mechanism("Magnetic Vortex Acceleration of ions"), "MVA")
        self.assertEqual(
            infer_mechanism("ion acceleration in the relativistic transparency regime"),
            "relativistic transparency/BOA",
        )
        self.assertEqual(
            infer_study_type("closed-loop Bayesian optimization for laser-driven proton beams"),
            "machine learning/automation",
        )
        self.assertEqual(infer_ion_species("deuteron and carbon ion acceleration"), "carbon, deuteron")

    def test_infers_research_category_after_laser_ion_core_check(self) -> None:
        self.assertEqual(
            infer_research_category("laser-driven proton irradiation causes single event upset in semiconductor devices"),
            "器件辐照交叉",
        )
        self.assertEqual(
            infer_research_category("laser-driven ion irradiation studies vacancy defects and annealing in materials"),
            "材料辐照交叉",
        )
        self.assertEqual(
            infer_research_category("defect evolution and annealing in irradiated silicon without a laser ion source"),
            "其他/相关性存疑",
        )
