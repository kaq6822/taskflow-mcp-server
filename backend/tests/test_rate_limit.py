from __future__ import annotations

from app.services.keys import rate_limit_ok


def test_burst_within_limit_passes():
    for _ in range(10):
        ok, _ = rate_limit_ok("k-burst", "10/min")
        assert ok is True


def test_burst_over_limit_is_denied_with_retry_after():
    for _ in range(10):
        ok, _ = rate_limit_ok("k-over", "10/min")
        assert ok is True
    ok, retry = rate_limit_ok("k-over", "10/min")
    assert ok is False
    assert retry >= 1
