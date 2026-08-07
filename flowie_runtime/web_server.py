"""Pure-Python web server for the bundled Flowie visualizer."""

from __future__ import annotations

import json
import mimetypes
import re
import sqlite3
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


MAX_LIMIT = 1000
DEFAULT_LIMIT = 500
SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
DIST_DIR = Path(__file__).resolve().parent / "web" / "dist"


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return min(maximum, max(minimum, int(value)))


def _safe_segment(value: str) -> bool:
    return bool(SAFE_SEGMENT.fullmatch(value)) and value not in {".", ".."}


class FlowieWebDb:
    def __init__(self, path: Path):
        if not path.exists():
            raise FileNotFoundError(f"flowie db not found at {path}; run `flowie init` first")
        self.path = path.resolve()
        self.sessions_dir = self.path.parent / "sessions"
        self._column_cache: dict[tuple[str, str], bool] = {}

    def _connect(self, *, readonly: bool = True) -> sqlite3.Connection:
        if readonly:
            conn = sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True)
        else:
            conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        if readonly:
            conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _has_column(self, table: str, column: str) -> bool:
        key = (table, column)
        if not self._column_cache.get(key):
            with self._connect() as conn:
                rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            self._column_cache[key] = any(row["name"] == column for row in rows)
        return self._column_cache.get(key, False)

    def _optional_column(self, table: str, column: str) -> str:
        return column if self._has_column(table, column) else f"NULL AS {column}"

    def _query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def _one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def health(self) -> dict[str, Any]:
        with self._connect() as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()
            count = conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()
        return {
            "ok": True,
            "db": str(self.path),
            "journal_mode": mode["journal_mode"] if mode else "unknown",
            "sessions": count["n"] if count else 0,
        }

    def session(self, adw_id: str) -> dict[str, Any] | None:
        return self._one(
            f"""SELECT adw_id, {self._optional_column("sessions", "adw_name")}, request,
                       status, engineer, started_at, ended_at,
                       total_tokens, total_cost,
                       {self._optional_column("sessions", "archived")}
                  FROM sessions WHERE adw_id = ?""",
            (adw_id,),
        )

    def sessions(self, limit: int = 200) -> list[dict[str, Any]]:
        archived_expr = "archived" if self._has_column("sessions", "archived") else "0"
        rows = self._query(
            f"""SELECT adw_id, {self._optional_column("sessions", "adw_name")}, request,
                       status, engineer, started_at, ended_at,
                       total_tokens, total_cost,
                       {self._optional_column("sessions", "archived")}
                  FROM sessions
                 WHERE COALESCE({archived_expr}, 0) = 0
                 ORDER BY started_at DESC, rowid DESC
                 LIMIT ?""",
            (_clamp(limit, 1, MAX_LIMIT),),
        )
        if not rows:
            return []

        ids = [row["adw_id"] for row in rows]
        placeholders = ", ".join("?" for _ in ids)
        phases = self._query(
            f"""SELECT phase_id, adw_id, seq, name, kind, owner, description, status,
                       attempt, retries, error, started_at, ended_at
                  FROM phases WHERE adw_id IN ({placeholders}) ORDER BY seq, rowid""",
            tuple(ids),
        )

        by_adw: dict[str, list[dict[str, Any]]] = {}
        for phase in phases:
            by_adw.setdefault(phase["adw_id"], []).append(phase)

        agents_by_adw = self.agents_for(ids)
        for row in rows:
            row["phases"] = by_adw.get(row["adw_id"], [])
            row["phase_count"] = len(row["phases"])
            row["agents"] = agents_by_adw.get(row["adw_id"], [])
        return rows

    def phases(self, adw_id: str) -> list[dict[str, Any]]:
        return self._query(
            """SELECT phase_id, adw_id, seq, name, kind, owner, description, status,
                      attempt, retries, error, started_at, ended_at
                 FROM phases WHERE adw_id = ? ORDER BY seq, rowid""",
            (adw_id,),
        )

    def agents_for(self, adw_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        by_adw: dict[str, list[dict[str, Any]]] = {}
        if not adw_ids:
            return by_adw
        placeholders = ", ".join("?" for _ in adw_ids)
        color = self._optional_column("agent_sessions", "color")
        ctx_tokens = self._optional_column("agent_sessions", "context_tokens")
        ctx_window = self._optional_column("agent_sessions", "context_window")

        completed = self._query(
            f"""SELECT adw_id, agent, coding_agent, model, session_id, {color},
                       {ctx_tokens}, {ctx_window}, created_at, last_used_at
                  FROM agent_sessions WHERE adw_id IN ({placeholders})
                 ORDER BY created_at, agent""",
            tuple(adw_ids),
        )
        for row in completed:
            by_adw.setdefault(row["adw_id"], []).append(row)

        started = self._query(
            f"""SELECT e.adw_id, p.owner AS agent, e.payload_json, e.started_at
                  FROM events e JOIN phases p ON p.phase_id = e.phase_id
                 WHERE e.adw_id IN ({placeholders}) AND e.type = 'agent_start'
                 ORDER BY e.rowid""",
            tuple(adw_ids),
        )
        for row in started:
            agent = row.get("agent")
            if not agent:
                continue
            if any(a.get("agent") == agent for a in by_adw.get(row["adw_id"], [])):
                continue
            try:
                payload = json.loads(row.get("payload_json") or "{}")
            except json.JSONDecodeError:
                payload = {}
            by_adw.setdefault(row["adw_id"], []).append({
                "adw_id": row["adw_id"],
                "agent": agent,
                "coding_agent": None,
                "model": payload.get("model"),
                "session_id": payload.get("session_id"),
                "color": payload.get("color"),
                "context_tokens": None,
                "context_window": None,
                "created_at": row.get("started_at"),
                "last_used_at": row.get("started_at"),
            })
        return by_adw

    def session_detail(self, adw_id: str) -> dict[str, Any] | None:
        session = self.session(adw_id)
        if not session:
            return None
        return {
            "session": session,
            "usage": self.usage(adw_id),
            "phases": self.phases(adw_id),
            "agents": self.agents_for([adw_id]).get(adw_id, []),
        }

    def usage(self, adw_id: str) -> dict[str, int]:
        rows = self._query(
            "SELECT payload_json FROM events WHERE adw_id = ? AND type = 'agent_end'",
            (adw_id,),
        )
        read = 0
        written = 0
        for row in rows:
            try:
                usage = json.loads(row.get("payload_json") or "{}").get("usage") or {}
            except json.JSONDecodeError:
                usage = {}
            read += int(usage.get("input_tokens") or 0) + int(usage.get("cache_write_tokens") or 0)
            written += int(usage.get("output_tokens") or 0)
        return {"read": read, "written": written}

    def events(self, adw_id: str, after: int = 0, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
        capped = _clamp(limit, 1, MAX_LIMIT)
        rows = self._query(
            """SELECT rowid, event_id, adw_id, phase_id, parent_id, type, name,
                      payload_json, tokens, started_at, ended_at
                 FROM events
                WHERE adw_id = ? AND rowid > ?
                ORDER BY rowid
                LIMIT ?""",
            (adw_id, max(0, after), capped),
        )
        return {
            "events": rows,
            "cursor": rows[-1]["rowid"] if rows else max(0, after),
            "has_more": len(rows) == capped,
        }

    def envelopes(self, adw_id: str) -> list[dict[str, Any]]:
        return self._query(
            """SELECT envelope_id, adw_id, phase_id, agent, output_type, payload_json,
                      valid, attempt, created_at
                 FROM envelopes WHERE adw_id = ? ORDER BY created_at, rowid""",
            (adw_id,),
        )

    def gates(self, adw_id: str) -> list[dict[str, Any]]:
        checks = self._optional_column("gate_results", "checks_json")
        return self._query(
            f"""SELECT id, adw_id, phase_id, attempt, gate, passed, violations_json,
                       {checks}, created_at
                  FROM gate_results WHERE adw_id = ? ORDER BY id""",
            (adw_id,),
        )

    def set_archived(self, adw_id: str, archived: bool) -> bool:
        if not self._has_column("sessions", "archived"):
            raise RuntimeError("this db predates the archived column; run any ADW once to migrate it")
        with self._connect(readonly=False) as conn:
            conn.execute("UPDATE sessions SET archived = ? WHERE adw_id = ?", (1 if archived else 0, adw_id))
            conn.commit()
        return self.session(adw_id) is not None

    def prompts(self, adw_id: str, agent: str) -> dict[str, str | None]:
        prompt_dir = (self.sessions_dir / adw_id / agent / "prompts").resolve()
        sessions_dir = self.sessions_dir.resolve()
        if prompt_dir != sessions_dir and sessions_dir not in prompt_dir.parents:
            raise ValueError("invalid path")

        def read(name: str) -> str | None:
            path = prompt_dir / f"{name}.md"
            return path.read_text() if path.is_file() else None

        return {"system": read("system"), "user": read("user")}


class FlowieWebHandler(BaseHTTPRequestHandler):
    server: "FlowieWebServer"

    def log_message(self, format: str, *args: object) -> None:
        return

    @property
    def db(self) -> FlowieWebDb:
        return self.server.db

    def _json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("cache-control", "no-store")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int = 500) -> None:
        self._json({"error": message}, status)

    def _body_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length") or "0")
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def _handle(self, method: str) -> None:
        try:
            if self._api(method):
                return
            if method != "GET":
                self._error("method not allowed", HTTPStatus.METHOD_NOT_ALLOWED)
                return
            self._static()
        except Exception as error:
            self._error(str(error), HTTPStatus.INTERNAL_SERVER_ERROR)

    def _api(self, method: str) -> bool:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if not path.startswith("/api/"):
            return False
        if method == "GET" and path == "/api/health":
            self._json(self.db.health())
            return True
        if method == "GET" and path == "/api/sessions":
            self._json(self.db.sessions(_int_query(query, "limit", 200)))
            return True

        parts = [unquote(part) for part in path.strip("/").split("/")]
        if len(parts) >= 3 and parts[0] == "api" and parts[1] == "sessions":
            adw_id = parts[2]
            if len(parts) == 3 and method == "GET":
                detail = self.db.session_detail(adw_id)
                if detail is None:
                    self._error(f"no session {adw_id}", HTTPStatus.NOT_FOUND)
                else:
                    self._json(detail)
                return True
            if len(parts) == 4 and parts[3] == "events" and method == "GET":
                self._json(self.db.events(
                    adw_id,
                    _int_query(query, "after", 0),
                    _int_query(query, "limit", DEFAULT_LIMIT),
                ))
                return True
            if len(parts) == 4 and parts[3] == "envelopes" and method == "GET":
                self._json(self.db.envelopes(adw_id))
                return True
            if len(parts) == 4 and parts[3] == "gates" and method == "GET":
                self._json(self.db.gates(adw_id))
                return True
            if len(parts) == 4 and parts[3] == "archive" and method == "POST":
                if not _safe_segment(adw_id):
                    self._error("invalid adw_id", HTTPStatus.BAD_REQUEST)
                    return True
                archived = bool(self._body_json().get("archived", True))
                if self.db.set_archived(adw_id, archived):
                    self._json({"adw_id": adw_id, "archived": archived})
                else:
                    self._error(f"no session {adw_id}", HTTPStatus.NOT_FOUND)
                return True
            if (
                len(parts) == 6
                and parts[3] == "agents"
                and parts[5] == "prompts"
                and method == "GET"
            ):
                agent = parts[4]
                if not _safe_segment(adw_id) or not _safe_segment(agent):
                    self._error("invalid adw_id or agent", HTTPStatus.BAD_REQUEST)
                elif not self.db.session(adw_id):
                    self._error(f"no session {adw_id}", HTTPStatus.NOT_FOUND)
                else:
                    self._json(self.db.prompts(adw_id, agent))
                return True

        self._error(f"no route {path}", HTTPStatus.NOT_FOUND)
        return True

    def _static(self) -> None:
        if not DIST_DIR.is_dir():
            self._plain(
                "Flowie web assets are not bundled in this checkout.\n"
                "Build the visualizer before packaging: cd apps/visualizer && bun run build\n",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return

        pathname = urlparse(self.path).path
        relative = pathname.lstrip("/") or "index.html"
        candidate = (DIST_DIR / relative).resolve()
        dist = DIST_DIR.resolve()
        if candidate != dist and dist not in candidate.parents:
            self._error("invalid path", HTTPStatus.BAD_REQUEST)
            return
        if not candidate.is_file():
            candidate = DIST_DIR / "index.html"
        data = candidate.read_bytes()
        mime, _encoding = mimetypes.guess_type(candidate)
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", mime or "application/octet-stream")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _plain(self, text: str, status: int) -> None:
        body = text.encode()
        self.send_response(status)
        self.send_header("content-type", "text/plain; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _int_query(query: dict[str, list[str]], key: str, fallback: int) -> int:
    try:
        return int(query.get(key, [str(fallback)])[0])
    except (TypeError, ValueError):
        return fallback


class FlowieWebServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], db: FlowieWebDb):
        super().__init__(address, FlowieWebHandler)
        self.db = db


def serve(db_path: Path, host: str, port: int, *, open_browser: Callable[[str], None] | None = None) -> int:
    db = FlowieWebDb(db_path)
    server = FlowieWebServer((host, port), db)
    actual_host, actual_port = server.server_address
    url = f"http://{actual_host}:{actual_port}"
    print(f"Flowie web: {url}", flush=True)
    print(f"Flowie db:  {db.path}", flush=True)
    print("Press Ctrl-C to stop.", flush=True)
    if open_browser:
        open_browser(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0
