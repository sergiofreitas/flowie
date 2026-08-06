# Install

`flowie install` — stamp the entire factory out of the skill and into the current working directory.

## Run it

```bash
uv run .codex/skills/flowie/scripts/install.py
```

Run from the **target repo root** — the cwd is where everything lands. If the skill lives in your user scope, the path is `~/.codex/skills/flowie/scripts/install.py`.

## What gets stamped

`install.py` copies `templates/` into the cwd:

| Stamped | From | Tracked? |
|---|---|---|
| `adws/flowie_config/flowie.config.yaml` | `templates/flowie.config.yaml` | yes — the agent roster |
| `.env.sample` | `templates/env.sample` | yes |
| `adws/adw_*.py` | `templates/adws/` | yes — the twelve starter ADWs |
| `adws/adw_modules/` | `templates/adws/adw_modules/` | yes — all low-level logic |
| `adws/adw_data/prompt_engineering/{planner,builder,scout,reviewer,documenter}/` | `templates/prompt_engineering/` | yes — **the user-owned home for prompts** |
| `adws/adw_data/harness_engineering/` | `templates/harness_engineering/` | yes — legacy Pi extension examples; ignored by Codex mode |
| `justfile` | `templates/justfile` | yes — starter recipes: `just demo`, the workflows, the trace reads, `just obs` |
| `adws/adw_data/sessions/`, `adws/adw_data/flowie.db` | created at runtime | no — gitignored |

`prompt_engineering` is what an agent is told. `harness_engineering` remains in the tree for upstream compatibility, but `coding_agent: codex` does not load Pi extensions.

## Idempotency

Re-running is safe. `install.py` skips **every** file that already exists — your config, your prompts, and previously stamped code alike — and reports what it skipped, so a second run doubles as a drift check. To refresh stamped code (`adw_modules/`, the starter `adw_*.py`) to the skill's current version, run with `--force` — but know that `--force` overwrites ALL existing stamped files, including `flowie.config.yaml` and `prompt_engineering/`, so commit or back up user-owned edits first.

## Post-install checklist

1. **Codex CLI** — `codex --version` must work from the target repo.
2. **Model** — `flowie.config.yaml` defaults to `gpt-5.5`; change `defaults.model` if your Codex config should use another model.
3. **Gitignore** — `install.py` appends `adws/adw_data/sessions/`, `adws/adw_data/flowie.db*`, and `.env` for you; confirm they landed. All three are runtime or secrets and must never be committed.
4. **Git repo** — ADWs that end in a commit phase call `git_helper.commit_all`, which raises if the cwd is not a git repository. Run `git init` and make a first commit before using `adw_plan_build.py`, `adw_plan_build_test.py`, or `adw_simple_sdlc.py`. `adw_document.py` needs one too: it measures the change with `git diff` against a base ref (`main` by default, `--base` to override).
5. **Smoke test** — `just demo` runs two cheap read-only workflows back to back, or run the smallest ADW directly:

```bash
just demo                                                    # both, end to end
uv run adws/adw_prompt.py "reply with a one-line summary of this repo"   # the raw form
```

Green means the whole path works: config validated, session minted, Codex ran, envelope parsed, events landed in `adws/adw_data/flowie.db`. Verify the trace exists before trusting anything larger:

```bash
sqlite3 adws/adw_data/flowie.db "select adw_id, status from sessions order by started_at desc limit 1;"
```

If the smoke test fails, fix it before composing chains — every multi-agent ADW rides on this exact path.
