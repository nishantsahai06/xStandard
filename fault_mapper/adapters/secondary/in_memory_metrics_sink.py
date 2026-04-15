"""In-memory metrics sink — implements ``MetricsSinkPort``.

Zero-dependency implementation for development, testing, and
lightweight deployments.  Stores all emitted metrics in plain
Python lists for easy assertion in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MetricRecord:
    """A single captured metric event."""

    kind: str          # "increment", "timing", or "gauge"
    name: str
    value: float
    tags: dict[str, str]


class InMemoryMetricsSink:
    """In-memory implementation of ``MetricsSinkPort``.

    All emitted metrics are captured in ``self.records`` for
    test inspection.

    Convenience properties provide filtered views:
    ``counters``, ``timings``, ``gauges``.
    """

    def __init__(self) -> None:
        self.records: list[MetricRecord] = []

    # ── MetricsSinkPort implementation ───────────────────────────

    def increment(
        self,
        name: str,
        value: int = 1,
        tags: dict[str, str] | None = None,
    ) -> None:
        self.records.append(MetricRecord(
            kind="increment",
            name=name,
            value=float(value),
            tags=tags or {},
        ))

    def timing(
        self,
        name: str,
        duration_ms: float,
        tags: dict[str, str] | None = None,
    ) -> None:
        self.records.append(MetricRecord(
            kind="timing",
            name=name,
            value=duration_ms,
            tags=tags or {},
        ))

    def gauge(
        self,
        name: str,
        value: float,
        tags: dict[str, str] | None = None,
    ) -> None:
        self.records.append(MetricRecord(
            kind="gauge",
            name=name,
            value=value,
            tags=tags or {},
        ))

    # ── Test helpers ─────────────────────────────────────────────

    def clear(self) -> None:
        """Remove all captured metrics."""
        self.records.clear()

    @property
    def counters(self) -> list[MetricRecord]:
        """All increment records."""
        return [r for r in self.records if r.kind == "increment"]

    @property
    def timings(self) -> list[MetricRecord]:
        """All timing records."""
        return [r for r in self.records if r.kind == "timing"]

    @property
    def gauges(self) -> list[MetricRecord]:
        """All gauge records."""
        return [r for r in self.records if r.kind == "gauge"]

    def get(self, name: str, kind: str | None = None) -> list[MetricRecord]:
        """Filter records by name and optionally kind."""
        return [
            r for r in self.records
            if r.name == name and (kind is None or r.kind == kind)
        ]
