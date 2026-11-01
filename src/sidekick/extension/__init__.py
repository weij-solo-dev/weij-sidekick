"""sidekick.extension — manifests, loader, registry, lifecycle and the registration bridge."""

from .extension import ExtensionSession, validate_settings
from .loader import discover, import_file, load_factory, read_manifest, read_skill
from .registry import ExtensionRegistry
from .schemas import (
    ExtensionContext,
    ExtensionManifest,
    ExtensionMCPServer,
    ExtensionRecord,
    ExtensionSubagent,
)

__all__ = [
    "ExtensionContext",
    "ExtensionMCPServer",
    "ExtensionManifest",
    "ExtensionRecord",
    "ExtensionRegistry",
    "ExtensionSession",
    "ExtensionSubagent",
    "discover",
    "import_file",
    "load_factory",
    "read_manifest",
    "read_skill",
    "validate_settings",
]
