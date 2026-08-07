"""Flowie command line interface."""

from __future__ import annotations

import argparse
import ast
import importlib.metadata
import runpy
import shutil
import sqlite3
import sys
from pathlib import Path


TEMPLATES = Path(__file__).resolve().parent / "templates"
PROJECT_DIR = ".flowie"
DEFAULT_CONFIG = ".flowie/flowie.config.yaml"
BUILTINS = {
    "build": "adw_build",
    "build-review": "adw_build_review",
    "build-test": "adw_build_test",
    "document": "adw_document",
    "plan": "adw_plan",
    "plan-build": "adw_plan_build",
    "plan-build-test": "adw_plan_build_test",
    "plan-build-test-quality": "adw_plan_build_test_quality",
    "prompt": "adw_prompt",
    "quality": "adw_quality",
    "scout": "adw_scout",
    "simple-sdlc": "adw_simple_sdlc",
}

GITIGNORE_ENTRIES = [
    ".flowie/data/",
    ".env",
    "__pycache__/",
    "*.pyc",
]


def version() -> str:
    try:
        return importlib.metadata.version("flowie")
    except importlib.metadata.PackageNotFoundError:
        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        if pyproject.is_file():
            for line in pyproject.read_text().splitlines():
                if line.startswith("version = "):
                    return line.split('"', 2)[1]
        return "unknown"


def _copy_tree(src: Path, dest: Path, force: bool, changed: list[str]) -> None:
    for child in sorted(src.rglob("*")):
        if child.is_dir() or child.name == "__pycache__":
            continue
        rel = child.relative_to(src)
        target = dest / rel
        if target.exists() and not force:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(child, target)
        changed.append(str(target))


def _copy_file(src: Path, dest: Path, force: bool, changed: list[str]) -> None:
    if dest.exists() and not force:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    changed.append(str(dest))


def _ensure_gitignore(root: Path, changed: list[str]) -> None:
    gitignore = root / ".gitignore"
    existing = gitignore.read_text().splitlines() if gitignore.exists() else []
    missing = [entry for entry in GITIGNORE_ENTRIES if entry not in existing]
    if not missing:
        return
    with gitignore.open("a") as f:
        f.write("\n# flowie runtime\n" + "\n".join(missing) + "\n")
    changed.append(f"{gitignore} (+{len(missing)} entries)")


def _ensure_db(root: Path, changed: list[str]) -> None:
    db_path = root / ".flowie" / "data" / "flowie.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema, migrations = _tracer_schema()
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
    changed.append(f"{db_path} (initialized/migrated)")


def _tracer_schema() -> tuple[str, list[tuple[str, str, str]]]:
    """Read schema constants without importing tracer's Pydantic models."""
    path = Path(__file__).resolve().parent / "tracer.py"
    module = ast.parse(path.read_text(), filename=str(path))
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
        raise RuntimeError(f"SCHEMA not found in {path}")
    return schema, migrations


def init(args: argparse.Namespace) -> int:
    root = Path.cwd()
    changed: list[str] = []
    _copy_file(TEMPLATES / "flowie.config.yaml",
               root / ".flowie" / "flowie.config.yaml", args.force, changed)
    _copy_tree(TEMPLATES / "prompt_engineering", root / ".flowie" / "prompts",
               args.force, changed)
    _copy_file(TEMPLATES / "quality.py", root / ".flowie" / "quality.py",
               args.force, changed)
    _copy_file(TEMPLATES / "env.sample", root / ".env.sample", args.force, changed)
    _copy_file(TEMPLATES / "justfile", root / "justfile", args.force, changed)
    (root / ".flowie" / "adws").mkdir(parents=True, exist_ok=True)
    _ensure_db(root, changed)
    _ensure_gitignore(root, changed)

    print(f"flowie initialized in {root}")
    print(f"  created/ensured: {len(changed)} file(s)")
    for item in changed:
        print(f"    + {item}")
    print("\nnext steps:")
    print("  1. flowie run scout \"reply with a one-line summary of this repo\"")
    print("  2. flowie run sessions")
    print("  3. flowie obs")
    return 0


