#!/usr/bin/env python3
"""Additional adversarial tests written independently of both competitors.

These go beyond the frozen contract checks: they probe edge cases a partial fix
would miss (attribute contexts, CDATA terminators, entity-looking input,
whitespace, and idempotency). They are used for scoring, not all for pass/fail
classification — see independent-evaluation.json.
"""
import importlib.util
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

CAND_ROOT = Path(os.environ.get("CANDIDATE_ROOT", "/candidate"))
REPORT = CAND_ROOT / "bench" / "report.py"


def load_report():
    spec = importlib.util.spec_from_file_location("candidate_report_adv", REPORT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Adversarial(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_report()
        cls.tmp = Path(tempfile.mkdtemp(prefix="svg-adv-"))

    def texts(self, root):
        return [(el.text or "") for el in root.iter() if el.text]

    def chart(self, title, subtitle, label, name="adv.svg"):
        path = self.tmp / name
        self.mod.chart(title, subtitle, [("CPU", "ms", {label: 1.0, "bun": 2.0})], [label, "bun"], "light", path)
        return path, ET.parse(path).getroot()

    def test_cdata_terminator_in_label(self):
        label = "]]><script>alert(1)</script>"
        path, root = self.chart("t", "s", label, "cdata.svg")
        self.assertNotIn("<script", ET.tostring(root, encoding="unicode"))
        self.assertIn(label, "\n".join(self.texts(root)))

    def test_entity_looking_input_is_not_decoded(self):
        label = "&lt;script&gt; &amp; &#x3c;"
        path, root = self.chart("t", "s", label, "entity.svg")
        joined = "\n".join(self.texts(root))
        # Exactly one round of escaping: the literal entity text survives.
        self.assertIn(label, joined)
        self.assertNotIn("<script>", joined)

    def test_title_attribute_breakout(self):
        title = 'q" onmouseover="alert(1)'
        path, root = self.chart(title, "s", "lbl", "breakout.svg")
        for el in root.iter():
            self.assertNotIn("onmouseover", [a.lower() for a in el.attrib])
        self.assertIn(title, root.get("aria-label") or "")

    def test_newlines_and_tabs_preserved_in_text(self):
        label = "line1\nline2\tcol"
        path, root = self.chart("t", "s", label, "ws.svg")
        self.assertIn(label, "\n".join(self.texts(root)))

    def test_escaping_is_idempotent_for_plain_text(self):
        """Escaping must not alter plain ASCII text at all."""
        label = "plain-ascii-2026"
        path, root = self.chart("plain", "plain sub", label, "plain.svg")
        self.assertIn("plain-ascii-2026", "\n".join(self.texts(root)))
        self.assertNotIn("&amp;plain", path.read_text())

    def test_all_dynamic_strings_escaped_in_one_document(self):
        nasty = '<>&"\''
        path = self.tmp / "all.svg"
        self.mod.chart(f"title{nasty}", f"sub{nasty}", [(f"panel{nasty}", "ms", {f"lbl{nasty}": 1.0, "bun": 2.0})],
                       [f"lbl{nasty}", "bun"], "dark", path)
        root = ET.parse(path).getroot()
        blob = ET.tostring(root, encoding="unicode")
        # The only literal markup allowed is the SVG's own.
        self.assertEqual(blob.count("<script"), 0)
        for part in ("title", "sub", "panel", "lbl"):
            self.assertIn(part + nasty, "\n".join(self.texts(root)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
