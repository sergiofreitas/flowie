"""Codex CLI interface for Flowie.

Runs `codex exec --json` non-interactively, stores the raw JSONL stream, and
uses `--output-schema` so the final assistant message is shaped as the ADW
envelope declared by the phase.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

from .data_types import CodexRequest, CodexResult
from .codex_schema import prepare_output_schema

CODEX_PATH = os.environ.get("CODEX_PATH", "codex")
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def validate_model(_model: str) -> None:
    """Codex validates model availability at invocation time."""
    return None


def run(
    request: CodexRequest,
    on_event: Optional[Callable[[dict], None]] = None,
    on_spawn: Optional[Callable[[int], None]] = None,
    on_exit: Optional[Callable[[int], None]] = None,
) -> CodexResult:
    prompt = (
        "Follow this system instruction for this ADW phase:\n\n"
        f"{request.system_prompt}\n\n"
        "Now complete the phase request. Return only the JSON object required "
        "by the supplied output schema.\n\n"
        f"{request.prompt}"
    )
    base = [
        CODEX_PATH,
        "exec",
        "--json",
        "--model",
        request.model,
        "--output-schema",
        request.output_schema_path,
        "--output-last-message",
        request.last_message_path,
    ]
    if request.session_id:
        cmd = [
            CODEX_PATH,
            "exec",
            "resume",
            "--json",
            "--model",
            request.model,
            "--output-schema",
            request.output_schema_path,
            "--output-last-message",
            request.last_message_path,
            request.session_id,
            "-",
        ]
    else:
        cmd = base + ["--cd", request.cwd, "--sandbox", request.sandbox, "-"]

    raw_path = Path(request.raw_output_path)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    Path(request.last_message_path).parent.mkdir(parents=True, exist_ok=True)

    result = CodexResult(session_id=request.session_id)
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        cwd=request.cwd,
    )
    if process.stdin:
        process.stdin.write(prompt)
        process.stdin.close()
    if on_spawn:
        on_spawn(process.pid)

    with raw_path.open("a") as raw:
        assert process.stdout is not None
        for line in process.stdout:
            raw.write(line)
            raw.flush()
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            result.session_id = _find_session_id(event) or result.session_id
            _fold_usage(result, event)
            if on_event:
                on_event(event)

    stderr = process.stderr.read() if process.stderr else ""
    result.returncode = process.wait()
    if on_exit:
        on_exit(process.pid)

    last = Path(request.last_message_path)
    if last.exists():
        result.text = last.read_text()
    if result.returncode != 0 and not result.text:
        detail = _failure_detail(stderr, raw_path)
        raise RuntimeError(f"codex exec exited {result.returncode}: {detail}")
    return result


def _failure_detail(stderr: str, raw_path: Path) -> str:
    parts = []
    if stderr.strip():
        parts.append(stderr.strip())
    raw_tail = _raw_error_tail(raw_path)
    if raw_tail:
        parts.append(raw_tail)
    if not parts:
        parts.append(f"no stderr; raw output: {raw_path}")
    return "\n".join(parts)[-2000:]


def _raw_error_tail(raw_path: Path) -> str:
    if not raw_path.exists():
        return ""
    lines = raw_path.read_text(errors="replace").splitlines()[-50:]
    messages = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            messages.append(line)
            continue
        if event.get("type") == "error":
            messages.append(str(event.get("message") or event))
        elif event.get("type") == "turn.failed":
            messages.append(json.dumps(event.get("error") or event))
    return "\n".join(messages).strip()


def _fold_usage(result: CodexResult, event: dict[str, Any]) -> None:
    usage = event.get("usage") or event.get("token_usage") or {}
    if not isinstance(usage, dict):
        return
    input_tokens = usage.get("input_tokens") or usage.get("input") or 0
    output_tokens = usage.get("output_tokens") or usage.get("output") or 0
    total = usage.get("total_tokens") or usage.get("total") or input_tokens + output_tokens
    result.usage.input_tokens += input_tokens
    result.usage.output_tokens += output_tokens
    result.usage.total_tokens += total
    result.tokens += total


def _find_session_id(value: Any) -> str:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(child, str) and ("session" in key or "thread" in key or "conversation" in key):
                if UUID_RE.match(child) or child:
                    return child
            found = _find_session_id(child)
            if found:
                return found
    if isinstance(value, list):
        for child in value:
            found = _find_session_id(child)
            if found:
                return found
    return ""


class ToolCallTracker:
    """Best-effort normalizer for Codex JSONL tool-call events."""

    def observe(self, event: dict) -> Optional[dict]:
        kind = str(event.get("type") or event.get("event") or "")
        if "tool" not in kind and "command" not in event:
            return None
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else event
        tool = payload.get("tool") or payload.get("name") or "tool"
        args = payload.get("args") or payload.get("arguments") or payload.get("command") or {}
        ok = payload.get("ok")
        if ok is None:
            ok = payload.get("exit_code", 0) == 0 if "exit_code" in payload else True
        return {
            "label": f"{tool}: {str(args)[:80]}",
            "tool": tool,
            "args": args,
            "result_snippet": str(payload.get("result") or payload.get("output") or "")[:1200],
            "ok": ok,
            "duration_ms": payload.get("duration_ms"),
        }
