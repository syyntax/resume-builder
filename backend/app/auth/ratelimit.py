"""In-process rate limiting. One instance serves the deployment (DESIGN.md §8.4), so memory is enough."""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

Clock = Callable[[], float]
_MAX_KEYS = 50_000


class SlidingWindow:
    """At most ``limit`` events per ``window`` seconds for each key."""

    def __init__(self, limit: int, window: float, clock: Clock = time.monotonic) -> None:
        self.limit, self.window, self._clock = limit, window, clock
        self._events: dict[str, deque[float]] = {}

    def _prune(self, key: str, now: float) -> deque[float]:
        events = self._events.setdefault(key, deque())
        while events and events[0] <= now - self.window:
            events.popleft()
        return events

    def count(self, key: str) -> int:
        return len(self._prune(key, self._clock()))

    def hit(self, key: str) -> None:
        now = self._clock()
        self._prune(key, now).append(now)
        self._gc(now)

    def allow(self, key: str) -> bool:
        """Record an attempt if under the limit; return False (and record nothing) if over it."""
        now = self._clock()
        events = self._prune(key, now)
        if len(events) >= self.limit:
            return False
        events.append(now)
        self._gc(now)
        return True

    def retry_after(self, key: str) -> int:
        now = self._clock()
        events = self._prune(key, now)
        if len(events) < self.limit:
            return 0
        return max(1, math.ceil(events[0] + self.window - now))

    def _gc(self, now: float) -> None:
        if len(self._events) > _MAX_KEYS:
            for key in [k for k, v in self._events.items() if not v or v[-1] <= now - self.window]:
                del self._events[key]


@dataclass
class _Failures:
    count: int = 0
    locked_until: float = 0.0
    last: float = 0.0


class FailureBackoff:
    """Exponential backoff after ``free`` consecutive failures: 1 s, 2 s, 4 s … capped at ``max_delay``.

    There is no permanent lockout, so an attacker can't lock a real user out of their account."""

    def __init__(self, free: int = 5, max_delay: float = 900.0, clock: Clock = time.monotonic) -> None:
        self.free, self.max_delay, self._clock = free, max_delay, clock
        self._state: dict[str, _Failures] = {}

    def retry_after(self, key: str) -> int:
        state = self._state.get(key)
        if state is None:
            return 0
        remaining = state.locked_until - self._clock()
        return math.ceil(remaining) if remaining > 0 else 0

    def failure(self, key: str) -> None:
        now = self._clock()
        state = self._state.setdefault(key, _Failures())
        if now - state.last > 24 * 3600:  # forget stale streaks
            state.count = 0
        state.count += 1
        state.last = now
        if state.count >= self.free:
            delay = min(2.0 ** (state.count - self.free), self.max_delay)
            state.locked_until = now + delay
        if len(self._state) > _MAX_KEYS:
            for stale in [k for k, v in self._state.items() if now - v.last > 24 * 3600]:
                del self._state[stale]

    def reset(self, key: str) -> None:
        self._state.pop(key, None)


@dataclass
class Limits:
    login_ip: SlidingWindow = field(default_factory=lambda: SlidingWindow(30, 15 * 60))
    login_account: FailureBackoff = field(default_factory=FailureBackoff)
    password_check: FailureBackoff = field(default_factory=FailureBackoff)
    register_ip: SlidingWindow = field(default_factory=lambda: SlidingWindow(10, 60 * 60))
    setup_ip: SlidingWindow = field(default_factory=lambda: SlidingWindow(10, 15 * 60))
    token_ip: SlidingWindow = field(default_factory=lambda: SlidingWindow(30, 15 * 60))
    mfa_account: FailureBackoff = field(default_factory=FailureBackoff)
    mfa_ip: SlidingWindow = field(default_factory=lambda: SlidingWindow(30, 15 * 60))
    email_ip: SlidingWindow = field(default_factory=lambda: SlidingWindow(10, 60 * 60))  # forgot password, resend
