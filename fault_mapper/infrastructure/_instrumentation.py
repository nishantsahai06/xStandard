"""Shared instrumentation helper for factory wiring.

This helper removes copy-paste boilerplate around the
``if metrics_sink is not None: return Wrapper(inner=..., metrics=...)``
idiom that appears for every service wired by the DI factories.
"""

from __future__ import annotations

from typing import Callable, TypeVar

from fault_mapper.domain.ports import MetricsSinkPort

T = TypeVar("T")


def wrap_with_metrics(
    inner: T,
    metrics_sink: MetricsSinkPort | None,
    wrapper_cls: Callable[..., T],
) -> T:
    """Return ``inner`` decorated with ``wrapper_cls`` when metrics are enabled.

    When ``metrics_sink`` is ``None``, returns ``inner`` unchanged —
    the factory stays zero-overhead for tests and local dev that don't
    care about metrics.

    The wrapper class must accept ``inner`` and ``metrics`` keyword
    arguments; this is the uniform decorator shape used by every
    ``Instrumented*`` wrapper in ``adapters/secondary``.
    """
    if metrics_sink is None:
        return inner
    return wrapper_cls(inner=inner, metrics=metrics_sink)
