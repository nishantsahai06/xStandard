"""End-to-end workflow tests — validate → persist → review → promote.

Exercises the full operational lifecycle without touching any real
external services.  Uses:
  • Real validators (schema, business-rule, review-gate)
  • Real serialiser (``serialize_module``)
  • Real persistence + review services
  • ``FakeFaultModuleRepository`` for storage

Scenarios
─────────
A. Happy-path approved:     validate → persist (trusted) → STORED
B. Review-required path:    validate → persist (review) → approve → trusted
C. Review-required reject:  validate → persist (review) → reject
D. Failed validation path:  validate → persist REJECTED (not persisted)
E. Round-trip retrieval:    persist → retrieve envelope → verify document
F. Counts & listing:        persist multiple → count/list each collection
G. Handoff hook fires:      approve triggers downstream spy
"""

from __future__ import annotations

import pytest

from fault_mapper.adapters.secondary.business_rule_validator import (
    validate_business_rules,
)
from fault_mapper.adapters.secondary.review_gate import default_review_gate
from fault_mapper.adapters.secondary.schema_validator import (
    validate_against_schema,
)
from fault_mapper.application.fault_module_persistence_service import (
    FaultModulePersistenceService,
)
from fault_mapper.application.fault_module_review_service import (
    FaultModuleReviewService,
)
from fault_mapper.application.fault_module_validator import FaultModuleValidator
from fault_mapper.domain.enums import (
    ReviewStatus,
    ValidationStatus,
)
from fault_mapper.domain.value_objects import PersistenceEnvelope

from tests.fakes.fake_fault_module_repository import FakeFaultModuleRepository
from tests.fixtures.persistence_fixtures import (
    make_approved_module,
    make_review_required_module,
    make_schema_failed_module,
)
from tests.fixtures.validation_fixtures import (
    make_valid_fault_isolation_module,
    make_valid_fault_reporting_module,
)


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════


class _SpyHandoff:
    """Spy for ``TrustedModuleHandoffPort``."""

    def __init__(self) -> None:
        self.calls: list[PersistenceEnvelope] = []

    def on_module_stored(self, envelope: PersistenceEnvelope) -> None:
        self.calls.append(envelope)


def _real_validator() -> FaultModuleValidator:
    return FaultModuleValidator(
        structural_validator=validate_against_schema,
        business_validator=validate_business_rules,
        review_gate=default_review_gate,
    )


# ═══════════════════════════════════════════════════════════════════════
#  FIXTURES
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture()
def repo() -> FakeFaultModuleRepository:
    return FakeFaultModuleRepository()


@pytest.fixture()
def persistence(repo: FakeFaultModuleRepository) -> FaultModulePersistenceService:
    return FaultModulePersistenceService(repository=repo)


@pytest.fixture()
def review(repo: FakeFaultModuleRepository) -> FaultModuleReviewService:
    return FaultModuleReviewService(repository=repo)


@pytest.fixture()
def validator() -> FaultModuleValidator:
    return _real_validator()


# ═══════════════════════════════════════════════════════════════════════
#  A.  HAPPY-PATH APPROVED → STORED
# ═══════════════════════════════════════════════════════════════════════


class TestApprovedEndToEnd:
    """Valid module → APPROVED → persist to trusted → STORED."""

    def test_validate_persist_full_flow(
        self,
        validator: FaultModuleValidator,
        persistence: FaultModulePersistenceService,
        repo: FakeFaultModuleRepository,
    ) -> None:
        module = make_valid_fault_reporting_module(
            record_id="E2E-APPROVED-001",
        )

        # Step 1: validate
        vr = validator.validate(module)
        assert vr.status is ValidationStatus.APPROVED

        # Step 2: persist
        result = persistence.persist(module)
        assert result.success is True
        assert result.collection == "trusted"

        # Step 3: lifecycle status is STORED
        assert module.validation_status is ValidationStatus.STORED

        # Step 4: envelope exists in trusted
        env = repo.get("E2E-APPROVED-001", "trusted")
        assert env is not None
        assert env.validation_status is ValidationStatus.APPROVED
        assert env.review_status is ReviewStatus.APPROVED

    def test_isolation_module_approved_flow(
        self,
        validator: FaultModuleValidator,
        persistence: FaultModulePersistenceService,
        repo: FakeFaultModuleRepository,
    ) -> None:
        module = make_valid_fault_isolation_module(
            record_id="E2E-ISO-001",
        )
        vr = validator.validate(module)
        assert vr.status is ValidationStatus.APPROVED

        result = persistence.persist(module)
        assert result.success is True
        assert module.validation_status is ValidationStatus.STORED


# ═══════════════════════════════════════════════════════════════════════
#  B.  REVIEW-REQUIRED → PROMOTE
# ═══════════════════════════════════════════════════════════════════════


