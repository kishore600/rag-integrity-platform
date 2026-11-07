"""Build the three connectors for the configured mode."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Settings
from ..demo.world import DemoIndex, DemoManifest, DemoSource, DemoWorld
from .base import IndexConnector, ManifestConnector, SourceConnector


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

    from .postgres import PostgresManifest
    from .qdrant import QdrantIndex
    from .s3 import S3Source

    return Connectors(S3Source(settings), PostgresManifest(settings), QdrantIndex(settings))
