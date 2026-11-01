"""sidekick.automation — jobs, the scheduler, event jobs and the heartbeat, run on the main agent."""

from .automation import AutomationSession
from .heartbeat import HEARTBEAT_NAME, ensure_heartbeat, heartbeat_prompt, is_heartbeat
from .jobs import JobStore, compute_next, cron_matches, next_cron, parse_at
from .scheduler import Scheduler
from .schemas import Job
from .tools import automation_tools

__all__ = [
    "HEARTBEAT_NAME",
    "AutomationSession",
    "Job",
    "JobStore",
    "Scheduler",
    "automation_tools",
    "compute_next",
    "cron_matches",
    "ensure_heartbeat",
    "heartbeat_prompt",
    "is_heartbeat",
    "next_cron",
    "parse_at",
]