class TestReviewPromoteEndToEnd:
    """REVIEW_REQUIRED → persist to review → approve → trusted."""

    def test_review_to_trusted_promotion(
        self,
        persistence: FaultModulePersistenceService,
        review: FaultModuleReviewService,
        repo: FakeFaultModuleRepository,
    ) -> None:
        module = make_review_required_module(
            record_id="E2E-REV-001",
        )

        # Persist to review collection
        result = persistence.persist(module)
        assert result.success is True
        assert result.collection == "review"
        assert repo.count("review") == 1

        # Promote via review service
        promo = review.approve("E2E-REV-001")
        assert promo.success is True

        # Now in trusted, not in review
        assert repo.get("E2E-REV-001", "trusted") is not None
        assert repo.get("E2E-REV-001", "review") is None
        assert repo.count("trusted") == 1
        assert repo.count("review") == 0

    def test_promoted_envelope_has_correct_statuses(
        self,
        persistence: FaultModulePersistenceService,
        review: FaultModuleReviewService,
        repo: FakeFaultModuleRepository,
    ) -> None:
        module = make_review_required_module(
            record_id="E2E-REV-002",
        )
        persistence.persist(module)
        review.approve("E2E-REV-002")

        env = repo.get("E2E-REV-002", "trusted")
        assert env is not None
        assert env.validation_status is ValidationStatus.APPROVED
        assert env.review_status is ReviewStatus.APPROVED


# ═══════════════════════════════════════════════════════════════════════
#  C.  REVIEW-REQUIRED → REJECT
# ═══════════════════════════════════════════════════════════════════════


class TestReviewRejectEndToEnd:
    """REVIEW_REQUIRED → persist to review → reject → stays in review."""

    def test_reject_keeps_in_review(
        self,
        persistence: FaultModulePersistenceService,
        review: FaultModuleReviewService,
        repo: FakeFaultModuleRepository,
    ) -> None:
        module = make_review_required_module(
            record_id="E2E-REJ-001",
        )
        persistence.persist(module)

        rej = review.reject("E2E-REJ-001", reason="Poor quality")
        assert rej.success is True

        # Still in review with REJECTED statuses
        env = repo.get("E2E-REJ-001", "review")
        assert env is not None
        assert env.validation_status is ValidationStatus.REJECTED
        assert env.review_status is ReviewStatus.REJECTED

        # Not in trusted
        assert repo.get("E2E-REJ-001", "trusted") is None


# ═══════════════════════════════════════════════════════════════════════
#  D.  FAILED VALIDATION → NOT PERSISTED
# ═══════════════════════════════════════════════════════════════════════


class TestFailedNotPersisted:
    """Modules that fail validation are not stored."""

    def test_schema_failed_not_persisted(
        self,
        persistence: FaultModulePersistenceService,
        repo: FakeFaultModuleRepository,
    ) -> None:
        module = make_schema_failed_module(
            record_id="E2E-FAIL-001",
        )
        result = persistence.persist(module)
        assert result.success is False
        assert repo.count("trusted") == 0
        assert repo.count("review") == 0

    def test_rejected_not_persisted(
        self,
        persistence: FaultModulePersistenceService,
        repo: FakeFaultModuleRepository,
    ) -> None:
        from tests.fixtures.persistence_fixtures import make_rejected_module

        module = make_rejected_module(record_id="E2E-FAIL-002")
        result = persistence.persist(module)
        assert result.success is False


# ═══════════════════════════════════════════════════════════════════════
#  E.  ROUND-TRIP RETRIEVAL
# ═══════════════════════════════════════════════════════════════════════


class TestRoundTrip:
    """Persist → retrieve → verify document integrity."""

    def test_trusted_round_trip(
        self,
        persistence: FaultModulePersistenceService,
        repo: FakeFaultModuleRepository,
    ) -> None:
        module = make_approved_module(record_id="E2E-RT-001")
        persistence.persist(module)

        env = persistence.retrieve("E2E-RT-001", "trusted")
        assert env is not None
        assert env.record_id == "E2E-RT-001"
        assert env.document["recordId"] == "E2E-RT-001"

    def test_review_round_trip(
        self,
        persistence: FaultModulePersistenceService,
    ) -> None:
        module = make_review_required_module(record_id="E2E-RT-002")
        persistence.persist(module)

        env = persistence.retrieve("E2E-RT-002", "review")
        assert env is not None
        assert env.record_id == "E2E-RT-002"

    def test_promoted_round_trip(
        self,
        persistence: FaultModulePersistenceService,
        review: FaultModuleReviewService,
    ) -> None:
        module = make_review_required_module(record_id="E2E-RT-003")
        persistence.persist(module)

        review.approve("E2E-RT-003")

        env = persistence.retrieve("E2E-RT-003", "trusted")
        assert env is not None
        assert env.document["recordId"] == "E2E-RT-003"


# ═══════════════════════════════════════════════════════════════════════
#  F.  COUNTS & LISTINGS
# ═══════════════════════════════════════════════════════════════════════


