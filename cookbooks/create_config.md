# Create Config

Generate `flowie.config.yaml` — the agent roster for a target repo.

## Generate it

```bash
uv run .codex/skills/flowie/scripts/make_config.py
```

Writes `.flowie/flowie.config.yaml` — creating the directory if needed — with the starter agents (planner, builder, scout, reviewer, documenter) wired to the prompt files `flowie init` stamped into `.flowie/prompts/`. That path is the default every ADW and the justfile look for; `--config` overrides it. `make_config.py` refuses to overwrite an existing config unless you pass `--force`, so retuning an existing roster is a hand edit — see `update_config.md`.

## The rule

**One agent, one prompt, one purpose.** An entry defines who an agent *is*: its coding agent, model, thinking level, and exactly one system prompt plus one user prompt. How it gets *used* — the output type, a per-call user prompt override — lives at the ADW call site, never here.

## Schema

```yaml
defaults:
  coding_agent: codex
  model: gpt-5.5
  thinking: medium                 # retained as metadata for phase traces
  harness_engineering: []          # ignored by coding_agent: codex
  data_dir: .flowie/data          # runtime home: {data_dir}/sessions/{adw_id}/{agent_name}/

observability:
  db: .flowie/data/flowie.db        # tracer writes here; the UI polls it
  poll_ms: 500                     # visualizer live-poll cadence

agents:
  - name: planner                  # ADW scripts name agents, never models
    coding_agent: codex
    model: gpt-5.5
    thinking: high
    color: "#a78bfa"               # optional hex — this agent's lane color in the visualizer
    purpose: Turn a request into a plan the builder can implement without asking questions.
    prompt_engineering:
      system: .flowie/prompts/planner/system.md
      user: .flowie/prompts/planner/user.md

  - name: scout
    thinking: high                 # unset keys fall through to defaults
    purpose: Find and report where things live; change nothing.
    prompt_engineering:
      system: .flowie/prompts/scout/system.md
      user: .flowie/prompts/scout/user.md
    tools:                         # optional allowlist — omit the key entirely for all tools
      - read
      - bash
```

Every agent entry merges over `defaults`, so an entry only states what differs. In Codex mode, `tools` is intent metadata; repository write boundaries are enforced after the call by `writes` and `protected_files`.

## After generating

1. Each agent needs its prompt pair to exist on disk: `.flowie/prompts/{name}/system.md` and `user.md`. `agents.validate()` fails the run at startup if either is missing.
2. Write `purpose` as one sentence and make the system prompt say the same thing — the two should not drift.
3. Validate by running the smallest ADW that names your agents; a bad entry fails fast, before anything spawns.

Full field-by-field spec, thinking-level mapping, and model resolution: `references/config.md`. Retuning an existing roster: `update_config.md`.
