"""In-memory sliding-window rate limiter."""
import time
from collections import defaultdict
from typing import Dict


class RateLimiter:
    """In-memory sliding-window rate limiter keyed by source."""

    def __init__(self, requests_per_minute: int):
        self.requests_per_minute = requests_per_minute
        self.requests: Dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, source: str) -> bool:
        """Check if request from source is allowed under rate limit."""
        now = time.time()
        window_start = now - 60  # 60 seconds sliding window

        # Remove expired timestamps
        self.requests[source] = [
            ts for ts in self.requests[source] if ts > window_start
        ]

        # Check if under limit
        if len(self.requests[source]) >= self.requests_per_minute:
            return False

        # Record this request
        self.requests[source].append(now)
        return True
