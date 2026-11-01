"""sidekick.dashboard.dashboard — DashboardSession: the loopback web app and its server

Overview
    Serves `dashboard_index.html` and the flat `dashboard_*.js` files in this directory (the
    page script, the Live / 3D / Replay scripts and the vendored Three.js module + loaders) and
    the JSON / WebSocket API from `api.py` on `127.0.0.1:8787` by default, inside the sidekick
    process with a uvicorn server task. Invariant 15: it ships in every build and binds
    loopback only.
Design
    FastAPI app built per session from a `DashboardContext`; `start()` runs `uvicorn.Server`
    on the current loop so stopping sidekick stops the dashboard. No build step, no templates:
    the page is static and talks to `/api/*`; the one static route only serves names matching
    `dashboard_<stem>.js` from this directory, so nothing else on disk is reachable. The
    sidebar console (Live first, Replay last) is described in `dashboard_index.html`.
    `LoopbackGuard` closes the one gap loopback binding leaves: a web page open in the owner's
    browser can still reach `127.0.0.1` — a form or a `no-cors` fetch needs no preflight, and a
    rebinding DNS name can even read answers. So every request must name a loopback host (any
    port, so an SSH tunnel works), and every write and the live socket must come from a
    loopback page or from no page at all (the CLI, scripts); the power control made a drive-by
    Stop worth refusing (block #87).
Depends on
    sidekick.log, fastapi, uvicorn.

See Also
--------
    AGENTS.md "Dashboard and CLI", PLAN.md blocks "[2026-10-26 #12]", "[2026-10-26 #25]".

"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from sidekick.log import Log

from .api import DashboardContext, build_router
from .vitals import HostVitals

STATIC_DIR = Path(__file__).parent
INDEX = STATIC_DIR / "dashboard_index.html"
SCRIPT = STATIC_DIR / "dashboard_app.js"
SCRIPT_STEM = re.compile(r"^[a-z0-9_.]{1,40}$")
# Loopback names a request may carry in Host / Origin; `testserver` is Starlette's TestClient.
LOOPBACK_NAMES = frozenset({"127.0.0.1", "localhost", "::1", "testserver"})
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _host_name(host: str) -> str:
    """`127.0.0.1:8787` → `127.0.0.1`, `[::1]:8787` → `::1`."""
    if host.startswith("["):
        return host[1 : host.find("]")] if "]" in host else host
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def _loopback_origin(origin: str) -> bool:
    parts = urlsplit(origin)
    return parts.scheme in ("http", "https") and (parts.hostname or "") in LOOPBACK_NAMES


class LoopbackGuard:
    """ASGI middleware: loopback Host on every request, loopback Origin on writes and sockets."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        """Pass the request on, or answer 403 / close the socket."""
        if scope["type"] in ("http", "websocket"):
            headers = {k.lower(): v for k, v in scope.get("headers") or []}
            host = headers.get(b"host", b"").decode("latin-1")
            origin = headers.get(b"origin")
            write = scope["type"] == "websocket" or scope.get("method", "GET") not in READ_METHODS
            if _host_name(host) not in LOOPBACK_NAMES:
                await self._refuse(scope, send, f"host {host!r} is not loopback")
                return
            if write and origin is not None and not _loopback_origin(origin.decode("latin-1")):
                await self._refuse(scope, send, "cross-site request")
                return
        await self.app(scope, receive, send)

    @staticmethod
    async def _refuse(scope: dict[str, Any], send: Any, reason: str) -> None:
        Log.warning(f"dashboard refused {scope.get('method', 'WS')} {scope.get('path')}: {reason}")
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        body = json.dumps({"detail": reason}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body})


def build_app(ctx: DashboardContext) -> FastAPI:
    """The FastAPI application."""
    app = FastAPI(title="sidekick dashboard", docs_url=None, redoc_url=None)
    app.add_middleware(LoopbackGuard)
    app.include_router(build_router(ctx))

    no_cache = {"Cache-Control": "no-cache"}  # the page and its scripts change with every build

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(INDEX.read_text(encoding="utf-8"), headers=no_cache)

    @app.get("/dashboard_app.js")
    def script() -> FileResponse:
        return FileResponse(SCRIPT, media_type="application/javascript", headers=no_cache)

    @app.get("/dashboard_{stem}.js")
    def static_script(stem: str) -> FileResponse:
        path = STATIC_DIR / f"dashboard_{stem}.js"
        if not SCRIPT_STEM.match(stem) or ".." in stem or not path.is_file():
            raise HTTPException(status_code=404, detail="no such script")
        return FileResponse(
            path, media_type="application/javascript", headers={"Cache-Control": "no-cache"}
        )

    return app


class DashboardSession:
    """Owns the server."""

    shared: ClassVar[DashboardSession]

    def __init__(
        self, ctx: DashboardContext | None = None, host: str = "127.0.0.1", port: int = 8787
    ) -> None:
        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task[None] | None = None
        self.app: FastAPI | None = None
        self.host, self.port = host, port
        if ctx is not None:
            self.setup(ctx, host, port)

    def setup(self, ctx: DashboardContext, host: str = "127.0.0.1", port: int = 8787) -> None:
        """Bind the peers the routes reach and where to listen."""
        self.ctx = ctx
        self.host = host
        self.port = port
        self.app = build_app(ctx)

    @property
    def url(self) -> str:
        """Where the page lives."""
        return f"http://{self.host}:{self.port}/"

    async def start(self) -> None:
        """Serve on the running loop."""
        assert self.app is not None, "setup() first"
        Log.info0(self.url)
        config = uvicorn.Config(
            self.app, host=self.host, port=self.port, log_level="warning", lifespan="off"
        )
        self._server = uvicorn.Server(config)
        self._task = asyncio.create_task(self._server.serve(), name="dashboard")
        await HostVitals.shared.start()  # the event-loop lag probe behind Live's System card
        for _ in range(100):
            if self._server.started:
                break
            await asyncio.sleep(0.05)
        Log.info(f"dashboard at {self.url}")

    async def stop(self) -> None:
        """Shut the server down."""
        await HostVitals.shared.stop()
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, 5.0)
            except (TimeoutError, asyncio.CancelledError, Exception):
                self._task.cancel()
        self._server = None
        self._task = None