def _run_builtin(name: str, argv: list[str]) -> int:
    module_name = BUILTINS[name]
    sys.argv = [f"flowie run {name}", *argv]
    # Let the builtin parse its own CLI exactly like the original script.
    runpy.run_module(f"flowie_runtime.builtins.{module_name}", run_name="__main__")
    return 0


def run(args: argparse.Namespace) -> int:
    if args.adw == "sessions":
        return _sessions()
    if args.adw in BUILTINS:
        return _run_builtin(args.adw, args.args)
    path = Path(args.adw)
    if not path.exists():
        path = Path(".flowie") / "adws" / f"{args.adw}.py"
    if not path.exists():
        known = ", ".join(sorted(BUILTINS))
        raise SystemExit(f"unknown ADW {args.adw!r}; builtins: {known}")
    sys.argv = [str(path), *args.args]
    runpy.run_path(str(path), run_name="__main__")
    return 0


def _sessions() -> int:
    db_path = Path(".flowie/data/flowie.db")
    if not db_path.exists():
        raise SystemExit("flowie db not found; run `flowie init` first")
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "select adw_id, status, substr(request,1,50), total_tokens, "
            "round(total_cost,4) from sessions order by started_at desc limit 10"
        ).fetchall()
    for row in rows:
        print("\t".join("" if value is None else str(value) for value in row))
    return 0


def make_adw(args: argparse.Namespace) -> int:
    from . import make_adw as generator

    sys.argv = [
        "flowie make-adw",
        "--name",
        args.name,
        "--agents",
        args.agents,
        "--dest-dir",
        ".flowie/adws",
        *(["--force"] if args.force else []),
    ]
    return generator.main()


def eject(args: argparse.Namespace) -> int:
    if args.kind != "adw":
        raise SystemExit("only `flowie eject adw <name>` is supported")
    if args.name not in BUILTINS:
        raise SystemExit(f"unknown builtin ADW {args.name!r}")
    src = Path(__file__).resolve().parent / "builtins" / f"{BUILTINS[args.name]}.py"
    dest = Path(".flowie") / "adws" / f"{args.name.replace('-', '_')}.py"
    if dest.exists() and not args.force:
        raise SystemExit(f"{dest} already exists; use --force to overwrite")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    print(f"ejected {args.name} to {dest}")
    return 0


def obs(_args: argparse.Namespace) -> int:
    print("Run the visualizer from the Flowie checkout:")
    print("  cd apps/visualizer")
    print("  FLOWIE_DB=$PWD/../../.flowie/data/flowie.db bun run server/index.ts")
    print("  bun run dev --host 127.0.0.1")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="flowie")
    p.add_argument("--version", action="version", version=f"flowie {version()}")
    sub = p.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="initialize .flowie in this repo")
    init_p.add_argument("--force", action="store_true")
    init_p.set_defaults(func=init)

    run_p = sub.add_parser("run", help="run a builtin or custom ADW")
    run_p.add_argument("adw")
    run_p.add_argument("args", nargs=argparse.REMAINDER)
    run_p.set_defaults(func=run)

    make_p = sub.add_parser("make-adw", help="generate .flowie/adws/<name>.py")
    make_p.add_argument("--name", required=True)
    make_p.add_argument("--agents", required=True)
    make_p.add_argument("--force", action="store_true")
    make_p.set_defaults(func=make_adw)

    eject_p = sub.add_parser("eject", help="copy a builtin into .flowie")
    eject_p.add_argument("kind")
    eject_p.add_argument("name")
    eject_p.add_argument("--force", action="store_true")
    eject_p.set_defaults(func=eject)

    obs_p = sub.add_parser("obs", help="show visualizer launch command")
    obs_p.set_defaults(func=obs)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
