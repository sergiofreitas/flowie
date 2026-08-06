#!/usr/bin/env -S uv run
# /// script
# dependencies = []
# ///
"""/install — stamp the Flowie factory from the skill into the cwd. Idempotent.

Usage:
    uv run <skill>/scripts/install.py [--force]

Stamps: adws/ (modules + starter ADWs), adws/adw_data/prompt_engineering/
(starter agents), adws/flowie_config/flowie.config.yaml, .env.sample,
.gitignore entries.
Existing files are skipped unless --force.
"""

import argparse
import ast
import sqlite3
import shutil
import sys
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"

GITIGNORE_ENTRIES = [
    "adws/adw_data/sessions/",
    "adws/adw_data/flowie.db*",
    ".env",
    # The ADWs are Python, so importing adw_modules writes bytecode next to it.
    # Chains that end in a commit phase call `git add -A`, so without this a
    # stamped repo commits its own .pyc files — 15 of them showed up in the
    # first repo that was ever installed into from scratch.
    "__pycache__/",
    "*.pyc",
]


def tracer_schema() -> tuple[str, list[tuple[str, str, str]]]:
    """Read the shipped tracer schema without importing target dependencies."""
    tracer = TEMPLATES / "adws" / "adw_modules" / "tracer.py"
    module = ast.parse(tracer.read_text(), filename=str(tracer))
    schema = None
    migrations = []
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        if "SCHEMA" in names:
            schema = ast.literal_eval(node.value)
        if "MIGRATIONS" in names:
            migrations = ast.literal_eval(node.value)
    if schema is None:
        raise RuntimeError(f"SCHEMA not found in {tracer}")
    return schema, migrations


def ensure_db(root: Path, stamped: list) -> None:
    db_path = root / "adws" / "adw_data" / "flowie.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema, migrations = tracer_schema()
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.executescript(schema)
        for table, column, decl in migrations:
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            if column not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    finally:
        conn.close()
    stamped.append(f"{db_path} (initialized/migrated)")


def stamp(src: Path, dest: Path, force: bool, stamped: list, skipped: list) -> None:
    if src.is_dir():
        for child in sorted(src.iterdir()):
            if child.name == "__pycache__":
                continue
            stamp(child, dest / child.name, force, stamped, skipped)
        return
    if dest.exists() and not force:
        skipped.append(str(dest))
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    stamped.append(str(dest))


def ensure_gitignore(root: Path, stamped: list) -> None:
    gitignore = root / ".gitignore"
    existing = gitignore.read_text().splitlines() if gitignore.exists() else []
    missing = [e for e in GITIGNORE_ENTRIES if e not in existing]
    if missing:
        with gitignore.open("a") as f:
            f.write("\n# flowie runtime\n" + "\n".join(missing) + "\n")
        stamped.append(f"{gitignore} (+{len(missing)} entries)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    args = parser.parse_args()

    root = Path.cwd()
    stamped, skipped = [], []

    stamp(TEMPLATES / "adws", root / "adws", args.force, stamped, skipped)
    stamp(TEMPLATES / "prompt_engineering",
          root / "adws" / "adw_data" / "prompt_engineering", args.force, stamped, skipped)
    stamp(TEMPLATES / "harness_engineering",
          root / "adws" / "adw_data" / "harness_engineering", args.force, stamped, skipped)
    stamp(TEMPLATES / "flowie.config.yaml",
          root / "adws" / "flowie_config" / "flowie.config.yaml",
          args.force, stamped, skipped)
    stamp(TEMPLATES / "env.sample", root / ".env.sample", args.force, stamped, skipped)
    # The recipes are part of the operating experience, and several cookbooks
    # plus the run banner tell you to use them, so a stamped repo has to have
    # them. Skipped like any other file if the repo already has a justfile.
    stamp(TEMPLATES / "justfile", root / "justfile", args.force, stamped, skipped)
    ensure_db(root, stamped)
    ensure_gitignore(root, stamped)

    print(f"flowie installed into {root}")
    print(f"  stamped/ensured: {len(stamped)} file(s)")
    for s in stamped:
        print(f"    + {s}")
    if skipped:
        print(f"  skipped (already exist, use --force to overwrite): {len(skipped)}")
    print("\nnext steps:")
    print("  1. codex --version       # confirm the Codex CLI is available")
    print("  2. just demo             # two cheap read-only runs, end to end")
    print("  3. just sessions         # what just happened")
    print("  4. just obs              # the trace UI, needs bun")
    print("\n  no just? the raw form of step 2 is:")
    print("     uv run adws/adw_prompt.py \"say hello\" --agent scout")
    return 0


if __name__ == "__main__":
    sys.exit(main())
