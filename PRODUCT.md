# Product

## Register

product

## Users

Quentin, GenAI engineer building AAOSA. Uses the dashboard solo on a dev machine to step through multi-agent execution traces: which agents claimed each task, why, what the ELO deltas were, whether QA passed or failed. Context: post-run review, not live monitoring. One user, high technical fluency, no tolerance for decorative noise.

## Product Purpose

Observability dashboard for the AAOSA multi-agent runtime. Replaces scattered print_timeline output with a visual, navigable record of each run: graph of agent claims, scrubber through task steps, modal overlays per node type. Success = Quentin can debug a run in two minutes without reading raw JSONL.

## Brand Personality

Precise. Technical. Unsentimental.

## Anti-references

- Grafana / Datadog default blue dashboards (commodity ops tooling aesthetic)
- Emerald-on-black SaaS dashboards (the emerald is already claimed by graph active state; chrome must not compete)
- Any "AI tool" purple-gradient-with-glassmorphism aesthetic
- Verbose SaaS onboarding chrome (zero marketing surface here)

## Design Principles

1. **The graph speaks first.** Every chrome decision defers to graph legibility. If the nav competes with active edges, the nav loses.
2. **Functional color separation.** Emerald = active/winning in the graph. Anything else in the UI must use a distinct hue — never reuse emerald for interactive states.
3. **Density is a feature.** This is a data tool. Tables, labels, metrics at reading density. No card-grid sprawl.
4. **Precision typography.** Monospace for data fields (ELO, latency, tokens). System sans for labels and nav. No display fonts.
5. **Zero decoration.** No gradients, no shadows for depth illusion, no hover animations on static data. Motion is reserved for state changes (modal open/close).

## Accessibility & Inclusion

WCAG AA contrast minimum. Single user, no specific accommodations required.
