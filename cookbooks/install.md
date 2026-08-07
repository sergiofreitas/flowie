# Install

`flowie init` creates the project-owned overlay. The package keeps the runtime
and builtin ADWs; the target repo owns config, prompts, custom ADWs, quality
commands, and runtime data.

## Run It

From the target repo root:

```bash
flowie init
```

From a source checkout or installed skill:

```bash
uv run ~/.codex/skills/flowie/scripts/flowie.py init
```

## What Gets Created

| Path | Purpose | Tracked? |
|---|---|---|
| `.flowie/flowie.config.yaml` | project agent roster, models, prompts, writes | yes |
| `.flowie/prompts/{planner,builder,scout,reviewer,documenter}/` | project-owned prompt pairs | yes |
| `.flowie/quality.py` | project-specific test/lint/typecheck/build commands | yes |
| `.flowie/adws/` | custom or ejected ADWs only | yes |
| `.flowie/data/flowie.db` | initialized SQLite trace db | no — under `.flowie/data/` |
| `.flowie/data/sessions/` | raw run records | no — under `.flowie/data/` |
| `justfile` | optional recipes that call `flowie ...`; created only with `flowie init --with-justfile` | yes |
| `.env.sample` | environment template | yes |

The installer appends `.flowie/data/`, `.env`, `__pycache__/`, and `*.pyc` to
`.gitignore`.

## Builtin vs Custom

Run package-owned ADWs by name:

```bash
flowie run scout "where is auth handled?"
flowie run plan-build "add a /health endpoint"
flowie run simple-sdlc "add it, test it, review it, document it"
```

Create a project-owned ADW only when the chain differs:

```bash
flowie make-adw --name review_docs --agents scout,builder
flowie run review_docs "review the docs flow"
```

Or eject a builtin:

```bash
flowie eject adw plan-build
```

## Post-Install Checklist

1. `codex --version` works from the target repo.
2. `.flowie/flowie.config.yaml` names a model your Codex CLI accepts.
3. `.flowie/quality.py` has real commands before you rely on test/quality ADWs.
4. The repo is a Git repo before running commit/document flows.
5. `flowie run scout "reply with a one-line summary of this repo"` produces a row in `.flowie/data/flowie.db`.
