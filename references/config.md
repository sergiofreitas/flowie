# Config Reference

The full `flowie.config.yaml` spec: every field, how defaults merge, and how model / tools / write boundaries map onto the selected coding agent.

It lives at `.flowie/flowie.config.yaml`. Every `adw_*.py` uses that path by default; pass `--config <path>` to run a different roster.

## Shape

```yaml
defaults:
  coding_agent: codex
  model: gpt-5.5
  thinking: medium
  harness_engineering: []
  tools: [read, bash, edit, write, grep, find, ls]
  protected_files: [.flowie/flowie.config.yaml, .flowie/adws/, .flowie/quality.py]
  data_dir: .flowie/data

observability:
  db: .flowie/data/flowie.db
  poll_ms: 500

agents:
  - name: planner
    purpose: Turn a request into a plan the builder can implement without asking questions.
    prompt_engineering:
      system: .flowie/prompts/planner/system.md
      user: .flowie/prompts/planner/user.md
    writes: [specs/]
```

## Fields

| Field | Meaning |
|---|---|
| `coding_agent` | `codex` by default. Legacy `pi` remains available if the upstream Pi CLI is installed. `claude_code` is still a stub. |
| `model` | Passed to `codex exec --model`. Use whatever model id your Codex CLI accepts. |
| `thinking` | Retained as roster metadata and shown in traces. The current Codex adapter does not map it to a separate CLI flag. |
| `harness_engineering` | Legacy upstream field. Ignored by `coding_agent: codex`; only used by the legacy Pi adapter. |
| `tools` | Intent metadata in Codex mode. Codex receives its normal tool surface; safety is enforced by `writes` and `protected_files` after the call. |
| `protected_files` | Paths no agent may modify unless it explicitly names them in its own `writes`. Default protects the factory machinery. |
| `data_dir` | Runtime home. Sessions land at `{data_dir}/sessions/{adw_id}/{agent_name}/`. |
| `observability.db` | SQLite trace db. `tracer.py` writes directly; `flowie obs`, `flowie sessions`, and the optional visualizer read it. |
| `prompt_engineering.system` / `user` | Required prompt files. `agents.validate()` fails before spawning Codex if either path is missing. |
| `writes` | Enforced repo write boundary. Omitted = unrestricted except protected files. `[]` = read-only with respect to the repo. A list = only those paths. |

Config defines who an agent is. The ADW call site defines how that agent is used: output type, phase name, gates, and task prompt.

## Defaults Merging

`agents.py` merges each agent entry over `defaults`, key by key. An agent only states what differs. `agents.validate(cfg, REQUIRED_AGENTS)` confirms every required agent exists, has supported `coding_agent`, and has both prompt files.

## Codex Runtime

The Codex adapter runs:

```bash
codex exec --json --model <model> --output-schema <schema> --output-last-message <file> --cd <repo> --sandbox workspace-write -
```

Corrections use `codex exec resume <session_id>` when Codex exposes a resumable session id in its JSONL stream. If the CLI version does not expose one, the run still records raw output and parsed envelopes, but a correction may start from a fresh Codex context.

`--output-schema` is generated from the Pydantic envelope type declared at the ADW call site. Keep the synced triad together whenever an output changes:

1. The `EnvelopeBase` subclass in `flowie_runtime/data_types.py`.
2. The `## Report` JSON example in the relevant `user.md`.
3. Every call site passing `output_type=`.

## Write Permissions

`tools` cannot express a safety boundary: shell access can edit anything. Flowie enforces write permissions after each agent call by comparing the working tree before and after the agent ran.

A breach:

1. rolls back unauthorized changes the agent introduced;
2. preserves paths that were already dirty before the agent ran;
3. fails the phase and records the path list in the trace.

Examples:

```yaml
agents:
  - name: builder      # no `writes` key -> unrestricted, minus protected_files
  - name: scout
    writes: []         # no repo writes; findings still land in context_handoff/
  - name: planner
    writes: [specs/]
  - name: documenter
    writes: [app_docs/, docs/, "**/*.md", "*.md"]
```

The session runtime under `data_dir` is always writable. That is where prompts, raw JSONL, `envelope.json`, and `context_handoff/` live.
