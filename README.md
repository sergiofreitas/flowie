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
- Starter ADWs for scout, plan, build, test, review, document, and composed SDLC flows.
- A project-local `flowie.config.yaml` roster for agents, models, prompts, and write boundaries.
- SQLite observability in `adws/adw_data/flowie.db`.
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
`adws/flowie_config/flowie.config.yaml` if your Codex setup should use another
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
uv run ~/.codex/skills/flowie/scripts/install.py
```

This stamps the workflow runtime into the target repo:

```text
adws/
├── flowie_config/flowie.config.yaml
├── adw_*.py
├── adw_modules/
└── adw_data/
    ├── flowie.db
    └── prompt_engineering/
justfile
.env.sample
```

The installer initializes the SQLite trace db so the read recipes and visualizer
have a schema immediately. Runtime files should stay uncommitted:

```text
adws/adw_data/sessions/
adws/adw_data/flowie.db*
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
uv run adws/adw_prompt.py --agent scout "reply with a one-line summary of this repo"
```

Check the latest runs:

```bash
just sessions
```

Or query SQLite directly:

```bash
sqlite3 adws/adw_data/flowie.db \
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
uv run adws/adw_plan.py "plan the migration" --adw-id a1b2c3d4
uv run adws/adw_build.py "implement the approved plan" --adw-id a1b2c3d4
```

## Agent Roster

The default roster lives at:

```text
adws/flowie_config/flowie.config.yaml
```

It defines:

- which agents exist (`planner`, `builder`, `scout`, `reviewer`, `documenter`);
- which model each agent uses;
- which prompt files each agent reads;
- which paths each agent may modify through `writes`;
- which paths are protected globally.

For alternate rosters, create another config and pass it explicitly:

```bash
uv run adws/adw_plan_build.py "..." --config adws/flowie_config/flowie.frontier.config.yaml
```

With `just`:

```bash
FLOWIE_CONFIG=adws/flowie_config/flowie.frontier.config.yaml just sdlc "..."
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

If you are running from a local checkout instead of an installed skill, point
the justfile at it:

```bash
FLOWIE_SKILL_DIR=/path/to/flowie just obs
```

You can also run the visualizer manually from this repository:

```bash
cd apps/visualizer
bun install
FLOWIE_DB=/path/to/target/repo/adws/adw_data/flowie.db PORT=4600 bun run server/index.ts
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
python3 -B -m py_compile scripts/*.py templates/adws/*.py templates/adws/adw_modules/*.py
```

Smoke-test the installer:

```bash
tmp="$(mktemp -d)"
(cd "$tmp" && python3 /absolute/path/to/flowie/scripts/install.py)
```

## License

MIT. This port preserves the upstream license from the original
`disler/super-simple-software-factory` project.
