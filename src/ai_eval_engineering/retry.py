"""Explicit retry policy for transient system-adapter failures."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RetryEvent:
    """Describes one failed adapter attempt that will be retried."""

    case_id: str
    failed_attempt: int
    next_attempt: int
    exception_type: str
    delay_seconds: float


RetryCallback = Callable[[RetryEvent], None]


@dataclass(frozen=True)
class RetryPolicy:
    """Opt-in, bounded exponential backoff for selected adapter exceptions.

    max_attempts counts the initial call. The default policy is not applied
    automatically: pass a RetryPolicy to a runner to enable retries.
    Only configured exception classes are eligible; graders and contract
    validation are outside the retry boundary.
    """

    max_attempts: int = 3
    retryable_exceptions: tuple[type[Exception], ...] = (TimeoutError, ConnectionError)
    initial_delay_seconds: float = 0.25
    backoff_factor: float = 2.0
    max_delay_seconds: float = 5.0
    on_retry: RetryCallback | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int):
            raise TypeError("max_attempts must be an integer.")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1.")
        if (
            not isinstance(self.retryable_exceptions, tuple)
            or not self.retryable_exceptions
        ):
            raise ValueError("retryable_exceptions must be a non-empty tuple of exception classes.")
        for exception_type in self.retryable_exceptions:
            if (
                not isinstance(exception_type, type)
                or not issubclass(exception_type, Exception)
            ):
                raise TypeError("retryable_exceptions must contain Exception subclasses.")
        initial = _finite_non_negative(self.initial_delay_seconds, "initial_delay_seconds")
        factor = _finite_number(self.backoff_factor, "backoff_factor")
        maximum = _finite_non_negative(self.max_delay_seconds, "max_delay_seconds")
        if factor < 1.0:
            raise ValueError("backoff_factor must be at least 1.")
        if self.on_retry is not None and not callable(self.on_retry):
            raise TypeError("on_retry must be callable or None.")
        object.__setattr__(self, "initial_delay_seconds", initial)
        object.__setattr__(self, "backoff_factor", factor)
        object.__setattr__(self, "max_delay_seconds", maximum)

    def schedule_retry(
        self,
        case_id: str,
        error: Exception,
        failed_attempt: int,
    ) -> float | None:
        """Notify about and return the delay for a permitted retry.

        Returns None when the exception is not configured for retry or the
        attempt budget is exhausted. Exceptions raised by the callback are
        intentionally propagated; callers must not silently lose audit hooks.
        """
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("case_id must not be empty.")
        if not isinstance(error, Exception):
            raise TypeError("error must be an Exception.")
        if isinstance(failed_attempt, bool) or not isinstance(failed_attempt, int):
            raise TypeError("failed_attempt must be an integer.")
        if failed_attempt < 1:
            raise ValueError("failed_attempt must be at least 1.")
        if failed_attempt >= self.max_attempts:
            return None
        if not isinstance(error, self.retryable_exceptions):
            return None

        delay = self._delay_for_attempt(failed_attempt)
        event = RetryEvent(
            case_id=case_id,
            failed_attempt=failed_attempt,
            next_attempt=failed_attempt + 1,
            exception_type=f"{type(error).__module__}.{type(error).__qualname__}",
            delay_seconds=delay,
        )
        if self.on_retry is not None:
            self.on_retry(event)
        return delay

    def to_dict(self) -> dict[str, object]:
        """Return JSON-compatible settings suitable for run-manifest configuration."""
        return {
            "max_attempts": self.max_attempts,
            "retryable_exceptions": [
                f"{item.__module__}.{item.__qualname__}"
                for item in self.retryable_exceptions
            ],
            "initial_delay_seconds": self.initial_delay_seconds,
            "backoff_factor": self.backoff_factor,
            "max_delay_seconds": self.max_delay_seconds,
        }

    def _delay_for_attempt(self, failed_attempt: int) -> float:
        delay = min(self.initial_delay_seconds, self.max_delay_seconds)
        for _ in range(failed_attempt - 1):
            if delay >= self.max_delay_seconds:
                return self.max_delay_seconds
            delay = min(delay * self.backoff_factor, self.max_delay_seconds)
        return min(delay, self.max_delay_seconds)


def _finite_number(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric.")
    try:
        converted = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be finite.") from exc
    if not math.isfinite(converted):
        raise ValueError(f"{name} must be finite.")
    return converted


def _finite_non_negative(value: float, name: str) -> float:
    converted = _finite_number(value, name)
    if converted < 0:
        raise ValueError(f"{name} must be non-negative.")
    return converted



def validate_retry_policy_manifest(
    configuration: dict[str, object],
    policy: RetryPolicy | None,
) -> None:
    """Ensure retry behavior is represented by the run's recorded configuration."""
    recorded = configuration.get("retry_policy")
    expected = policy.to_dict() if policy is not None else None
    if recorded != expected:
        if policy is None:
            raise ValueError(
                "manifest declares retry_policy but the runner has no retry policy; "
                "remove that configuration or pass the matching RetryPolicy."
            )
        raise ValueError(
            "manifest retry_policy does not match the runner; build metadata with "
            "build_run_metadata(..., retry_policy=policy)."
        )
