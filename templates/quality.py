"""Project-local Flowie quality commands.

Replace the placeholder argv lists with this repo's real commands. These
functions are loaded by flowie_runtime.quality when an ADW runs.
"""

from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path
from typing import Callable

from flowie_runtime.data_types import (
    EventRecord,
    QualityCheckResult,
    QualityCheckSpec,
    QualityResult,
)
from flowie_runtime.utils import now_iso, operator_env

TAIL_CHARS = 4_000


def _placeholder(name: str) -> list[str]:
    return [
        "python3",
        "-c",
        "import sys; print('PLACEHOLDER %s: edit .flowie/quality.py'); sys.exit(1)"
        % name,
    ]


def _check_dir(run, name: str) -> Path:
    seq = run.phases[-1].seq if run.phases else 0
    path = run.context_handoff_dir / "quality" / f"{seq:02d}_{name}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run(spec: QualityCheckSpec, run) -> QualityCheckResult:
    phase = run.phases[-1]
    output_dir = _check_dir(run, spec.name)
    output_artifact = output_dir / "command.log"
    command = shlex.join(spec.argv)
    env = operator_env()
    run.console.note(f"quality {spec.name}: {command}")
    started_at = now_iso()
    clock = time.monotonic()
    stdout = ""
    stderr = ""
    try:
        completed = subprocess.run(
            spec.argv,
            cwd=run.repo_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=spec.timeout_seconds,
        )
        returncode = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as error:
        returncode = 124
        stdout = error.stdout or ""
        stderr = (error.stderr or "") + f"\nTimed out after {spec.timeout_seconds}s."
    except OSError as error:
        returncode = 127
        stderr = str(error)

    duration = time.monotonic() - clock
    output_artifact.write_text(
        f"$ {command}\nexit: {returncode}\nduration_seconds: {duration:.3f}\n"
        f"\n--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}\n"
    )
    passed = returncode == 0
    run.tracer.event(EventRecord(
        adw_id=run.adw_id,
        phase_id=phase.phase_id,
        type="tool_call",
        name=f"quality:{spec.name}",
        payload={
            "area": spec.area,
            "operation": spec.operation,
            "command": command,
            "returncode": returncode,
            "passed": passed,
            "output_artifact": str(output_artifact),
        },
        started_at=started_at,
        ended_at=now_iso(),
    ))
    run.console.note(
        f"quality {spec.name}: {'passed' if passed else 'failed'} "
        f"(exit {returncode}, {duration:.1f}s)"
    )
    return QualityCheckResult(
        name=spec.name,
        area=spec.area,
        operation=spec.operation,
        command=command,
        returncode=returncode,
        passed=passed,
        duration_seconds=duration,
        output_artifact=str(output_artifact),
        output_tail=(stdout + stderr)[-TAIL_CHARS:],
    )


def test(run) -> QualityCheckResult:
    return _run(QualityCheckSpec(
        name="test",
        area="backend",
        operation="build",
        argv=_placeholder("test"),
        timeout_seconds=600,
    ), run)


def lint(run) -> QualityCheckResult:
    return _run(QualityCheckSpec(
        name="lint",
        area="backend",
        operation="lint",
        argv=_placeholder("lint"),
    ), run)


def typecheck(run) -> QualityCheckResult:
    return _run(QualityCheckSpec(
        name="typecheck",
        area="backend",
        operation="typecheck",
        argv=_placeholder("typecheck"),
    ), run)


def build(run) -> QualityCheckResult:
    return _run(QualityCheckSpec(
        name="build",
        area="backend",
        operation="build",
        argv=_placeholder("build"),
    ), run)


def run_tests(run) -> QualityResult:
    check = test(run)
    failures = ([] if check.passed else
                [f"{check.name}: `{check.command}` exited {check.returncode}\n"
                 f"{check.output_tail}".rstrip()])
    return QualityResult(passed=check.passed, checks=[check], failures=failures,
                         artifacts=[check.output_artifact])


def run_quality(run) -> QualityResult:
    blocks: list[Callable] = [test, lint, typecheck, build]
    checks = [block(run) for block in blocks]
    failures = [
        f"{check.name}: `{check.command}` exited {check.returncode}\n{check.output_tail}".rstrip()
        for check in checks if not check.passed
    ]
    return QualityResult(
        passed=not failures,
        checks=checks,
        failures=failures,
        artifacts=[check.output_artifact for check in checks],
    )
