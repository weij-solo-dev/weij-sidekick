"""sidekick.extension.loader — read manifests and import an extension's Python files

Overview
    Finds `extension.json` in a directory, validates it, and imports `tools.py` / `watchers.py`
    as isolated modules named `sidekick_ext_<name>_<file>` so two extensions never collide.
    The module must expose `TOOLS(ctx) -> list[Tool]` or `WATCHERS(ctx) -> list[Watcher]`.
Design
    `importlib.util.spec_from_file_location`; a failed import is reported as an error on the
    record instead of crashing the process. Skill documents are read as text.
Depends on
    sidekick.log, pydantic (through schemas).

See Also
--------
    AGENTS.md "Extensions".

"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sidekick.log import Log

from .schemas import ExtensionContext, ExtensionManifest

MANIFEST_NAME = "extension.json"


def read_manifest(directory: Path) -> ExtensionManifest:
    """Validate `<dir>/extension.json`."""
    path = directory / MANIFEST_NAME
    data = json.loads(path.read_text(encoding="utf-8"))
    manifest = ExtensionManifest.model_validate(data)
    if manifest.tools and not (directory / manifest.tools).exists():
        raise FileNotFoundError(f"{manifest.name}: tools file {manifest.tools} missing")
    if manifest.watchers and not (directory / manifest.watchers).exists():
        raise FileNotFoundError(f"{manifest.name}: watchers file {manifest.watchers} missing")
    for skill in manifest.skills:
        if not (directory / skill).exists():
            raise FileNotFoundError(f"{manifest.name}: skill file {skill} missing")
    return manifest


def discover(directory: Path) -> dict[str, tuple[Path, ExtensionManifest]]:
    """Every valid extension directory under `directory`."""
    found: dict[str, tuple[Path, ExtensionManifest]] = {}
    if not directory.exists():
        return found
    for child in sorted(directory.iterdir()):
        if not child.is_dir() or not (child / MANIFEST_NAME).exists():
            continue
        try:
            manifest = read_manifest(child)
        except Exception as exc:
            Log.warning(f"extension at {child}: invalid manifest: {exc!r}")
            continue
        found[manifest.name] = (child, manifest)
    return found


def _package(directory: Path, extension_name: str) -> str:
    """Register the extension directory as a namespace package so relative imports work."""
    package_name = f"sidekick_ext_{extension_name}"
    package = sys.modules.get(package_name)
    if package is None or getattr(package, "__path__", None) != [str(directory)]:
        package = types.ModuleType(package_name)
        package.__path__ = [str(directory)]
        package.__package__ = package_name
        sys.modules[package_name] = package
    return package_name


def import_file(directory: Path, filename: str, extension_name: str) -> Any:
    """Import `<dir>/<filename>` as `sidekick_ext_<name>.<stem>` (siblings import as `.module`)."""
    path = directory / filename
    package_name = _package(directory, extension_name)
    module_name = f"{package_name}.{path.stem}"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    module.__package__ = package_name
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_factory(
    directory: Path, filename: str, extension_name: str, symbol: str
) -> Callable[[ExtensionContext], list[Any]]:
    """`TOOLS` or `WATCHERS` from a file."""
    module = import_file(directory, filename, extension_name)
    factory = getattr(module, symbol, None)
    if not callable(factory):
        raise ImportError(f"{filename} has no callable {symbol}")
    return factory  # type: ignore[no-any-return]


def read_skill(directory: Path, filename: str) -> str:
    """Skill Markdown."""
    return (directory / filename).read_text(encoding="utf-8")
