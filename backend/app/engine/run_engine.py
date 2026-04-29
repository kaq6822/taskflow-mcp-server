from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.engine.dag import topo_sort
from app.engine.log_bus import log_bus
from app.engine.policies import (
    AllowlistError,
    check_allowlist,
    check_forbidden_state_command,
    filter_env,
)
from app.engine.worker import WorkerResult, execute_argv
from app.models import Job, Run, RunStep, utcnow
from app.services.audit import append_event


def _ts() -> str:
    d = datetime.now(timezone.utc).astimezone()
    return d.strftime("%H:%M:%S")


def _step_cwd(step_spec: dict) -> tuple[Path, bool]:
    raw = step_spec.get("cwd")
    if isinstance(raw, str) and raw.strip():
        return Path(raw), True
    return settings.step_cwd, False


class RunEngine:
    """Single-process engine. Per-job asyncio.Lock enforces concurrency=1."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._live: dict[str, int] = {}  # job_id → run_id
        self._tasks: dict[int, asyncio.Task] = {}
        self._pending_launch: dict[int, str] = {}
        self._cancelled: set[int] = set()

    def live_run_for(self, job_id: str) -> int | None:
        return self._live.get(job_id)

    def has_run(self, run_id: int) -> bool:
        return run_id in self._tasks

    async def run_exists(self, run_id: int) -> bool:
        async with SessionLocal() as s:
            return (await s.get(Run, run_id)) is not None

    async def start(
        self,
        session: AsyncSession,
        *,
        job: Job,
        trigger: str,
        actor: str,
        artifact_ref: str | None = None,
        idempotency_key: str | None = None,
    ) -> Run:
        lock = self._locks.setdefault(job.id, asyncio.Lock())
        if lock.locked():
            raise RuntimeError("job busy")
        order = topo_sort(job.steps)
        run = Run(
            job_id=job.id,
            status="RUNNING",
            trigger=trigger,
            actor=actor,
            order=order,
            artifact_ref=artifact_ref,
            idempotency_key=idempotency_key,
        )
        session.add(run)
        await session.flush()
        for sid in order:
            session.add(RunStep(run_id=run.id, step_id=sid, state="PENDING"))
        await session.flush()

        self._live[job.id] = run.id
        self._pending_launch[run.id] = job.id
        return run

    def launch(self, run_id: int) -> None:
        """Spawn the per-run asyncio task. Call this *after* the caller's
        transaction has committed, so the background task's fresh session can
        read the Run row."""
        job_id = self._pending_launch.pop(run_id, None)
        if job_id is None:
            return
        self._tasks[run_id] = asyncio.create_task(self._run_loop(job_id, run_id))

    async def cancel(self, session: AsyncSession, run_id: int) -> Run | None:
        run = await session.get(Run, run_id)
        if not run or run.status != "RUNNING":
            return run
        self._cancelled.add(run_id)
        task = self._tasks.get(run_id)
        if task:
            task.cancel()
        # Mark run-level state immediately so the cancel HTTP response is
        # accurate; _run_loop's cancel-finalizer will also update this view,
        # but racing clients that poll before the loop settles still see it.
        run.status = "FAILED"
        run.err_message = "사용자 취소"
        run.finished_at = utcnow()
        await session.flush()
        return run

    async def _run_loop(self, job_id: str, run_id: int) -> None:
        """Owned by engine. Re-opens its own DB session."""
        lock = self._locks[job_id]
        await lock.acquire()
        try:
            try:
                await self._run_loop_body(job_id, run_id)
            except asyncio.CancelledError:
                # P2-7: when the active step is cancelled the body raises before
                # it reaches `run.finished`. Publish the terminal event so SSE
                # subscribers and MCP `subscribe_run` consumers unblock and see
                # the cancelled state instead of silently dropping.
                await self._finalize_cancelled(job_id, run_id)
                # Do not re-raise — this task is the engine's own; swallowing
                # keeps engine bookkeeping in the `finally` below simple.
        finally:
            self._live.pop(job_id, None)
            self._tasks.pop(run_id, None)
            self._cancelled.discard(run_id)
            lock.release()

    async def _run_loop_body(self, job_id: str, run_id: int) -> None:
        # Phase A — snapshot immutable Run/Job fields into plain values. The
        # session is closed immediately so the SQLite writer lock is never
        # held while subprocesses execute below.
        async with SessionLocal() as session:
            run = await session.get(Run, run_id)
            assert run is not None
            job = await session.get(Job, job_id)
            assert job is not None
            order: list[str] = list(run.order)
            job_steps: dict[str, dict] = {s["id"]: s for s in job.steps}
            job_on_failure: str = job.on_failure
            actor: str = run.actor
            trigger: str = run.trigger
            started_at = run.started_at
            log_bus.publish(
                run_id,
                "run.started",
                {"run_id": run_id, "job_id": job_id, "at": started_at.isoformat()},
            )

        # Phase B — each step owns its own short transactions. Subprocess I/O
        # happens entirely outside any DB session.
        failed = False
        failed_step: str | None = None
        err_message: str | None = None
        for sid in order:
            if run_id in self._cancelled:
                failed = True
                break
            step_spec = job_steps[sid]
            # P2-4: once a previous step has set `failed=True` via STOP or
            # RETRY-exhausted, skip downstream regardless of job default.
            if failed:
                async with SessionLocal() as s:
                    rs = (
                        await s.execute(
                            select(RunStep).where(
                                RunStep.run_id == run_id, RunStep.step_id == sid
                            )
                        )
                    ).scalar_one()
                    rs.state = "SKIPPED"
                    await s.commit()
                log_bus.publish(
                    run_id,
                    "step.finished",
                    {"step_id": sid, "state": "SKIPPED", "elapsed_sec": 0.0},
                )
                continue
            result = await self._execute_step(
                run_id=run_id,
                step_id=sid,
                step_spec=step_spec,
                actor=actor,
                trigger=trigger,
            )
            if result.state in ("FAILED", "TIMEOUT"):
                failed_step = sid
                err_message = result.err_message
                # Step-level on_failure wins over job default (docs/02 §2.3).
                on_fail = step_spec.get("on_failure", job_on_failure)
                if on_fail == "RETRY":
                    log_bus.publish(
                        run_id,
                        "step.log",
                        {
                            "step_id": sid,
                            "ts": _ts(),
                            "lvl": "warn",
                            "text": "retrying once …",
                        },
                    )
                    retry = await self._execute_step(
                        run_id=run_id,
                        step_id=sid,
                        step_spec=step_spec,
                        actor=actor,
                        trigger=trigger,
                    )
                    if retry.state in ("FAILED", "TIMEOUT"):
                        failed = True
                        # Preserve first-attempt failure metadata, matching the
                        # pre-split behavior (docs/02 §10.4).
                    else:
                        # P2-5: retry succeeded — clear the failure metadata
                        # from the first attempt so the final response
                        # doesn't claim a step failed when it ultimately
                        # succeeded.
                        failed_step = None
                        err_message = None
                elif on_fail == "CONTINUE":
                    pass  # proceed without marking the run failed
                else:
                    # STOP / ROLLBACK — stop downstream execution.
                    failed = True

        # Phase C — finalize Run + audit append in a single short transaction.
        async with SessionLocal() as session:
            run = await session.get(Run, run_id)
            assert run is not None
            run.finished_at = utcnow()
            run.duration_sec = (run.finished_at - started_at).total_seconds()
            if run_id in self._cancelled:
                run.status = "FAILED"
                run.err_message = err_message or "사용자 취소"
                run.failed_step = failed_step
            elif failed:
                run.status = (
                    "TIMEOUT"
                    if err_message and "timeout" in err_message
                    else "FAILED"
                )
                run.err_message = err_message
                run.failed_step = failed_step
            else:
                run.status = "SUCCESS"
                # Clear per-step failure metadata accumulated via CONTINUE/RETRY
                # so a successful run never reports `failed_step` in its Agent
                # response (docs/02 §10.4 treats `failed_step` as "where the
                # run ended up failing", which is nothing on SUCCESS).
                run.failed_step = None
                run.err_message = None
            final_status = run.status
            final_failed_step = run.failed_step
            final_err_message = run.err_message
            final_duration = run.duration_sec
            await append_event(
                session,
                who=actor,
                kind="job.run.fail" if final_status != "SUCCESS" else "job.run.done",
                target=f"{job_id} #{run_id}",
                src="mcp" if trigger == "mcp" else "web",
                result="FAIL" if final_status != "SUCCESS" else "OK",
            )
        log_bus.publish(
            run_id,
            "run.finished",
            {
                "run_id": run_id,
                "status": final_status,
                "failed_step": final_failed_step,
                "err_message": final_err_message,
                "duration_sec": final_duration,
            },
        )

    async def _finalize_cancelled(self, job_id: str, run_id: int) -> None:
        """Finalize a run that was cancelled mid-step. Opens a fresh session
        because the loop body's session was aborted by the cancellation."""
        try:
            async with SessionLocal() as s:
                run = await s.get(Run, run_id)
                if run is None:
                    return
                if run.status == "RUNNING":
                    run.status = "FAILED"
                    run.err_message = run.err_message or "사용자 취소"
                    run.finished_at = utcnow()
                    run.duration_sec = (
                        run.finished_at - run.started_at
                    ).total_seconds()
                # With per-step commits the step that was mid-execution stays
                # at RUNNING after cancellation. Flip any such zombies to
                # FAILED so the Run schema stays consistent for clients.
                zombies = (
                    await s.execute(
                        select(RunStep).where(
                            RunStep.run_id == run_id, RunStep.state == "RUNNING"
                        )
                    )
                ).scalars().all()
                for rs in zombies:
                    rs.state = "FAILED"
                    rs.finished_at = rs.finished_at or utcnow()
                await append_event(
                    s,
                    who=run.actor,
                    kind="job.run.fail",
                    target=f"{job_id} #{run_id}",
                    src="mcp" if run.trigger == "mcp" else "web",
                    result="FAIL",
                )
            log_bus.publish(
                run_id,
                "run.finished",
                {
                    "run_id": run_id,
                    "status": "FAILED",
                    "failed_step": run.failed_step,
                    "err_message": run.err_message,
                    "duration_sec": run.duration_sec,
                },
            )
        except Exception:
            # Last-resort: always close the stream for subscribers.
            log_bus.publish(
                run_id,
                "run.finished",
                {
                    "run_id": run_id,
                    "status": "FAILED",
                    "failed_step": None,
                    "err_message": "cancelled",
                    "duration_sec": 0.0,
                },
            )

    async def _execute_step(
        self,
        *,
        run_id: int,
        step_id: str,
        step_spec: dict,
        actor: str,
        trigger: str,
    ) -> WorkerResult:
        cmd: list[str] = step_spec["cmd"]
        timeout: int = step_spec.get("timeout", 60)
        step_cwd, has_custom_cwd = _step_cwd(step_spec)
        sid = step_id

        # Mark RUNNING — short transaction. Clear any terminal fields left
        # over from a previous attempt (RETRY re-enters this path); without
        # this, pollers can observe state=RUNNING alongside a stale
        # finished_at/exit_code from the failed first attempt.
        async with SessionLocal() as s:
            rs = (
                await s.execute(
                    select(RunStep).where(
                        RunStep.run_id == run_id, RunStep.step_id == sid
                    )
                )
            ).scalar_one()
            rs.state = "RUNNING"
            rs.started_at = utcnow()
            rs.finished_at = None
            rs.exit_code = None
            rs.elapsed_sec = 0.0
            rs.logs_path = None
            await s.commit()
        log_bus.publish(
            run_id, "step.started", {"step_id": sid, "cmd": cmd, "timeout": timeout}
        )
        log_bus.publish(
            run_id,
            "step.log",
            {"step_id": sid, "ts": _ts(), "lvl": "cmd", "text": "$ " + " ".join(cmd)},
        )
        log_bus.publish(
            run_id,
            "step.log",
            {
                "step_id": sid,
                "ts": _ts(),
                "lvl": "dim",
                "text": f"cwd={step_cwd} · timeout={timeout}s · shell=False",
            },
        )

        # Allowlist re-check (defense in depth)
        try:
            check_forbidden_state_command(cmd)
            check_allowlist(cmd)
        except AllowlistError as e:
            async with SessionLocal() as s:
                rs = (
                    await s.execute(
                        select(RunStep).where(
                            RunStep.run_id == run_id, RunStep.step_id == sid
                        )
                    )
                ).scalar_one()
                rs.state = "FAILED"
                rs.finished_at = utcnow()
                rs.exit_code = -1
                rs.elapsed_sec = 0.0
                await append_event(
                    s,
                    who=actor,
                    kind="policy.violation",
                    target=f"run #{run_id} step {sid}",
                    src="mcp" if trigger == "mcp" else "web",
                    result="DENY",
                )
            log_bus.publish(
                run_id,
                "step.log",
                {"step_id": sid, "ts": _ts(), "lvl": "err", "text": f"DENY: {e}"},
            )
            log_bus.publish(
                run_id,
                "step.finished",
                {"step_id": sid, "state": "FAILED", "elapsed_sec": 0.0},
            )
            return WorkerResult(
                state="FAILED", elapsed=0.0, exit_code=-1, err_message=str(e)
            )

        log_path = settings.logs_dir / str(run_id) / f"{sid}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        def on_line(stream: str, text: str) -> None:
            lvl = "err" if stream == "stderr" else "info"
            log_bus.publish(
                run_id, "step.log", {"step_id": sid, "ts": _ts(), "lvl": lvl, "text": text}
            )

        # P2-6: merge step-level env onto the worker process env so jobs can
        # configure per-step variables. Pass through the SECRET_* filter so
        # secret names still get masked in logs.
        base_env = dict(os.environ)
        base_env.update(step_spec.get("env", {}))
        env, masked = filter_env(base_env)
        if masked:
            log_bus.publish(
                run_id,
                "step.log",
                {
                    "step_id": sid,
                    "ts": _ts(),
                    "lvl": "dim",
                    "text": f"env: secrets masked ({', '.join(masked)})",
                },
            )
        # Subprocess runs with no DB session open — this is the window that
        # used to hold the SQLite writer lock for the full step timeout.
        result = await execute_argv(
            cmd,
            cwd=step_cwd,
            timeout=timeout,
            env=env,
            log_path=log_path,
            on_line=on_line,
            create_cwd=not has_custom_cwd,
        )

        # Finalize step state — short transaction.
        async with SessionLocal() as s:
            rs = (
                await s.execute(
                    select(RunStep).where(
                        RunStep.run_id == run_id, RunStep.step_id == sid
                    )
                )
            ).scalar_one()
            rs.state = result.state
            rs.elapsed_sec = result.elapsed
            rs.exit_code = result.exit_code
            rs.finished_at = utcnow()
            rs.logs_path = str(log_path)
            await s.commit()
        if result.state == "SUCCESS":
            log_bus.publish(
                run_id,
                "step.log",
                {
                    "step_id": sid,
                    "ts": _ts(),
                    "lvl": "ok",
                    "text": f"✓ done ({result.elapsed:.2f}s · exit 0)",
                },
            )
        elif result.state == "TIMEOUT":
            log_bus.publish(
                run_id,
                "step.log",
                {"step_id": sid, "ts": _ts(), "lvl": "warn", "text": f"✗ timeout after {timeout}s"},
            )
        else:
            log_bus.publish(
                run_id,
                "step.log",
                {
                    "step_id": sid,
                    "ts": _ts(),
                    "lvl": "err",
                    "text": f"✗ exit {result.exit_code}: {result.err_message or ''}",
                },
            )
        log_bus.publish(
            run_id,
            "step.finished",
            {"step_id": sid, "state": result.state, "elapsed_sec": result.elapsed},
        )
        return result


_ENGINE: RunEngine | None = None


def get_engine() -> RunEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = RunEngine()
    return _ENGINE
