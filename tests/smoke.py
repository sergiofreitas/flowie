"""Smoke tests for the Flowie CLI and generation scripts.

These tests intentionally use only the standard library. They exercise the
paths users hit first: install into an empty repo, query the initialized trace
db, and generate an ADW whose runtime contract matches Run.finish().
"""

from __future__ import annotations

import sqlite3
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from flowie_runtime.codex_schema import prepare_output_schema


ROOT = Path(__file__).resolve().parents[1]


def run_script(script: Path, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def run_flowie(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [sys.executable, "-m", "flowie_runtime", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


class InstallSmokeTest(unittest.TestCase):
    def test_install_initializes_sqlite_schema_and_gitignore(self) -> None:
        with tempfile.TemporaryDirectory(prefix="flowie-install-") as tmp:
            target = Path(tmp)
            result = run_script(ROOT / "scripts" / "install.py", cwd=target)

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            db_path = target / ".flowie" / "data" / "flowie.db"
            self.assertTrue(db_path.is_file())
            self.assertTrue((target / ".flowie" / "flowie.config.yaml").is_file())
            self.assertTrue((target / ".flowie" / "quality.py").is_file())
            self.assertTrue((target / ".flowie" / "prompts" / "planner" / "user.md").is_file())

            with sqlite3.connect(db_path) as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                session_columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(sessions)")
                }

            self.assertGreaterEqual(
                tables,
                {
                    "sessions",
                    "phases",
                    "events",
                    "envelopes",
                    "gate_results",
                    "processes",
                    "agent_sessions",
                },
            )
            self.assertIn("archived", session_columns)

            gitignore = (target / ".gitignore").read_text()
            self.assertIn(".flowie/data/", gitignore)

    def test_install_is_idempotent_for_initialized_db(self) -> None:
        with tempfile.TemporaryDirectory(prefix="flowie-install-") as tmp:
            target = Path(tmp)
            first = run_script(ROOT / "scripts" / "install.py", cwd=target)
            second = run_script(ROOT / "scripts" / "install.py", cwd=target)

            self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
            self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
            self.assertIn("flowie.db (initialized/migrated)", second.stdout)

    def test_cli_init_matches_install_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory(prefix="flowie-cli-") as tmp:
            target = Path(tmp)
            result = run_flowie("init", cwd=target)

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue((target / ".flowie" / "flowie.config.yaml").is_file())
            self.assertTrue((target / ".flowie" / "data" / "flowie.db").is_file())


class MakeAdwSmokeTest(unittest.TestCase):
    def test_generated_adw_uses_current_run_finish_contract(self) -> None:
        with tempfile.TemporaryDirectory(prefix="flowie-make-adw-") as tmp:
            target = Path(tmp)
            result = run_script(
                ROOT / "scripts" / "make_adw.py",
                "--name",
                "review_docs",
                "--agents",
                "scout,builder",
                cwd=target,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            generated = target / ".flowie" / "adws" / "review_docs.py"
            text = generated.read_text()

            self.assertIn(
                'dependencies = ["pydantic", "python-dotenv", "pyyaml", "rich"]',
                text,
            )
            self.assertIn("return run.finish()", text)
            self.assertNotIn("run.succeeded", text)
            self.assertIn("from flowie_runtime import agents, gates, session, utils", text)

            compile_result = subprocess.run(
                [sys.executable, "-B", "-m", "py_compile", str(generated)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                compile_result.returncode,
                0,
                compile_result.stderr + compile_result.stdout,
            )

    def test_generated_adw_imports_generic_output_for_unknown_agents(self) -> None:
        with tempfile.TemporaryDirectory(prefix="flowie-make-adw-") as tmp:
            target = Path(tmp)
            result = run_script(
                ROOT / "scripts" / "make_adw.py",
                "--name",
                "custom",
                "--agents",
                "researcher",
                cwd=target,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            text = (target / ".flowie" / "adws" / "custom.py").read_text()
            self.assertIn("GenericOutput", text)

    def test_cli_make_adw_writes_project_overlay(self) -> None:
        with tempfile.TemporaryDirectory(prefix="flowie-cli-") as tmp:
            target = Path(tmp)
            result = run_flowie(
                "make-adw",
                "--name",
                "review_docs",
                "--agents",
                "scout,builder",
                cwd=target,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue((target / ".flowie" / "adws" / "review_docs.py").is_file())


class CodexSchemaSmokeTest(unittest.TestCase):
    def test_codex_output_schema_is_strict_for_objects(self) -> None:
        schema = prepare_output_schema({
            "type": "object",
            "properties": {
                "status": {"type": "string", "default": "success"},
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"file": {"type": "string"}, "note": {"type": "string"}},
                    },
                },
            },
        })

        def object_schemas(value):
            if isinstance(value, dict):
                if value.get("type") == "object" or "properties" in value:
                    yield value
                for child in value.values():
                    yield from object_schemas(child)
            elif isinstance(value, list):
                for child in value:
                    yield from object_schemas(child)

        objects = list(object_schemas(schema))
        self.assertTrue(objects)
        for obj in objects:
            self.assertIs(obj.get("additionalProperties"), False)
            self.assertEqual(set(obj["required"]), set(obj["properties"]))
        self.assertNotIn("default", schema["properties"]["status"])

    def test_generic_output_schema_root_is_codex_strict(self) -> None:
        schema = prepare_output_schema({
            "properties": {
                "status": {"type": "string"},
                "summary": {"type": "string"},
            },
        })

        self.assertIs(schema.get("additionalProperties"), False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
