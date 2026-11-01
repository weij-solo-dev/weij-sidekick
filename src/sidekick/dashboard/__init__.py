"""sidekick.dashboard — loopback FastAPI app: health, settings, listening monitor, traces, logs."""

from .api import DashboardContext, build_router
from .dashboard import DashboardSession, build_app

__all__ = ["DashboardContext", "DashboardSession", "build_app", "build_router"]
