from __future__ import annotations

from app.services.keys import scope_allows


def test_exact_run_scope_allows_matching_job():
    assert scope_allows(["run:deploy-web"], "run:deploy-web") is True
    assert scope_allows(["run:deploy-web"], "run:other") is False


def test_run_wildcard_allows_any_job():
    assert scope_allows(["run:*"], "run:deploy-web") is True
    assert scope_allows(["run:*"], "run:etl-nightly") is True


def test_read_wildcard_covers_read_scopes():
    assert scope_allows(["read:*"], "read:jobs") is True
    assert scope_allows(["read:*"], "read:runs") is True


def test_read_only_cannot_run():
    assert scope_allows(["read:jobs", "read:runs"], "run:deploy-web") is False


def test_write_exact():
    assert scope_allows(["write:uploads"], "write:uploads") is True
    assert scope_allows(["read:*"], "write:uploads") is False
