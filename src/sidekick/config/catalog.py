"""sidekick.config.catalog — loads the bundled provider presets

Overview
    Reads every `provider_*.json` beside this file into `ConfigProvider` models (invariant 3:
    endpoints, models, voices and credential fields live in JSON, never in code).
Design
    Loaded once and cached; a preset with `enabled: false` is skipped; a malformed preset fails
    loudly at import of the catalog rather than at the first call that needs it.
Depends on
    pydantic, stdlib json/pathlib.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from sidekick.log import Log

from .schemas import ConfigProvider

PRESET_DIR = Path(__file__).resolve().parent
PRESET_GLOB = "provider_*.json"


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, ConfigProvider]:
    """Provider id → preset, ordered by `order`."""
    providers: list[ConfigProvider] = []
    for path in sorted(PRESET_DIR.glob(PRESET_GLOB)):
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        provider = ConfigProvider.model_validate(data)
        if not provider.enabled:
            Log.info(f"preset disabled: {path.name}")
            continue
        providers.append(provider)
    providers.sort(key=lambda item: (item.order, item.id))
    return {provider.id: provider for provider in providers}


def provider(provider_id: str) -> ConfigProvider:
    """A preset by id; raises `KeyError` when unknown."""
    catalog = load_catalog()
    if provider_id not in catalog:
        raise KeyError(f"unknown provider {provider_id!r}; known: {sorted(catalog)}")
    return catalog[provider_id]
