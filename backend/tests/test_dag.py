from __future__ import annotations

import pytest

from app.engine.dag import DagValidationError, topo_sort, validate_steps


def test_argv_list_required():
    with pytest.raises(DagValidationError):
        validate_steps([{"id": "a", "cmd": "echo hi", "deps": []}])  # shell-style string
    with pytest.raises(DagValidationError):
        validate_steps([{"id": "a", "cmd": [], "deps": []}])  # empty argv


def test_duplicate_id_rejected():
    with pytest.raises(DagValidationError):
        validate_steps(
            [
                {"id": "a", "cmd": ["echo"], "deps": []},
                {"id": "a", "cmd": ["echo"], "deps": []},
            ]
        )


def test_cycle_rejected():
    with pytest.raises(DagValidationError):
        validate_steps(
            [
                {"id": "a", "cmd": ["echo"], "deps": ["b"]},
                {"id": "b", "cmd": ["echo"], "deps": ["a"]},
            ]
        )


def test_topo_sort_respects_deps():
    steps = [
        {"id": "a", "cmd": ["echo"], "deps": []},
        {"id": "b", "cmd": ["echo"], "deps": ["a"]},
        {"id": "c", "cmd": ["echo"], "deps": ["a", "b"]},
    ]
    validate_steps(steps)
    order = topo_sort(steps)
    assert order.index("a") < order.index("b") < order.index("c")
