#!/usr/bin/env python3
"""Post-hoc independent check derived from the task's "preserve the existing
command-line interface" constraint: --help output and the Markdown tables must
be unchanged for ordinary inputs. Applied blind to all four candidate trees.
"""
import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path

CAND = Path(os.environ.get("CANDIDATE_ROOT", "/candidate"))
BASE = Path(os.environ.get("BASELINE_ROOT", "/baseline"))
FIXTURE = Path(os.environ.get("FIXTURE_RESULTS", "/fixture/results"))


class CliParity(unittest.TestCase):
    def test_help_output_byte_identical(self):
        def help_of(root):
            return subprocess.run([sys.executable, str(root / "bench" / "report.py"), "--help"],
                                  capture_output=True, text=True, timeout=120)
        a, b = help_of(BASE), help_of(CAND)
        self.assertEqual(a.returncode, b.returncode)
        self.assertEqual(a.stdout, b.stdout, "--help output changed")

    def test_tables_unchanged_for_ordinary_results(self):
        def tables(root):
            p = subprocess.run([sys.executable, str(root / "bench" / "report.py"), str(FIXTURE),
                                "--images", "/tmp/imgs-" + root.name, "--builds", "pi-bolt,bun,node"],
                               capture_output=True, text=True, timeout=600)
            return p.returncode, p.stdout
        a, b = tables(BASE), tables(CAND)
        self.assertEqual(a[0], 0)
        self.assertEqual(b[0], 0)
        self.assertEqual(a[1], b[1], "Markdown tables changed for ordinary results")


if __name__ == "__main__":
    unittest.main(verbosity=2)
