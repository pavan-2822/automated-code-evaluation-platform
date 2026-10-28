"""Failure classification for failed CI runs.

IMPORTANT HONESTY NOTE: the six modes below are *this repository's
own design*. They are not the original company's failure modes, which
this project does not know or reproduce. Each mode is defined here by
its detection signals and its bounded recovery action, and the tests
in ``tests/test_healer.py`` check exactly these definitions.

Precedence: modes are checked in the order listed. The first mode whose
signals match wins. If no mode matches, the result is ``UNKNOWN`` and
the healer must NOT retry -- an unknown failure stays visible for a
human instead of being retried into silence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class FailureMode:
    """One classified failure mode."""

    slug: str
    name: str
    description: str
    patterns: tuple = ()
    conclusions: tuple = ()
    recovery_action: str = ""
    retryable: bool = True

    def matches(self, log_text, conclusion=None):
        """True when a log pattern or a job conclusion matches."""
        if conclusion and conclusion in self.conclusions:
            return True
        for pattern in self.patterns:
            if re.search(pattern, log_text or "", re.IGNORECASE):
                return True
        return False


UNKNOWN = FailureMode(
    slug="unknown",
    name="Unknown failure",
    description="No defined failure mode matched. Do not retry.",
    recovery_action="none -- leave visible for manual investigation",
    retryable=False,
)

# The six modes defined by this repository, in precedence order.
FAILURE_MODES = (
    FailureMode(
        slug="disk-quota",
        name="Runner disk quota / no space left",
        description="The runner ran out of disk, so builds or image pulls fail.",
        patterns=(
            r"no space left on device",
            r"disk quota exceeded",
            r"\bENOSPC\b",
            r"no space left",
        ),
        recovery_action="prune Docker images/caches, then rerun failed jobs",
    ),
    FailureMode(
        slug="dependency-network",
        name="Transient dependency-install network failure",
        description="Package installation failed on a transient network error.",
        patterns=(
            r"temporary failure in name resolution",
            r"could not fetch",
            r"failed to fetch",
            r"connection (timed out|reset) .* (pip|npm|apt)",
            r"network is unreachable",
        ),
        recovery_action="rerun failed jobs (no code change)",
    ),
    FailureMode(
        slug="docker-pull",
        name="Docker pull rate-limit / timeout",
        description="Pulling a container image hit a registry rate limit or timed out.",
        patterns=(
            r"toomanyrequests",
            r"rate limit.*pull",
            r"docker.*pull.*timed out",
            r"pull access denied.*rate",
            r"manifest.*rate limit",
        ),
        recovery_action="wait for backoff, then rerun failed jobs",
    ),
    FailureMode(
        slug="runner-lost",
        name="Runner lost communication",
        description="The runner stopped communicating with the CI service.",
        patterns=(
            r"lost communication with the server",
            r"runner.*lost communication",
            r"runner has received a shutdown signal",
            r"the runner has unexpectedly disconnected",
        ),
        conclusions=("cancelled",),
        recovery_action="rerun failed jobs on a fresh runner",
    ),
    FailureMode(
        slug="cache-corruption",
        name="Cache corruption / restore failure",
        description="A restored cache was corrupt or could not be restored.",
        patterns=(
            r"cache.*corrupt",
            r"failed to restore.*cache",
            r"cache restore failed",
            r"checksum mismatch.*cache",
        ),
        recovery_action="clear the cache key, then rerun failed jobs",
    ),
    FailureMode(
        slug="service-startup-timeout",
        name="Dependent-service startup timeout",
        description="A dependent service did not become healthy in time.",
        patterns=(
            r"timed out waiting.*service",
            r"service.*did not become healthy",
            r"health check.*timed out",
            r"waiting for .* to be ready.*timed out",
        ),
        recovery_action="increase service startup wait, then rerun failed jobs",
    ),
)


def classify(log_text, conclusion=None):
    """Classify a failed job. Returns a FailureMode (or UNKNOWN)."""
    for mode in FAILURE_MODES:
        if mode.matches(log_text, conclusion):
            return mode
    return UNKNOWN


def classify_job(job):
    """Classify one job dict with ``log`` and ``conclusion`` keys."""
    return classify(job.get("log", ""), job.get("conclusion"))
