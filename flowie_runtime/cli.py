"""Flowie command line interface."""

from __future__ import annotations

import argparse
import ast
import importlib.metadata
import runpy
import shutil
import sqlite3
import sys
from collections.abc import Sequence
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
    if args.with_justfile:
        _copy_file(TEMPLATES / "justfile", root / "justfile", args.force, changed)
    (root / ".flowie" / "adws").mkdir(parents=True, exist_ok=True)
    _ensure_db(root, changed)
    _ensure_gitignore(root, changed)

    print(f"flowie initialized in {root}")
    print(f"  created/ensured: {len(changed)} file(s)")
    for item in changed:
        print(f"    + {item}")
    print("\nnext steps:")
    print("  1. flowie demo")
    print("  2. flowie sessions")
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


def _connect_db() -> sqlite3.Connection:
    db_path = Path(".flowie/data/flowie.db")
    if not db_path.exists():
        raise SystemExit("flowie db not found; run `flowie init` first")
    try:
        return sqlite3.connect(db_path)
    except sqlite3.OperationalError as error:
        raise SystemExit(f"cannot open Flowie db at {db_path}: {error}") from error


def _fetch_rows(query: str, params: Sequence[object] = ()) -> list[Sequence[object]]:
    try:
        with _connect_db() as conn:
            return conn.execute(query, params).fetchall()
    except sqlite3.OperationalError as error:
        raise SystemExit(f"cannot read Flowie db: {error}") from error


