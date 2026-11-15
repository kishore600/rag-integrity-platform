"""The processing manifest is optional.

Many pipelines never record what they did: they read a file, cut it into chunks, embed them and save them. For those teams
there is no manifest table. This connector stands in for it: it has no rows, says so (``available`` is False), and the audit
then compares the source files with the vector index directly, using what every vector already carries (its document id and
the hash of the file it came from).
"""

from __future__ import annotations

from collections.abc import Iterator

from ..models import ChunkRow, ConnectionStatus, ManifestRow, Scope

NOT_CONNECTED = "Not connected. It is optional: with a manifest, RAGGuard can also check what the pipeline claimed against what is indexed."


class NoManifest:
    available = False  # the audit looks at this: "no rows" must not be read as "the pipeline recorded nothing for any document"
    has_chunk_manifest = False
    empty_ids = 0

    def documents(self, scope: Scope | None = None) -> Iterator[ManifestRow]:
        return iter(())

    def chunks(self, scope: Scope | None = None) -> Iterator[ChunkRow]:
        return iter(())

    def health(self) -> ConnectionStatus:
        return ConnectionStatus("Processing manifest", "manifest", True, NOT_CONNECTED, None, {"connected": False, "optional": True})
