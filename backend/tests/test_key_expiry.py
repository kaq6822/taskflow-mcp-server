from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import KeyCreate
from app.services.keys import find_active_by_plaintext, issue_key


async def test_issue_key_without_expiry_has_no_expires(session):
    key, plaintext = await issue_key(
        session, label="forever", scopes=["read:jobs"], expires_days=None, rate_limit="30/min"
    )
    assert key.expires is None
    found = await find_active_by_plaintext(session, plaintext)
    assert found is not None and found.id == key.id


async def test_issue_key_with_days_sets_expires(session):
    key, _ = await issue_key(
        session, label="temp", scopes=["read:jobs"], expires_days=30, rate_limit="30/min"
    )
    assert key.expires is not None


def test_key_create_accepts_null_and_rejects_non_positive():
    assert KeyCreate(label="a", scopes=[], expires_days=None).expires_days is None
    assert KeyCreate(label="a", scopes=[]).expires_days == 90
    with pytest.raises(ValidationError):
        KeyCreate(label="a", scopes=[], expires_days=0)


def test_key_create_rejects_too_large_days():
    with pytest.raises(ValidationError):
        KeyCreate(label="a", scopes=[], expires_days=3_000_000)