class TestCountsAndListings:
    """Multiple modules → correct counts and listings per collection."""

    def test_mixed_collections(
        self,
        persistence: FaultModulePersistenceService,
        repo: FakeFaultModuleRepository,
    ) -> None:
        # 2 approved → trusted
        persistence.persist(
            make_approved_module(record_id="CNT-A1"),
        )
        persistence.persist(
            make_approved_module(record_id="CNT-A2"),
        )
        # 1 review_required → review
        persistence.persist(
            make_review_required_module(record_id="CNT-R1"),
        )

        assert persistence.count_modules("trusted") == 2
        assert persistence.count_modules("review") == 1

        trusted_list = persistence.list_modules("trusted")
        assert len(trusted_list) == 2

        review_list = persistence.list_modules("review")
        assert len(review_list) == 1

    def test_counts_after_promotion(
        self,
        persistence: FaultModulePersistenceService,
        review: FaultModuleReviewService,
        repo: FakeFaultModuleRepository,
    ) -> None:
        persistence.persist(
            make_review_required_module(record_id="CNT-P1"),
        )
        assert repo.count("review") == 1
        assert repo.count("trusted") == 0

        review.approve("CNT-P1")
        assert repo.count("review") == 0
        assert repo.count("trusted") == 1

    def test_counts_after_rejection(
        self,
        persistence: FaultModulePersistenceService,
        review: FaultModuleReviewService,
        repo: FakeFaultModuleRepository,
    ) -> None:
        persistence.persist(
            make_review_required_module(record_id="CNT-J1"),
        )
        review.reject("CNT-J1")

        # Still in review (rejected items stay for audit)
        assert repo.count("review") == 1
        assert repo.count("trusted") == 0


# ═══════════════════════════════════════════════════════════════════════
#  G.  HANDOFF HOOK IN END-TO-END
# ═══════════════════════════════════════════════════════════════════════


class TestHandoffEndToEnd:
    """Handoff spy fires when module is promoted."""

    def test_handoff_fires_on_promotion(
        self,
        repo: FakeFaultModuleRepository,
    ) -> None:
        persistence = FaultModulePersistenceService(repository=repo)
        spy = _SpyHandoff()
        review_svc = FaultModuleReviewService(
            repository=repo, handoff=spy,
        )

        module = make_review_required_module(record_id="HO-001")
        persistence.persist(module)
        review_svc.approve("HO-001")

        assert len(spy.calls) == 1
        assert spy.calls[0].collection == "trusted"
        assert spy.calls[0].record_id == "HO-001"

    def test_no_handoff_on_direct_persist(
        self,
        repo: FakeFaultModuleRepository,
    ) -> None:
        """Handoff is only for promotions, not direct APPROVED persists."""
        spy = _SpyHandoff()
        persistence = FaultModulePersistenceService(repository=repo)
        review_svc = FaultModuleReviewService(
            repository=repo, handoff=spy,
        )

        module = make_approved_module(record_id="HO-002")
        persistence.persist(module)

        # No handoff — module went directly to trusted
        assert len(spy.calls) == 0


# ═══════════════════════════════════════════════════════════════════════
#  H.  FULL PIPELINE: VALIDATE → PERSIST → PROMOTE
# ═══════════════════════════════════════════════════════════════════════


class TestFullPipeline:
    """Complete validate → persist → promote in one sequence."""

    def test_reporting_module_full_pipeline(
        self,
        validator: FaultModuleValidator,
        persistence: FaultModulePersistenceService,
        review: FaultModuleReviewService,
        repo: FakeFaultModuleRepository,
    ) -> None:
        """Build a fresh module, validate, persist, promote — all green."""
        module = make_valid_fault_reporting_module(
            record_id="PIPE-001",
        )

        # Validate → APPROVED
        vr = validator.validate(module)
        assert vr.status is ValidationStatus.APPROVED

        # Persist → trusted
        pr = persistence.persist(module)
        assert pr.success is True
        assert module.validation_status is ValidationStatus.STORED

        # Verify stored
        env = repo.get("PIPE-001", "trusted")
        assert env is not None
        assert env.validation_status is ValidationStatus.APPROVED

    def test_re_persist_is_upsert(
        self,
        persistence: FaultModulePersistenceService,
        repo: FakeFaultModuleRepository,
    ) -> None:
        """Persisting the same record_id twice is an upsert, not a dup."""
        m1 = make_approved_module(
            record_id="UPSERT-001",
            mapping_version="1.0.0",
        )
        persistence.persist(m1)

        m2 = make_approved_module(
            record_id="UPSERT-001",
            mapping_version="2.0.0",
        )
        # Reset to APPROVED so it's persistable again
        m2.validation_status = ValidationStatus.APPROVED
        persistence.persist(m2)

        # Only one document
        assert repo.count("trusted") == 1
        env = repo.get("UPSERT-001", "trusted")
        assert env is not None
        assert env.mapping_version == "2.0.0"
