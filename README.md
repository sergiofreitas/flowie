# Flowie

Flowie is a Codex skill for running repeatable **agents plus code** workflows.
It ports the Super Simple Software Factory pattern to Codex: deterministic Python
workflow scripts own sequencing, retries, validation, and observability, while
Codex agents do bounded planning, building, reviewing, scouting, and documenting
inside those workflows.

The main unit is an **ADW**: an Agent Developer Workflow. An ADW is a Python
script that runs phases such as `plan -> build -> test -> review -> document`,
captures typed JSON envelopes between agents, enforces write boundaries, and
streams events into SQLite for terminal queries or the web visualizer.

## What It Gives You

- A Codex skill named `flowie`.
- Builtin ADWs for scout, plan, build, test, review, document, and composed SDLC flows.
- A project-local `.flowie/` overlay for config, prompts, custom ADWs, quality commands, and runtime data.
- SQLite observability in `.flowie/data/flowie.db`.
- A Bun/Vite visualizer for inspecting sessions, phases, events, gates, prompts, and envelopes.

## Requirements

For using the skill:

```bash
codex --version
uv --version
```

Recommended for daily operation:

```bash
just --version
sqlite3 --version
```

For the web visualizer:

```bash
bun --version
```

Flowie defaults to `model: gpt-5.5` in stamped configs. Change
`.flowie/flowie.config.yaml` if your Codex setup should use another
model.

## Install The Skill

Clone this repository and copy it into Codex's skills directory:

```bash
git clone <your-flowie-repo-url> flowie
mkdir -p ~/.codex/skills
cp -R flowie ~/.codex/skills/flowie
```

Restart Codex so the new skill appears as `$flowie`.

## Install Flowie Into A Target Repo

From the repository where you want to use Flowie:

```bash
uv run ~/.codex/skills/flowie/scripts/flowie.py init
```

This creates only the project-owned overlay:

```text
.flowie/
├── flowie.config.yaml
├── prompts/
├── quality.py
├── adws/
└── data/
    └── flowie.db
justfile
.env.sample
```

The runtime and builtin ADWs stay in the Flowie package. Runtime data should
stay uncommitted:

```text
.flowie/data/
.env
```

The installer appends these to `.gitignore`.

## First Run

In the target repo:

```bash
just demo
```

Without `just`, run the smallest ADW directly:

```bash
uv run ~/.codex/skills/flowie/scripts/flowie.py run prompt --agent scout "reply with a one-line summary of this repo"
```

Check the latest runs:

```bash
just sessions
```

Or query SQLite directly:

```bash
sqlite3 .flowie/data/flowie.db \
  "select adw_id, status, request from sessions order by started_at desc limit 5;"
```

## Daily Use

Use the `justfile` recipes stamped into your repo:

```bash
just scout "where is authentication handled?"
just plan "add a /health endpoint"
just plan-build "add a /health endpoint"
just sdlc "add a /health endpoint and cover it with tests"
just simple-sdlc "implement the requested feature, test it, review it, and document it"
```

Each workflow prints an `adw_id`. Use it to inspect the run:

```bash
just phases <adw_id>
just tail <adw_id>
just procs <adw_id>
```

You can resume or chain work under the same ADW session:

```bash
flowie run plan "plan the migration" --adw-id a1b2c3d4
flowie run build "implement the approved plan" --adw-id a1b2c3d4
```

## Agent Roster

The default roster lives at:

```text
.flowie/flowie.config.yaml
```

It defines:

- which agents exist (`planner`, `builder`, `scout`, `reviewer`, `documenter`);
- which model each agent uses;
- which prompt files each agent reads;
- which paths each agent may modify through `writes`;
- which paths are protected globally.

For alternate rosters, create another config and pass it explicitly:

```bash
flowie run plan-build "..." --config .flowie/flowie.frontier.config.yaml
```

With `just`:

```bash
FLOWIE_CONFIG=.flowie/flowie.frontier.config.yaml just sdlc "..."
```

## Custom ADWs

Builtin ADWs are addressed by name:

```bash
flowie run scout "where is auth handled?"
flowie run simple-sdlc "add a /health endpoint"
```

Create a project-owned ADW when the chain itself needs to differ:

```bash
flowie make-adw --name review_docs --agents scout,builder
flowie run review_docs "review the docs flow"
```

Or eject a builtin and edit the copy:

```bash
flowie eject adw plan-build
```

## Web Visualizer

Install Bun if needed, then in a target repo with a `flowie.db`:

```bash
just obs
```

The UI runs at:

```text
http://localhost:4601
```

The API defaults to:

```text
http://localhost:4600
```

You can also run the visualizer manually from this repository:

```bash
cd apps/visualizer
bun install
FLOWIE_DB=/path/to/target/repo/.flowie/data/flowie.db PORT=4600 bun run server/index.ts
PORT=4600 bun run dev --host 127.0.0.1
```

## Using It From Codex

Once installed as a skill, ask Codex to use it:

```text
Use $flowie to install Flowie in this repo.
```

Then, in day-to-day work:

```text
Use $flowie to run the SDLC workflow for adding a /health endpoint.
```

The skill tells Codex to run and observe the ADW instead of doing the ADW work
itself. That keeps the workflow traceable: phases, prompts, envelopes, gates,
tool calls, and failures all land in `flowie.db`.

## Development

Validate the skill structure:

```bash
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
```

Compile Python scripts/templates:

```bash
python3 -B -m py_compile scripts/*.py flowie_runtime/*.py flowie_runtime/builtins/*.py templates/quality.py
```

Run the smoke tests:

```bash
python3 -m unittest tests.smoke
```

## License

MIT. This port preserves the upstream license from the original
`disler/super-simple-software-factory` project.