def _print_rows(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
    widths = [len(header) for header in headers]
    for row in rows:
        for i, value in enumerate(row):
            widths[i] = max(widths[i], len("" if value is None else str(value)))
    print("  ".join(header.ljust(widths[i]) for i, header in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(("" if value is None else str(value)).ljust(widths[i])
                        for i, value in enumerate(row)))


def _sessions(limit: int = 10) -> int:
    rows = _fetch_rows(
        "select adw_id, status, substr(request,1,50), total_tokens, "
        "round(total_cost,4) from sessions order by started_at desc limit ?",
        (limit,),
    )
    if not rows:
        print("no Flowie sessions yet")
        return 0
    _print_rows(("adw_id", "status", "request", "tokens", "cost"), rows)
    return 0


def sessions(args: argparse.Namespace) -> int:
    return _sessions(args.limit)


def phases(args: argparse.Namespace) -> int:
    rows = _fetch_rows(
        "select seq, name, kind, owner, status, attempt from phases "
        "where adw_id=? order by seq",
        (args.adw_id,),
    )
    if not rows:
        raise SystemExit(f"no phases found for {args.adw_id}")
    _print_rows(("seq", "name", "kind", "owner", "status", "attempt"), rows)
    return 0


def tail(args: argparse.Namespace) -> int:
    rows = _fetch_rows(
        "select rowid, type, name, started_at from events where adw_id=? "
        "order by rowid desc limit ?",
        (args.adw_id, args.limit),
    )
    if not rows:
        raise SystemExit(f"no events found for {args.adw_id}")
    _print_rows(("rowid", "type", "name", "started_at"), rows)
    return 0


def procs(args: argparse.Namespace) -> int:
    rows = _fetch_rows(
        "select kind, name, pid, command, started_at from processes "
        "where adw_id=? and ended_at is null order by id",
        (args.adw_id,),
    )
    if not rows:
        print(f"no running processes for {args.adw_id}")
        return 0
    _print_rows(("kind", "name", "pid", "command", "started_at"), rows)
    return 0


def _yaml_scalar(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.split("#", 1)[0].strip()
    return text.strip("'\"")


def _fallback_roster(path: Path) -> tuple[dict[str, str], list[dict[str, str]]]:
    defaults: dict[str, str] = {}
    agents: list[dict[str, str]] = []
    section = ""
    current: dict[str, str] | None = None
    for raw_line in path.read_text().splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped == "defaults:":
            section = "defaults"
            current = None
            continue
        if stripped == "agents:":
            section = "agents"
            current = None
            continue
        if section == "defaults" and line.startswith("  ") and ":" in stripped:
            key, value = stripped.split(":", 1)
            if key in {"coding_agent", "model", "thinking"}:
                defaults[key] = _yaml_scalar(value)
            continue
        if section == "agents" and stripped.startswith("- name:"):
            current = {"name": _yaml_scalar(stripped.split(":", 1)[1])}
            agents.append(current)
            continue
        if section == "agents" and current is not None and line.startswith("    ") and ":" in stripped:
            key, value = stripped.split(":", 1)
            if key in {"coding_agent", "model", "thinking"}:
                current[key] = _yaml_scalar(value)
    return defaults, agents


def _read_roster(path: Path) -> tuple[dict[str, str], list[dict[str, str]]]:
    try:
        import yaml
    except ModuleNotFoundError:
        return _fallback_roster(path)
    raw = yaml.safe_load(path.read_text()) or {}
    defaults = {
        key: _yaml_scalar(value)
        for key, value in (raw.get("defaults") or {}).items()
        if key in {"coding_agent", "model", "thinking"}
    }
    agents = [
        {
            key: _yaml_scalar(value)
            for key, value in (agent or {}).items()
            if key in {"name", "coding_agent", "model", "thinking"}
        }
        for agent in (raw.get("agents") or [])
    ]
    return defaults, agents


def rosters(_args: argparse.Namespace) -> int:
    paths = sorted(Path(".flowie").glob("*.config.yaml"))
    if not paths:
        raise SystemExit("no Flowie rosters found; run `flowie init` first")
    for index, path in enumerate(paths):
        if index:
            print("")
        print(path)
        defaults, roster_agents = _read_roster(path)
        rows = [
            (
                agent.get("name", ""),
                agent.get("coding_agent") or defaults.get("coding_agent", ""),
                agent.get("model") or defaults.get("model", ""),
                agent.get("thinking") or defaults.get("thinking", ""),
            )
            for agent in roster_agents
        ]
        _print_rows(("agent", "coding_agent", "model", "thinking"), rows)
    return 0


def demo(_args: argparse.Namespace) -> int:
    print("1/2  prompt: one agent, one prompt")
    first = run(argparse.Namespace(
        adw="prompt",
        args=["--agent", "scout", "reply with a one-line summary of this repo"],
    ))
    if first != 0:
        return first
    print("\n2/2  scout: read-only recon")
    second = run(argparse.Namespace(
        adw="scout",
        args=["list the top-level directories in this repo and what each is for. change nothing."],
    ))
    if second == 0:
        print("\nboth done. now run:  flowie sessions")
    return second


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


def obs(args: argparse.Namespace) -> int:
    db_path = Path(".flowie/data/flowie.db")
    if not db_path.exists():
        raise SystemExit("flowie db not found; run `flowie init` first")
    print(f"Flowie observability")
    print(f"db: {db_path}")
    print("")
    _sessions(args.limit)
    print("")
    print("details:")
    print("  flowie phases <adw_id>")
    print("  flowie tail <adw_id>")
    print("  flowie procs <adw_id>")
    return 0


def web(args: argparse.Namespace) -> int:
    db_path = Path(args.db or ".flowie/data/flowie.db").resolve()
    if not db_path.exists():
        raise SystemExit(f"flowie db not found at {db_path}; run `flowie init` first")

    from .web_server import serve

    return serve(db_path, args.host, args.port)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="flowie")
    p.add_argument("--version", action="version", version=f"flowie {version()}")
    sub = p.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="initialize .flowie in this repo")
    init_p.add_argument("--force", action="store_true")
    init_p.add_argument("--with-justfile", action="store_true",
                        help="also stamp optional just recipes")
    init_p.set_defaults(func=init)

    demo_p = sub.add_parser("demo", help="run two cheap read-only starter ADWs")
    demo_p.set_defaults(func=demo)

    run_p = sub.add_parser("run", help="run a builtin or custom ADW")
    run_p.add_argument("adw")
    run_p.add_argument("args", nargs=argparse.REMAINDER)
    run_p.set_defaults(func=run)

    make_p = sub.add_parser("make-adw", help="generate .flowie/adws/<name>.py")
    make_p.add_argument("--name", required=True)
    make_p.add_argument("--agents", required=True)
    make_p.add_argument("--force", action="store_true")
    make_p.set_defaults(func=make_adw)

    sessions_p = sub.add_parser("sessions", help="show recent Flowie sessions")
    sessions_p.add_argument("--limit", type=int, default=10)
    sessions_p.set_defaults(func=sessions)

    phases_p = sub.add_parser("phases", help="show phases for an ADW session")
    phases_p.add_argument("adw_id")
    phases_p.set_defaults(func=phases)

    tail_p = sub.add_parser("tail", help="show recent events for an ADW session")
    tail_p.add_argument("adw_id")
    tail_p.add_argument("--limit", type=int, default=25)
    tail_p.set_defaults(func=tail)

    procs_p = sub.add_parser("procs", help="show running processes for an ADW session")
    procs_p.add_argument("adw_id")
    procs_p.set_defaults(func=procs)

    rosters_p = sub.add_parser("rosters", help="show configured Flowie rosters")
    rosters_p.set_defaults(func=rosters)

    eject_p = sub.add_parser("eject", help="copy a builtin into .flowie")
    eject_p.add_argument("kind")
    eject_p.add_argument("name")
    eject_p.add_argument("--force", action="store_true")
    eject_p.set_defaults(func=eject)

    obs_p = sub.add_parser("obs", help="show a terminal observability summary")
    obs_p.add_argument("--limit", type=int, default=10)
    obs_p.set_defaults(func=obs)

    web_p = sub.add_parser("web", help="start the web visualizer for Flowie sessions")
    web_p.add_argument("--db", default=None, help="path to flowie.db (default: .flowie/data/flowie.db)")
    web_p.add_argument("--host", default="127.0.0.1", help="host to bind")
    web_p.add_argument("--port", type=int, default=4601, help="port to bind")
    web_p.set_defaults(func=web)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
