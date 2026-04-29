from __future__ import annotations

from typing import Iterable


class DagValidationError(ValueError):
    pass


def validate_steps(steps: Iterable[dict]) -> list[dict]:
    """Validate step list: unique ids, argv list only (no shell strings), DAG acyclic.

    Returns steps unchanged on success; raises DagValidationError on any violation.
    """
    steps = list(steps)
    ids: list[str] = []
    for s in steps:
        sid = s.get("id")
        if not sid or not isinstance(sid, str):
            raise DagValidationError("step.id must be a non-empty string")
        if sid in ids:
            raise DagValidationError(f"duplicate step id: {sid}")
        ids.append(sid)
        cmd = s.get("cmd")
        if not isinstance(cmd, list) or not cmd or not all(isinstance(c, str) for c in cmd):
            raise DagValidationError(
                f"step {sid}: cmd must be a non-empty list of strings (argv only, shell=False)"
            )
        deps = s.get("deps", [])
        if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
            raise DagValidationError(f"step {sid}: deps must be a list of strings")
        cwd = s.get("cwd")
        if cwd is not None and (not isinstance(cwd, str) or not cwd.strip()):
            raise DagValidationError(f"step {sid}: cwd must be a non-empty string")
        for d in deps:
            if d not in ids and d not in [s2.get("id") for s2 in steps]:
                raise DagValidationError(f"step {sid}: depends on unknown step '{d}'")

    # Cycle detection via DFS
    by_id = {s["id"]: s for s in steps}
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {sid: WHITE for sid in by_id}

    def visit(sid: str, stack: list[str]) -> None:
        if color[sid] == GRAY:
            cycle = " → ".join(stack[stack.index(sid) :] + [sid])
            raise DagValidationError(f"cycle detected: {cycle}")
        if color[sid] == BLACK:
            return
        color[sid] = GRAY
        stack.append(sid)
        for d in by_id[sid].get("deps", []):
            visit(d, stack)
        stack.pop()
        color[sid] = BLACK

    for sid in by_id:
        visit(sid, [])

    return steps


def topo_sort(steps: list[dict]) -> list[str]:
    """Return ids in topological order. Assumes steps already validated."""
    by_id = {s["id"]: s for s in steps}
    order: list[str] = []
    seen: set[str] = set()

    def visit(sid: str) -> None:
        if sid in seen:
            return
        seen.add(sid)
        for d in by_id[sid].get("deps", []):
            visit(d)
        order.append(sid)

    for s in steps:
        visit(s["id"])
    return order
