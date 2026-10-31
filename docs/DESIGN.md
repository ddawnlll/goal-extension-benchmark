# Design system

The charts are the argument of this repository, so they are designed rather than
decorated. The language is editorial data journalism (precision, direct labels,
one annotation that says something) crossed with product-dashboard clarity. It is
generated, not drawn by hand, but the annotations are hand-drawn on purpose: a
pen mark draws the eye to the one thing worth reading, while the data marks stay
exact.

References that shaped the rules:

- **Financial Times Visual Vocabulary** — a small, fixed set of chart forms and a
  bias toward direct labelling instead of legends.
- **The Pudding / NYT graphics** — one hand annotation per figure, always stating
  a fact the data already proves.
- **Stripe and Linear dashboards** — restrained chrome, generous whitespace, one
  accent per series, no drop shadows.
- **WCAG 2.2** (1.4.3, 1.4.11, 1.4.1) — the accessibility floor, enforced by
  `tools/check_contrast.py`.

## Constraints that shaped everything

| Constraint | Consequence |
|---|---|
| GitHub renders SVG inside an `<img>` | No webfonts, no external CSS, no JavaScript, no network requests. Type must come from system stacks. |
| The charts are generated from committed data | No manual retouching; every mark is reproducible and `--check` must stay byte-identical. |
| Light and dark GitHub themes | Two files per chart with identical geometry, chosen with `<picture>` and `prefers-color-scheme`. |
| Neutrality | Equal visual weight, equal annotation treatment, no ranking cues, no red/green semantics. |

## Type

| Role | Stack | Sizes |
|---|---|---|
| Display | `ui-serif, 'Iowan Old Style', 'Palatino Linotype', Palatino, Georgia, 'Times New Roman', serif` | 22 (title), 16 (section) |
| Text | `ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif` | 13.5, 12, 11 |
| Numerals | `ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace` | 72, 46, 13.5, 11 |

The serif is the editorial voice; the sans carries labels; the mono is reserved
for measured values, so numbers never shift width between themes and always read
as data rather than prose. Nothing is smaller than 11 px at 1x.

## Colour

Two hues only, plus a neutral ink ramp. The hues were chosen for equal weight and
for separability under deuteranopia (blue vs orange), and every series also
carries a direct label, so color is never the only channel.

| Token | Light | Dark | Role |
|---|---|---|---|
| `surface` | `#ffffff` | `#0b1220` | card background |
| `panel` | `#f8fafc` | `#111a2e` | grouping surface |
| `ink` | `#0f172a` | `#f1f5f9` | primary type |
| `muted` | `#475569` | `#c3cddd` | secondary type |
| `faint` | `#64748b` | `#94a3b8` | captions, axis labels |
| `rule` | `#e2e8f0` | `#26334a` | grid lines |
| `glla` | `#4338ca` | `#a5b4fc` | GLLA series |
| `goalx` | `#b45309` | `#fbbf24` | pi-goal-x series |
| `seg_audit` | `#0f766e` | `#5eead4` | model audit |
| `seg_rework` | `#b45309` | `#fbbf24` | repair after a rejected audit |
| `seg_coding` | `#334155` | `#cbd5e1` | coding and self-testing |
| `seg_*` bands | pale slate | dark slate | drafting, reconciliation, settlement |

Enforced by `python3 tools/check_contrast.py`: every text pair at or above
4.5:1, series and audit fills at or above 3:1 against the surface, in both
themes. The pale band fills sit below 3:1 on purpose; each one is always printed
with its value inside it, so no meaning depends on the fill. The checker lists
them as exempt rather than hiding them.

## Layout

- Canvas 920 px wide, 28 px outer padding, 8 px spacing grid.
- Header band: title baseline 44, subtitle 68, hairline rule 84, optional meta
  line right-aligned at 44.
- Chart body starts at 104–132 depending on the composition; source note sits on
  the last baseline.
- Accent dividers are 1 px `rule` lines, never boxes or shadows.

## Marks

- **Data marks are exact.** Bar extents, dot positions and ranges come straight
  from the committed numbers, snapped to 0.1 px.
- **Hand-drawn marks are annotations only.** `chartkit.scribble`,
  `hand_underline`, `hand_arrow` and `hand_circle` add 0.8–1.5 px of seeded
  jitter to a polyline. The seed is a constant, so the wobble is identical on
  every regeneration.
- One annotation per chart, maximum. It must state something the chart already
  proves (for example "211 s of contract reconciliation, no code defect found"),
  and it must never point at one extension as better.

## Accessibility rules

1. Direct labels on every series and every value; the legend is a convenience,
   not the key.
2. No color-only encoding: the two extensions also differ by position, label and
   (in the timing chart) by open/closed markers.
3. Every document carries `<title>`, `<desc>` and a summary `role="img"`
   `aria-label` that reads the numbers out loud.
4. Text never smaller than 11 px; contrast enforced by the checker.
5. Annotations are decorative duplicates of printed facts, so a screen reader
   loses nothing by skipping them.

## Theme mechanism

Each chart exists twice with identical geometry and different tokens. The README
selects them with:

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/hero-dark.svg">
  <img src="assets/hero-light.svg" alt="...">
</picture>
```

Because only token values change, the two files have the same byte length and the
same structure; a diff between them is a color edit and nothing else.
