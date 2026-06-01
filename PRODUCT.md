# Product

## Register

product

## Users

Quentin, GenAI engineer building AAOSA. Uses the dashboard solo on a dev machine to step through multi-agent execution traces: which agents claimed each task, why, what the ELO deltas were, whether QA passed or failed. Context: post-run review, not live monitoring. One user, high technical fluency, no tolerance for decorative noise.

## Product Purpose

Observability dashboard for the AAOSA multi-agent runtime. Replaces scattered print_timeline output with a visual, navigable record of each run: graph of agent claims, scrubber through task steps, modal overlays per node type. Success = Quentin can debug a run in two minutes without reading raw JSONL.

## Brand Personality

Precise. Technical. Unsentimental.

## Locked visual direction

**Wireframe instrument** (dark). Full system in `DESIGN.md`: cool graphite neutrals, a single warm **ember/fire** hero, a wireframe scale-field background with a slow diagonal wave, and a hex-node execution graph (tree-tiered: agents=leaves, logic=trunk, I/O=roots) whose live path carries ember pulses.

## Anti-references

- Grafana / Datadog default blue dashboards (commodity ops tooling aesthetic)
- "AI tool" neon-on-black / purple-gradient / glassmorphism slop (the wireframe-dark + glow family is one cliché away from this; stay monochrome-cool + single warm hero)
- Card-grid sprawl (use the stat strip)
- Verbose SaaS onboarding chrome (zero marketing surface here)

## Design Principles

1. **The graph speaks first.** Every chrome decision defers to graph legibility. If the nav competes with the live path, the nav loses.
2. **Functional color separation.** Ember (`--fire`) = active/winning in the graph. Chrome accents and state colors (`--cool`, `--warn`, `--fail`) stay distinct — never reuse ember as decoration.
3. **Density is a feature.** This is a data tool. Tables, labels, metrics at reading density. No card-grid sprawl; metrics live in the stat strip.
4. **Precision typography.** Monospace for all data (ELO, latency, tokens, ids, axis/node labels). Inter/system sans for labels and nav. No display fonts.
5. **Motion conveys state.** The ambient scale-field wave and the active-path ember pulses are the signature; the winner burns steady. No marching-ant edges, no node ping, no decorative motion on static data. Glow only on live/winner elements. Transitions 150-250ms.

## Accessibility & Inclusion

WCAG AA contrast minimum. Single user, no specific accommodations required.
