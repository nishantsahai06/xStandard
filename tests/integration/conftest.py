"""Integration-test fixtures — real MongoDB via testcontainers.

Provides a session-scoped MongoDB container and per-test repository
instances with clean collections.

Skip behaviour
──────────────
All tests in this directory are automatically skipped when:
  • ``pymongo`` is not installed, OR
  • ``testcontainers`` is not installed, OR
  • the Docker daemon is not reachable.

This makes ``pytest`` safe to run everywhere — CI boxes without
Docker simply skip the integration suite.
"""

from __future__ import annotations

import pytest

# ── Guard: skip entire module if dependencies are missing ────────
pymongo = pytest.importorskip("pymongo", reason="pymongo not installed")
tc_mongo = pytest.importorskip(
    "testcontainers.mongodb",
    reason="testcontainers[mongo] not installed",
)

from pymongo import MongoClient  # noqa: E402
from pymongo.errors import ConnectionFailure  # noqa: E402
from testcontainers.mongodb import MongoDbContainer  # noqa: E402

from fault_mapper.adapters.secondary.mongodb_repository import (  # noqa: E402
    MongoDBFaultModuleRepository,
)
from fault_mapper.application.fault_module_persistence_service import (  # noqa: E402
    FaultModulePersistenceService,
)
from fault_mapper.application.fault_module_review_service import (  # noqa: E402
    FaultModuleReviewService,
)
from fault_mapper.infrastructure.config import MongoConfig  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════
#  DOCKER-AVAILABILITY CHECK
# ═══════════════════════════════════════════════════════════════════════


def _docker_is_available() -> bool:
    """Return True if the Docker daemon is reachable."""
    try:
        import docker  # type: ignore[import-untyped]

        client = docker.from_env()
        client.ping()
        return True
    except Exception:  # noqa: BLE001
        return False


_SKIP_REASON = "Docker daemon not reachable — skipping MongoDB integration tests"


# ═══════════════════════════════════════════════════════════════════════
#  SESSION-SCOPED MONGO CONTAINER
# ═══════════════════════════════════════════════════════════════════════

# Use a lightweight Mongo image; 7.0 is well-tested.
_MONGO_IMAGE = "mongo:7.0"
_TEST_DB_NAME = "fault_mapper_integration_test"
_TRUSTED_COLLECTION = "test_trusted"
_REVIEW_COLLECTION = "test_review"


@pytest.fixture(scope="session")
def mongo_container():
    """Start a real MongoDB container once per test session.

    Yields the running ``MongoDbContainer`` so tests can derive
    connection parameters.  Stopped and removed automatically at
    session teardown.

    Skips the entire session when Docker is not reachable (the skip
    propagates to every dependent fixture / test).
    """
    if not _docker_is_available():
        pytest.skip(_SKIP_REASON)

    container = MongoDbContainer(image=_MONGO_IMAGE)
    container.start()
    yield container
    container.stop()


@pytest.fixture(scope="session")
def mongo_client(mongo_container) -> MongoClient:
    """Session-scoped ``MongoClient`` connected to the container."""
    uri = mongo_container.get_connection_url()
    client = MongoClient(uri)
    # Smoke-test connectivity
    client.admin.command("ping")
    return client


@pytest.fixture(scope="session")
def mongo_config(mongo_container) -> MongoConfig:
    """Session-scoped ``MongoConfig`` pointing at the container DB."""
    return MongoConfig(
        connection_uri=mongo_container.get_connection_url(),
        database_name=_TEST_DB_NAME,
        trusted_collection=_TRUSTED_COLLECTION,
        review_collection=_REVIEW_COLLECTION,
    )


# ═══════════════════════════════════════════════════════════════════════
#  PER-TEST FIXTURES — clean state each time
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture()
def mongo_repo(
    mongo_config: MongoConfig,
    mongo_client: MongoClient,
) -> MongoDBFaultModuleRepository:
    """Per-test repository backed by the real container.

    Drops both collections before AND after the test to ensure
    complete isolation regardless of pass/fail.
    """
    db = mongo_client[mongo_config.database_name]
    db[mongo_config.trusted_collection].drop()
    db[mongo_config.review_collection].drop()

    repo = MongoDBFaultModuleRepository(
        config=mongo_config,
        client=mongo_client,
    )

    yield repo

    # Teardown — clean up even if test failed
    db[mongo_config.trusted_collection].drop()
    db[mongo_config.review_collection].drop()


@pytest.fixture()
def persistence_svc(
    mongo_repo: MongoDBFaultModuleRepository,
) -> FaultModulePersistenceService:
    """Per-test persistence service wired to the real Mongo repo."""
    return FaultModulePersistenceService(repository=mongo_repo)


@pytest.fixture()
def review_svc(
    mongo_repo: MongoDBFaultModuleRepository,
) -> FaultModuleReviewService:
    """Per-test review service wired to the real Mongo repo."""
    return FaultModuleReviewService(repository=mongo_repo)
