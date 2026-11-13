# Role: policy
"""Verifica sincronia estrita entre AGENTS.md e tools/dev.py check."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

REQUIRED_GATES_IN_MANUAL = (
    "Role:",
    "250 linhas",
    "utils",
    "Decided",
    "tools/dev.py check",
)


class ManualSyncTests(unittest.TestCase):
    def test_the_checks_are_those_the_agents_manual_requires(self) -> None:
        agents_md = (ROOT_DIR / "AGENTS.md").read_text(encoding="utf-8")
        dev_py = (ROOT_DIR / "tools" / "dev.py").read_text(encoding="utf-8")
        arch_py = (ROOT_DIR / "tools" / "arch_checks.py").read_text(encoding="utf-8")
        combined_tools = dev_py + "\n" + arch_py

        for token in REQUIRED_GATES_IN_MANUAL:
            self.assertIn(token, agents_md, f"Token ausente em AGENTS.md: {token}")
        for step in (
            "check_roles",
            "check_line_limits",
            "check_forbidden_filenames",
            "check_architecture_sync",
            "run_all_tests",
        ):
            self.assertIn(step, combined_tools, f"Etapa ausente nos verificadores: {step}")


if __name__ == "__main__":
    unittest.main()
