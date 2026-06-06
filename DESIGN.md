# Design

Visual system for the AAOSA observability dashboard. Locked 2026-06-01 after a design-lab exploration (`design-lab/lab-wire-full.html` is the visual source of truth, keep it until the port is done). Register: **product**. Direction name: **wireframe instrument**.

## Theme

Dark, always. Scene: a GenAI engineer reviewing a finished multi-agent run on a dev machine, dense data, focused. A precise control-surface instrument, not a commodity ops dashboard. The signature is a **wireframe scale-field background with a slow diagonal wave** and a **hex-node execution graph** whose live path carries warm ember light.

## Color (OKLCH)

Neutrals are cool graphite (hue ~230-250, very low chroma). The hero is a warm **ember/fire**; the only saturated color that carries meaning. Functional separation holds: ember = active/winning in the graph; chrome never competes with it.

```
--bg-0:     oklch(13% 0.006 250)   /* page ground */
--bg-1:     oklch(17% 0.008 250)   /* panel */
--bg-2:     oklch(21% 0.01 250)    /* raised / track */
--wire:     oklch(46% 0.012 230)   /* hairline borders, idle lattice/edges */
--wire-2:   oklch(62% 0.015 230)   /* idle node stroke, brighter rule */
--crest:    oklch(82% 0.04 70)     /* wave crest, winner label, graph ascent edges */
--fire:     oklch(80% 0.18 52)     /* HERO — graph active/winner, accent, primary data */
--fire-2:   oklch(72% 0.2 38)      /* active edge, bar fill end */
--fire-glow:oklch(80% 0.18 52 / 0.55)
--fire-dim: oklch(80% 0.18 52 / 0.14)
--cool:     oklch(72% 0.09 220)    /* secondary chart series only */
--warn:     oklch(82% 0.13 85)     /* unstable / partial pass */
--fail:     oklch(64% 0.19 22)     /* failure / regression */
--fg-0:     oklch(94% 0.01 230)    /* primary text */
--fg-1:     oklch(72% 0.012 230)   /* secondary */
--fg-2:     oklch(54% 0.012 230)   /* faint / labels */
```

Strategy: **Restrained** chrome (tinted neutrals + ember accent), the graph is the one place ember saturates. `--cool` is reserved strictly for a second chart series; `--warn`/`--fail` are state-only.

## Typography

- **Inter** (system-sans fallback) for chrome: nav, labels, prose, buttons.
- **Mono** (`"SF Mono", "JetBrains Mono", ui-monospace, Consolas`) for **all data**: ids, ELO, latency, tokens, pass rates, axis labels, node labels, table cells. `font-variant-numeric: tabular-nums`.
- Base 15px. Fixed rem scale, no fluid headings. Section heads are mono, uppercase, tracked (`letter-spacing: .16em`), `--fg-2`.

## Surface & shape

- **Sharp geometry** (radius 0–2px). Panels are 1px `--wire` borders over a faintly translucent `--bg-1` (`oklch(15% .007 250 / .6)`) with `backdrop-filter: blur(2px)` and a small **ember corner tick** (`::after` 13px L-bracket top-left).
- **Scale-field background**: fixed lattice of 45deg wireframe diamonds (`--wire`), built in JS as a CSS grid sized to the viewport. A **diagonal wave** sweeps top-left → bottom-right via per-cell `animation-delay = (col+row)/maxd * period`, peaking bright with a crest color + ember glow. A radial **vignette** sits above it to keep the center legible.
- No glassmorphism beyond the subtle panel blur. Ember glow (`drop-shadow` / `box-shadow`) is used only on live/winner elements and never on static chrome.

## Motion

Calm, state-bearing. Easing `cubic-bezier(0.22, 1, 0.36, 1)`.

- **Scale-field wave**: ~4.6s linear loop, the ambient pulse of the surface.
- **Graph live path**: directional **pulse dots** travel the active edges (`<animateMotion>`, ~2.6s,
  staggered) — crest dots climb the ascent legs, ember dots ride the descents; the winner node
  **burns steady** (no blink). Direction is never carried by color alone. Idle edges/nodes are still.
- **Modal**: fade + rise (200-280ms).
- Hover/focus transitions 150-200ms. No marching-ant edges, no node ping, no decorative motion on static data.

## Layout

- Full-page: `main` max-width **1640px**, generous padding.
- **One screen per tab.** The active `.tab-panel` is a flex column at `height: calc(100vh - 184px)`; the dominant visual absorbs the slack:
  - Sessions → the graph grows to fill.
  - Agents → stacked rows; the ELO chart row grows (`flex: 1`).
  - Infra → stat strip (full-width) + a **2×2 chart grid** that stretches to fill.
  - Health → content-dense; flows naturally (`min-height` full) with its case-graph capped (~40vh).

## Components

- **Topbar**: ember diamond mark + `AAOSA` (mono, tracked) + faint `observability`; right-aligned **tab nav** as bordered wire pills, active = ember text + `--wire` border.
- **Stat strip** (`.strip`/`.stat`): replaces all card grids. Column-ruled cells, mono value (~26px), uppercase mono label; key metrics in `--fire`.
- **Hex graph**: bottom-up emergent tree (roots I/O at the bottom, one arch per branch:
  DISPATCH ascent → AGENT apex with tool canopy → EVAL descent; a DIVIDER/AGGREGATOR pair frames
  each level). Delta-45 routing: horizontal bus rails + 45deg chamfers, junction dot = real contact.
  Ascent edges `--crest`, descents `--fire-2`, transients dashed wire. DIAG is a `--warn` diamond
  on the descent; ROSTER GAP a `--fail` dead-end. Camera: cursor-anchored zoom + pan,
  defeatable follow-mode. The `--cool` reserve (charts only) is unchanged.
- **ELO bars**: `--bg-2` track with `--wire` border, `--fire` fill + glow.
- **Charts**: dashed `--wire` gridlines, `series-1` = `--fire` (glow), `series-2` = `--cool`, bars `--fire-2`; mono captions prefixed with an ember `▸`.
- **Case table**: column-ruled rows, mono ids, ember role, active row = `--fire-dim` + inset ember bar; pass rate ember (ok) / warn / faint (none).
- **Modal**: wire card with corner tick, mono title, ember status pill with glow dot.

## Anti-slop guardrails

The wireframe-dark + ember-glow family is one cliché away from "AI tool" slop. Stay precise: monochrome cool lattice, a single warm hero, calm motion, real data density. No neon multi-hue, no purple, no glass cards, no gradient text, no decorative glow.
