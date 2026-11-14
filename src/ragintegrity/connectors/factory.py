"""Build the three connectors for the configured mode."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Settings
from ..demo.world import DemoIndex, DemoManifest, DemoSource, DemoWorld
from .base import ConnectorError, IndexConnector, ManifestConnector, SourceConnector


@dataclass
class Connectors:
    source: SourceConnector
    manifest: ManifestConnector
    index: IndexConnector
    world: DemoWorld | None = None  # only in demo mode


def build_connectors(settings: Settings, world: DemoWorld | None = None) -> Connectors:
    if settings.is_demo:
        world = world or DemoWorld()
        return Connectors(DemoSource(world), DemoManifest(world), DemoIndex(world), world)

    from .nomanifest import NoManifest
    from .pgvector import PgVectorIndex
    from .postgres import PostgresManifest
    from .qdrant import QdrantIndex
    from .s3 import S3Source

    # the manifest is optional: without a manifest database the audit compares the source with the index directly
    manifest = PostgresManifest(settings) if settings.manifest_database_url else NoManifest()
    if (settings.index_type or "qdrant").lower() not in ("qdrant", "pgvector"):
        raise ConnectorError(f"RAGI_INDEX_TYPE must be qdrant or pgvector, not {settings.index_type!r}")
    index = PgVectorIndex(settings) if settings.uses_pgvector else QdrantIndex(settings)
    return Connectors(S3Source(settings), manifest, index)
