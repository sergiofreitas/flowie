# Flowie Overview

The system map the orchestrator reads on startup — what Flowie is, how a target
repo is laid out, and which cookbook to load next.

## What Flowie Is

Flowie builds repeatable **agents plus code** workflows. Deterministic Python
owns sequencing, retries, acceptance, permissions, and observability; agents are
bounded nodes inside that graph. Agent proposes, code disposes.

The package owns `flowie_runtime/` and builtin ADWs. A target repo owns only its
`.flowie/` overlay.

## Target Repo Layout

```text
.flowie/
├── flowie.config.yaml       agent roster, models, prompts, write boundaries
├── prompts/{agent}/         tracked project prompt pairs
├── quality.py               project test/lint/typecheck/build commands
├── adws/                    custom or ejected ADWs only
└── data/                    gitignored runtime
    ├── flowie.db
    └── sessions/{adw_id}/
```

Builtin chains run by name:

```bash
flowie run scout "where is auth handled?"
flowie run plan-build "add a /health endpoint"
flowie run simple-sdlc "add it, test it, review it, document it"
```

Project-specific chains live in `.flowie/adws/` and also run by name:

```bash
flowie make-adw --name review_docs --agents scout,builder
flowie run review_docs "review docs"
```

## The Phase Model

Every ADW run is a sequence of phases, each one `with run.phase(PhaseParams(...))`:

- **engineer** — records the incoming ask.
- **agent** — `ph.call(AgentCall(...))`: prompt in, typed envelope out, gates verified.
- **code** — deterministic work such as tests, quality commands, git commit, diff capture.

Success must be earned: every phase defaults to `fail`; clean exit flips it to
success. Agent phases additionally require parsed envelopes and green gates.

## Where To Go Next

Load one cookbook per request.

| Request | Cookbook |
|---|---|
| Turn a request into the prompt an ADW gets | `how_to_prompt_for_the_eng.md` |
| Set the system up in a repo | `install.md` |
| Write a custom ADW | `create_adw.md` |
| Change an existing custom ADW | `update_adw.md` |
| Create or replace the config | `create_config.md` |
| Add or retune an agent | `update_config.md` |
| Edit deterministic project checks | `update_modules.md` |
| Run and monitor a workflow | `how_to_prompt_for_the_eng.md`, then `run_adw.md` |
