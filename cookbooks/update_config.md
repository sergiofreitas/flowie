# Update Config

Add or retune agents in `flowie.config.yaml`.

## Retune model or thinking

Edit the agent's entry in place:

```yaml
  - name: builder
    model: gpt-5.5
    thinking: high                   # was medium
```

Use a model id accepted by your local Codex CLI. See `references/config.md`.

`thinking` is retained as roster metadata in this Codex port; the current adapter does not map it to a separate `codex exec` flag.

**A model change means a fresh session.** `agent_map.json` records the model each coding-agent session was created with. When a joined run (`--adw-id`) finds the config's model no longer matches the recorded one, that agent starts a **new** session rather than resuming — the map is updated, never a bad resume. Thinking changes do not invalidate a session; model changes do. Expect the agent to lose its accumulated context window on the first run after the change.

## Recolor an agent's lane

```yaml
  - name: builder
    color: "#22d3ee"      # hex; the starter roster ships violet/cyan/amber/green
```

Purely cosmetic and safe to change mid-project: the color rides the `agent_start` event and the `agent_sessions` row, so the visualizer picks it up on the next run without touching past sessions. Omit the key to let the UI's fallback palette choose.

## Retune tools

In Codex mode, `tools` is intent metadata. Codex receives its normal tool surface; `writes` and `protected_files` are the enforced safety boundary after each call.

Set the roster-wide floor in `defaults`, then narrow per agent:

```yaml
defaults:
  tools: [read, bash, edit, write, grep, find, ls]

agents:
  - name: reviewer
    tools:                # explicit list wins over defaults
      - read
      - grep
      - find
      - ls
      - bash
      - write
```

**Resolution:** the agent's own list wins → else it inherits `defaults.tools` → else `None`. In Codex mode this affects trace/config intent, not CLI tool availability.

Narrow by role, not by reflex:

- Withhold `edit`/`write` only where the restriction *is* the guarantee. The reviewer's contract is "change nothing", so withholding `edit` makes that structural instead of merely prompted.
- Recon agents should get the full read/search/list intent surface (`read`, `grep`, `find`, `ls`).

## Add harness extensions

```yaml
    harness_engineering:
      - .pi/extensions/json_guard.ts    # a pi extension FILE PATH
```

`harness_engineering` is ignored by `coding_agent: codex`. It remains for legacy upstream Pi rosters only.

## Add a new agent

Three steps, all required — skipping any one fails `agents.validate()` at ADW startup, before anything spawns:

1. **Prompts.** Create `.flowie/prompts/{name}/system.md` (Purpose + Instructions — the agent's static identity, nothing else) and `user.md` (an h3 per incoming datum: `{{prompt}}`, `{{previous_envelope}}`, `{{context_handoff_dir}}`, then the task, then a `## Report` section showing the exact output JSON). Copy an existing pair as the shape.
2. **Config entry.** Name, purpose, prompt refs, plus anything that differs from `defaults`.
3. **An output type.** Every agent call parses against a concrete Pydantic model in `flowie_runtime/data_types.py`. If none of `PlanOutput`, `BuildOutput`, `ScoutOutput`, `ReviewOutput`, `DocumentOutput` fits the new agent's report, add one — see `update_modules.md`. The user prompt's `Report` section must show exactly that JSON shape.

Then name the agent in an ADW's `REQUIRED_AGENTS` and call it.

## Rules that do not bend

- ADW scripts name **agents**, never models. Swapping a model is a config edit and touches no Python.
- One agent, one prompt, one purpose. If an entry needs two purposes, it is two agents.
- Output types never appear in config — they live at the call site, paired with the user prompt.

Full spec: `references/config.md`.
