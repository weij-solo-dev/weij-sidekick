"""Automation jobs: the cron matcher, the job store, the heartbeat job and the scheduler's quiet hours."""

from __future__ import annotations

import time
from datetime import datetime

from sidekick.automation import (
    HEARTBEAT_NAME,
    Job,
    JobStore,
    Scheduler,
    compute_next,
    cron_matches,
    ensure_heartbeat,
    heartbeat_prompt,
    is_heartbeat,
    next_cron,
)


def test_cron_matcher_and_next():
    at = datetime(2026, 10, 26, 8, 0)  # a Monday
    assert cron_matches("0 8 * * *", at)
    assert cron_matches("*/30 * * * *", at) and not cron_matches(
        "*/30 * * * *", at.replace(minute=20)
    )
    assert cron_matches("0 8 * * 1-5", at) and not cron_matches("0 8 * * 0,6", at)
    assert cron_matches("0 8 26 10 *", at) and not cron_matches("0 8 27 * *", at)
    nxt = next_cron("0 8 * * *", at)
    assert nxt == datetime(2026, 10, 27, 8, 0)
    assert next_cron("*/15 * * * *", at.replace(minute=7)) == at.replace(minute=15)
    assert next_cron("0 0 30 2 *", at) is None  # never


def test_job_store_due_and_runs(tmp_path):
    store = JobStore(tmp_path / "automation_v1.db")
    past = Job("pills", "at", "2020-01-01T08:00", "提我食藥", owner="dad", channel="voice")
    saved = store.save(past)
    assert saved.next_run_ts is not None and saved in store.due()
    cron = store.save(Job("news", "cron", "0 8 * * *", "morning briefing"))
    assert cron.next_run_ts is not None and cron not in store.due()
    ran = store.mark_run(saved)
    assert ran.state == "done" and ran.runs == 1 and ran.next_run_ts is None and store.due() == []
    hb = ensure_heartbeat(store, 30)
    assert hb.builtin and hb.trigger == "*/30 * * * *" and is_heartbeat(hb)
    paused = ensure_heartbeat(store, 0)
    assert paused.state == "paused" and paused.id == hb.id  # paused, not replaced
    assert ensure_heartbeat(store, 120).trigger == "0 */2 * * *"
    assert not is_heartbeat(Job(HEARTBEAT_NAME, "cron", "* * * * *", "a user's own job"))
    assert store.set_state(cron.id, "paused").next_run_ts is None
    assert store.by_name("news").state == "paused"
    assert store.delete(cron.id) and store.by_name("news") is None
    assert compute_next(Job("x", "event", "face.unknown", "p")) is None


async def test_scheduler_quiet_hours_silence_only_the_heartbeat(tmp_path):
    store = JobStore(tmp_path / "automation_v1.db")
    ran = []

    async def runner(job):
        ran.append(job.name)

    scheduler = Scheduler(
        store, runner, quiet_hours=("23:00", "07:30"), silent_in_quiet_hours=is_heartbeat
    )
    scheduler.in_quiet_hours = lambda now=None: True  # inside the quiet hours
    heartbeat = ensure_heartbeat(store, 30)
    store.save(Job("pills", "at", "2020-01-01T08:00", "提我食藥"))
    later = time.time() + 3600
    assert await scheduler.tick(later) == 1 and ran == ["pills"]  # the reminder still speaks
    skipped = store.by_name(HEARTBEAT_NAME)
    assert skipped.id == heartbeat.id and skipped.last_run_ts == later and skipped.runs == 1
    scheduler.in_quiet_hours = lambda now=None: False
    assert await scheduler.tick(time.time() + 7200) == 1 and ran == ["pills", HEARTBEAT_NAME]


def test_heartbeat_prompt_lists_what_was_said_newest_last():
    job = Job(HEARTBEAT_NAME, "cron", "*/30 * * * *", "Heartbeat check.", builtin=True)
    assert heartbeat_prompt(job, []) == "Heartbeat check."
    said = [(1000.0, "提你食藥啦"), (2000.0, "早晨"), (3000.0, "提你食藥啦")]
    prompt = heartbeat_prompt(job, said)
    assert "Already said" in prompt and prompt.count("提你食藥啦") == 1
    assert prompt.rindex("提你食藥啦") > prompt.index("早晨")  # newest last, by its newest time
