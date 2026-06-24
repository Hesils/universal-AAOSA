# universal-AAOSA

[![CI](https://github.com/Hesils/universal-AAOSA/actions/workflows/ci.yml/badge.svg)](https://github.com/Hesils/universal-AAOSA/actions/workflows/ci.yml)
&nbsp;·&nbsp; **1200+** tests &nbsp;·&nbsp; Python 3.14

> A multi-agent runtime where the execution graph is **not** planned in advance — it **emerges** from distributed claiming decisions. No central orchestrator routes tasks: each agent locally decides whether to claim a task, competing with the others. Coordination is bottom-up. Domain-agnostic.

## Why

Classic multi-agent systems lean on a central orchestrator: one component receives the task, decides which agent handles it, routes sub-tasks, recombines results. That orchestrator is a single point of failure, a coupling bottleneck, and a ceiling on autonomy — the system can only handle the paths it was wired for.

universal-AAOSA inverts the load. The execution graph is discovered at runtime, from the agents' own claiming decisions. Adding, removing, or specializing an agent never touches a router, because there isn't one.

## Architecture

```
src/aaosa/
├── schemas/    task · claim · output · elo
├── core/       agent.py (claim + execute, tool-use loop) · tool.py
├── claiming/   scoring · phase1 (deterministic, no LLM) · phase2 (cognitive, LLM) · dispatch
├── config/     loader.py (load_agents from YAML)
├── cli/        app.py (Typer: run · campaign · report · dashboard · health-check)
├── runtime/    llm_client · runner (run_task / run_chain / run_divided_task) · divider · aggregator
├── tracing/    events · tracer · analysis · formatter · store
├── elo/        formula · updater · persistence
└── qa/         protocol · rule_based · health_check · judge · spec_evaluator · triage

dashboard/      Flask observability app — claim graph, step scrubber, REST API
tests/          mirrors src/aaosa/ — 1200+ tests
runs/           unified run store (gitignored) · runs_demo/ = curated demo exhibits (versioned)
```

Two coordination phases stay strictly separated: **Phase 1** filters candidates deterministically (no LLM); **Phase 2** is the cognitive claim (LLM), and an agent never sees its own system fit score. The graph emerges — a sub-task with an unknown tag goes *unassigned*, which is a signal of a roster gap, not a bug.

## Quickstart

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Hesils/universal-AAOSA.git
cd universal-AAOSA
uv sync
echo "OPENAI_API_KEY=sk-..." > .env   # `aaosa run` calls a real LLM
uv run aaosa run
```

`aaosa run` executes the built-in demo end-to-end: a task enters, agents compete to claim it, one wins and executes it, the result is evaluated, and ELO updates immediately.

| Command | What it does |
|---|---|
| `aaosa run [--scenario main\|roster_gap]` | single task, claim → execute → evaluate |
| `aaosa solve --roster <dir> --task "..."` | free-form task on injected roster(s) → session + manifest + trace (the entry point called from AIOS) |
| `aaosa campaign --n N --runs-root <dir>` | batch of N runs into a fresh store |
| `aaosa report [--runs-root <dir>]` | offline run summary (no API key needed) |
| `aaosa dashboard [--port 5001]` | observability UI (`http://127.0.0.1:5001`) |
| `aaosa health-check` | replay known cases, measure success rates |

## Contributing

`master` is protected: every change lands through a pull request, and CI must pass before merge (no approval required — solo project).

- **Branch naming**: `feat/<ticket>-<slug>`, `fix/<slug>`, `docs/<slug>`, `chore/<slug>`.
- **Flow**: branch → push → open PR → CI green → **squash-merge** → delete branch.
- **Versioning**: semver; a `v{version}` tag is pushed automatically by CI on `master` when `pyproject.toml` is bumped.

## Documentation

- **[Technical documentation](docs/documentation-technique.md)** — the full narrative: the problem with central orchestration, the claiming mechanism, execution, self-correction through ELO, and observability. _(In French.)_
- Roadmap and known follow-ups: [`docs/backlog/`](docs/backlog/).

## Stack

Python 3.14 · uv · Pydantic 2 · OpenAI SDK · Typer · pytest. CI runs the full test suite on every push and pull request.
