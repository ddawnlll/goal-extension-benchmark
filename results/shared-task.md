Improve the security and reliability of SVG generation in Pi-Bolt's `bench/report.py`.

The reporting tool generates SVG charts and accepts text that can originate from benchmark metadata, labels and command-line arguments.

Implement correct SVG/XML escaping for text inserted into generated SVG documents.

Requirements:

1. Locate all relevant paths that insert dynamic text into generated SVG markup.
2. Ensure special XML characters are handled safely, including `&`, `<`, `>`, quotation marks and apostrophes where applicable.
3. Preserve legitimate Unicode content.
4. Ensure user-controlled labels cannot inject SVG elements, attributes or scripts.
5. Avoid double escaping.
6. Preserve the existing visual appearance for ordinary inputs.
7. Add focused automated regression tests, including adversarial input.
8. Validate the generated SVG with a standard XML parser.
9. Run relevant existing tests and report their results.
10. Document the behavior where appropriate.

Constraints:

- No unrelated refactoring.
- Do not weaken existing tests.
- Do not modify benchmark result datasets.
- Preserve the existing command-line interface and supported functionality.
- Prefer standard-library solutions.
- Do not require a complete Pi-Bolt runtime rebuild unless genuinely necessary.

Definition of done:

The implementation addresses relevant SVG text-injection paths, generated SVG documents remain valid, regression tests cover malicious and ordinary inputs, existing functionality remains intact, and the result is supported by reproducible evidence.

Do not claim completion without verification.
