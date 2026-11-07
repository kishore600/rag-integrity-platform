from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ragintegrity.demo.world import TARGET_FP, DemoIndex, DemoManifest, DemoSource, DemoWorld
from ragintegrity.engine.audit import AuditOptions

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def world() -> DemoWorld:
    return DemoWorld(seed=11, docs_per_tenant=60, now=NOW)


@pytest.fixture()
def connectors(world):
    return DemoSource(world), DemoManifest(world), DemoIndex(world)


@pytest.fixture()
def opts() -> AuditOptions:
    return AuditOptions(target=TARGET_FP, check_vectors=True, probe=True, now=NOW, grace_minutes=10)
