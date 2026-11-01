"""extensions.home.tools — Home Assistant REST as agent tools

Overview
    `ha_entities` (list entities matching a word), `ha_state` (one entity), `ha_call`
    (`/api/services/<domain>/<service>`, confirm-gated for lock / alarm_control_panel / cover
    domains through a second tool `ha_call_sensitive`).
Design
    Bearer token from settings; one `httpx.AsyncClient` per call. Results are short text lines.
Depends on
    sidekick.agent, sidekick.extension, httpx.
"""

from __future__ import annotations

from typing import Any

import httpx

from sidekick.agent import Tool, ToolContext, ToolResult
from sidekick.extension import ExtensionContext

SENSITIVE_DOMAINS = {"lock", "alarm_control_panel", "cover", "garage_door"}


def client(ctx: ExtensionContext) -> httpx.AsyncClient | None:
    """Authenticated client or None when not configured."""
    url = str(ctx.setting("url", "") or "").rstrip("/")
    token = str(ctx.setting("token", "") or "")
    if not url or not token:
        return None
    return httpx.AsyncClient(
        base_url=url,
        timeout=15.0,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or []}


async def fetch_states(ctx: ExtensionContext) -> list[dict[str, Any]]:
    """All entity states (raises when not configured)."""
    c = client(ctx)
    if c is None:
        raise RuntimeError("Home Assistant is not configured (settings: url, token)")
    try:
        response = await c.get("/api/states")
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else []
    finally:
        await c.aclose()


def TOOLS(ctx: ExtensionContext) -> list[Tool]:
    """Build the Home Assistant tools."""

    async def ha_entities(arguments: dict[str, Any], tctx: ToolContext) -> ToolResult:
        query = str(arguments.get("query", "")).strip().lower()
        try:
            states = await fetch_states(ctx)
        except Exception as exc:
            return ToolResult.error(str(exc))
        rows = [
            s
            for s in states
            if query in s.get("entity_id", "").lower()
            or query in str(s.get("attributes", {}).get("friendly_name", "")).lower()
        ]
        if not rows:
            return ToolResult(True, "no matching entities")
        lines = [
            f"- {s['entity_id']} ({s.get('attributes', {}).get('friendly_name', '')}): {s.get('state')}"
            for s in rows[:25]
        ]
        return ToolResult(True, "\n".join(lines))

    async def ha_state(arguments: dict[str, Any], tctx: ToolContext) -> ToolResult:
        entity = str(arguments.get("entity_id", "")).strip()
        if not entity:
            return ToolResult.error("entity_id is required")
        c = client(ctx)
        if c is None:
            return ToolResult.error("Home Assistant is not configured (settings: url, token)")
        try:
            response = await c.get(f"/api/states/{entity}")
            if response.status_code == 404:
                return ToolResult.error(f"no entity {entity}")
            response.raise_for_status()
            state = response.json()
        except Exception as exc:
            return ToolResult.error(f"Home Assistant: {exc!r}")
        finally:
            await c.aclose()
        attrs = state.get("attributes", {})
        keep = {
            k: v
            for k, v in attrs.items()
            if k
            in (
                "friendly_name",
                "unit_of_measurement",
                "temperature",
                "brightness",
                "current_temperature",
                "hvac_action",
                "media_title",
            )
        }
        return ToolResult(
            True,
            f"{entity} is {state.get('state')} {keep}",
            {"state": state.get("state"), "attributes": attrs},
        )

    async def _call(arguments: dict[str, Any]) -> ToolResult:
        domain = str(arguments.get("domain", "")).strip()
        service = str(arguments.get("service", "")).strip()
        entity = str(arguments.get("entity_id", "")).strip()
        data = dict(arguments.get("data") or {})
        if not domain or not service:
            return ToolResult.error("domain and service are required (e.g. light / turn_on)")
        if entity:
            data["entity_id"] = entity
        c = client(ctx)
        if c is None:
            return ToolResult.error("Home Assistant is not configured (settings: url, token)")
        try:
            response = await c.post(f"/api/services/{domain}/{service}", json=data)
            response.raise_for_status()
            changed = response.json()
        except Exception as exc:
            return ToolResult.error(f"Home Assistant: {exc!r}")
        finally:
            await c.aclose()
        summary = (
            ", ".join(f"{s.get('entity_id')}={s.get('state')}" for s in changed[:5])
            if isinstance(changed, list)
            else "done"
        )
        return ToolResult(True, f"{domain}.{service} on {entity or 'targets'}: {summary or 'done'}")

    async def ha_call(arguments: dict[str, Any], tctx: ToolContext) -> ToolResult:
        if str(arguments.get("domain", "")).strip() in SENSITIVE_DOMAINS:
            return ToolResult.error(
                "this domain is sensitive; use ha_call_sensitive (it asks for confirmation)"
            )
        return await _call(arguments)

    async def ha_call_sensitive(arguments: dict[str, Any], tctx: ToolContext) -> ToolResult:
        return await _call(arguments)

    params = _schema(
        {
            "domain": {"type": "string"},
            "service": {"type": "string"},
            "entity_id": {"type": "string"},
            "data": {"type": "object"},
        },
        ["domain", "service"],
    )
    return [
        Tool(
            "ha_entities",
            "Find Home Assistant entities by a word in their id or name.",
            _schema({"query": {"type": "string"}}),
            ha_entities,
        ),
        Tool(
            "ha_state",
            "Read one entity's state.",
            _schema({"entity_id": {"type": "string"}}, ["entity_id"]),
            ha_state,
        ),
        Tool(
            "ha_call",
            "Call a Home Assistant service (lights, switches, climate, media). Not for locks/alarms/covers.",
            params,
            ha_call,
        ),
        Tool(
            "ha_call_sensitive",
            "Call a service in a sensitive domain (lock, alarm, cover); requires the person's confirmation.",
            params,
            ha_call_sensitive,
            confirm=True,
        ),
    ]
