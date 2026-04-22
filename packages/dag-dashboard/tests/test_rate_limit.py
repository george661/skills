"""Tests for rate limiter extraction and back-compat."""
import pytest


def test_rate_limiter_extracted_module():
    """Test 1: RateLimiter can be imported from dag_dashboard.rate_limit.
    
    Also verifies back-compat: import from dag_dashboard.trigger still works.
    """
    # Import from new location
    from dag_dashboard.rate_limit import RateLimiter
    
    limiter = RateLimiter(requests_per_minute=30)
    assert limiter.is_allowed("test_source")
    
    # Back-compat: import from old location still works
    from dag_dashboard.trigger import RateLimiter as TriggerRateLimiter
    
    limiter2 = TriggerRateLimiter(requests_per_minute=30)
    assert limiter2.is_allowed("test_source")
