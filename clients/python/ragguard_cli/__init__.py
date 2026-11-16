"""RAGGuard from the command line and from AI assistants (MCP): check that your RAG index matches your source documents."""

from .client import DEFAULT_URL, RagGuard, RagGuardError

__version__ = "0.1.0"
__all__ = ["DEFAULT_URL", "RagGuard", "RagGuardError", "__version__"]
