"""Fake mapping review policy — test double for ``MappingReviewPolicyPort``.

Returns a configurable ``ReviewStatus``.  Tracks calls for assertions.
"""

from __future__ import annotations

from typing import Any

from fault_mapper.domain.enums import ReviewStatus
from fault_mapper.domain.value_objects import MappingTrace


class FakeMappingReviewPolicy:
    """Configurable fake implementing ``MappingReviewPolicyPort``."""

    def __init__(
        self,
        status: ReviewStatus = ReviewStatus.APPROVED,
    ) -> None:
        self.status = status
        self.calls: list[Any] = []

    def determine_initial_review_status(
        self,
        trace: MappingTrace,
    ) -> ReviewStatus:
        self.calls.append(trace)
        return self.status
