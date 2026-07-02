from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from paper_digest import cli


class CliTests(unittest.TestCase):
    def test_allow_fetch_failure_renders_warning_report(self) -> None:
        stdout = io.StringIO()
        with patch("paper_digest.cli.fetch_recent_papers", side_effect=RuntimeError("source down")):
            with redirect_stdout(stdout):
                exit_code = cli.main(["--allow-fetch-failure", "--dry-run", "--no-openai"])

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("## 数据源告警", output)
        self.assertIn("arXiv 暂时不可用", output)
