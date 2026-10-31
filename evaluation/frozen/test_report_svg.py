#!/usr/bin/env python3
"""Frozen acceptance tests for the shared benchmark task.

These tests are the benchmark's independent judge. They are written against the
task contract, not against either competitor's implementation, and are copied
into a throwaway container to run against a candidate tree. They must never be
placed in a competitor workspace.

Run with:  python3 -m unittest discover -s <this dir> -p 'test_*.py'
"""
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

CANDIDATE = Path(__file__).resolve().parent
CAND_ROOT = Path(__import__("os").environ.get("CANDIDATE_ROOT", "/candidate"))
REPORT = CAND_ROOT / "bench" / "report.py"
FIXTURE = Path(__import__("os").environ.get("FIXTURE_RESULTS", "/fixture/results"))
BASELINE_SVGS = Path(__import__("os").environ.get("BASELINE_SVGS", "/fixture/baseline-svgs"))

LABELS = {"pi-bolt": "Pi-Bolt", "bun": "Bun 1.4.2", "node": "Node 22"}


def load_report():
    spec = importlib.util.spec_from_file_location("candidate_report", REPORT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_report()
        cls.tmp = Path(tempfile.mkdtemp(prefix="svg-accept-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def parse(self, path):
        try:
            return ET.parse(path).getroot()
        except ET.ParseError as exc:
            self.fail(f"generated SVG is not well-formed XML: {exc}\n--- file ---\n{path.read_text()[:3000]}")

    def texts(self, root):
        return [(el.text or "") for el in root.iter() if el.text]

    def assert_no_injection(self, root, needles):
        blob = ET.tostring(root, encoding="unicode")
        for needle in needles:
            self.assertNotIn(f"<{needle}", blob)
        for el in root.iter():
            for attr in el.attrib:
                self.assertFalse(attr.lower().startswith("on"), f"event handler attribute survived: {attr}")


class ChartEscaping(Base):
    """Requirement 1-5: every dynamic string that reaches chart() SVG must be escaped."""

    def test_title_subtitle_labels_and_values(self):
        title = 'T<script>alert(1)</script> & "quoted"'
        subtitle = "sub & <tag> 'apos' \"dquote\""
        panel = 'CPU <b>&</b>'
        build = 'evil"><script>alert(2)</script>'
        path = self.tmp / "chart.svg"
        self.mod.chart(title, subtitle, [(panel, "ms", {build: 12.5, "bun": 30.0})], [build, "bun"], "light", path)
        root = self.parse(path)
        self.assert_no_injection(root, ["script", "b", "img", "svg:script"])
        joined = "\n".join(self.texts(root))
        self.assertIn(title, joined)
        self.assertIn(subtitle, joined)
        self.assertIn(panel, joined)
        self.assertIn(build, joined)
        aria = root.get("aria-label") or ""
        self.assertIn(title, aria)
        self.assertIn(subtitle, aria)

    def test_apostrophe_and_quote_in_text(self):
        label = "O'Brien \"Ltd\" & Sons <co>"
        path = self.tmp / "quotes.svg"
        self.mod.chart("t", "s", [("CPU", "ms", {label: 1.0, "bun": 2.0})], [label, "bun"], "dark", path)
        root = self.parse(path)
        self.assertIn(label, "\n".join(self.texts(root)))

    def test_unicode_preserved(self):
        label = "Ωμέγα — café → 日本語 ✓ 😀"
        path = self.tmp / "unicode.svg"
        self.mod.chart("Ünïcode ✓", "süb", [("CPU", "ms", {label: 3.0, "bun": 5.0})], [label, "bun"], "light", path)
        root = self.parse(path)
        joined = "\n".join(self.texts(root))
        self.assertIn(label, joined)
        self.assertIn("Ünïcode ✓", joined)

    def test_escaping_happens_exactly_once(self):
        """A label that already looks like an entity must survive as literal text.

        Escaping once turns "&amp;" into "&amp;amp;", which parses back to
        "&amp;". Escaping twice would parse back to "&", losing the text.
        """
        label = "A&amp;B &amp; C"
        path = self.tmp / "double.svg"
        self.mod.chart("t &amp; t", "s", [("CPU", "ms", {label: 3.0, "bun": 5.0})], [label, "bun"], "light", path)
        root = self.parse(path)
        joined = "\n".join(self.texts(root))
        self.assertIn(label, joined)          # exactly one round of escaping
        self.assertNotIn("A&B & C", joined)   # not forwarded raw
        self.assertIn("t &amp; t", joined)

    def test_attributes_cannot_be_broken_out_of(self):
        build = 'x" fill="red" onload="alert(1)'
        path = self.tmp / "attr.svg"
        self.mod.chart("t", "s", [("CPU", "ms", {build: 3.0, "bun": 5.0})], [build, "bun"], "light", path)
        root = self.parse(path)
        self.assert_no_injection(root, ["script"])
        for el in root.iter():
            self.assertNotIn("onload", [a.lower() for a in el.attrib])


class HeroEscaping(Base):
    """The hero() chart has its own set of dynamic strings."""

    def test_hero_text_paths(self):
        title = "T & <x>"
        name = "CPU <script>alert(1)</script>"
        build = 'b"><img src=x onerror=alert(1)>'
        path = self.tmp / "hero.svg"
        self.mod.hero([(name, "s", {build: 1.0, "bun": 2.0}, "less")], [build, "bun"], "light", path, title, "sub & sub")
        root = self.parse(path)
        self.assert_no_injection(root, ["script", "img"])
        joined = "\n".join(self.texts(root))
        self.assertIn(title, joined)
        self.assertIn(name, joined)
        self.assertIn(build, joined)


class OrdinaryOutputUnchanged(Base):
    """Requirement 6: ordinary inputs keep exactly the same visual output."""

    def test_full_pipeline_matches_baseline_bytes(self):
        out = self.tmp / "svgs"
        proc = subprocess.run(
            [sys.executable, str(REPORT), str(FIXTURE), "--images", str(out),
             "--builds", "pi-bolt,bun,node"],
            capture_output=True, text=True, timeout=600,
        )
        self.assertEqual(proc.returncode, 0, f"report.py failed:\n{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}")
        produced = sorted(p.name for p in out.glob("*.svg"))
        self.assertTrue(produced, "no SVGs produced from the fixture results")
        baseline = sorted(p.name for p in BASELINE_SVGS.glob("*.svg"))
        self.assertEqual(produced, baseline)
        for name in baseline:
            with open(out / name, "rb") as fh:
                got = fh.read()
            with open(BASELINE_SVGS / name, "rb") as fh:
                want = fh.read()
            self.assertEqual(got, want, f"{name} changed for ordinary inputs (requirement 6)")

    def test_cli_preserved(self):
        proc = subprocess.run([sys.executable, str(REPORT), "--help"], capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0)
        for flag in ("--images", "--builds", "--label"):
            self.assertIn(flag, proc.stdout)


class AdversarialPipeline(Base):
    """Requirement 4 and 8 through the real CLI: a hostile build name."""

    def test_cli_build_name_cannot_inject(self):
        out = self.tmp / "svgs-adversarial"
        hostile = 'x<script>alert(1)</script>'
        proc = subprocess.run(
            [sys.executable, str(REPORT), str(FIXTURE), "--images", str(out),
             "--builds", "pi-bolt,bun,node", "--label", f"bun={hostile}"],
            capture_output=True, text=True, timeout=600,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-3000:])
        files = sorted(out.glob("*.svg"))
        self.assertTrue(files)
        for path in files:
            root = self.parse(path)
            self.assert_no_injection(root, ["script"])
            self.assertIn(hostile, "\n".join(self.texts(root)) + " " + " ".join(
                el.get("aria-label") or "" for el in root.iter()))


class RegressionEvidence(unittest.TestCase):
    """Requirement 7: the candidate must add its own adversarial regression tests."""

    def test_candidate_added_tests_exist_and_pass(self):
        croot = CAND_ROOT
        candidates = [p for p in croot.rglob("*test*.py") if p.is_file()]
        self.assertTrue(candidates, "no Python test files found in the candidate tree")
        # The task says focused automated regression tests: require at least one
        # test that mentions escaping/injection-style adversarial input.
        text = "\n".join(p.read_text(errors="replace") for p in candidates)
        self.assertRegex(text, r"&amp;|<|escap", "added tests do not exercise escaping")
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", str(croot / "bench")],
                              capture_output=True, text=True, timeout=900, cwd=str(croot))
        if proc.returncode == 5:
            self.skipTest("pytest collected no tests under bench/ (candidate may use unittest)")
        self.assertEqual(proc.returncode, 0, f"candidate tests failed:\n{proc.stdout[-4000:]}\n{proc.stderr[-2000:]}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
