"""AutomationSession on a real AgentSession with a scripted LLM: scheduling tools, jobs, events,
the heartbeat, main-only tools and the master switch."""

from __future__ import annotations

import time

import pytest

from sidekick.agent import AgentSession
from sidekick.automation import AutomationSession, Job
from sidekick.channel import ChannelSession
from sidekick.config import ConfigAgents, ConfigAutomation, ConfigSubagent
from sidekick.llm import LLMSession
from sidekick.perception import PerceptionEvent, PerceptionSession, Severity
from test_agent_session import FakeVoice, RecordingAdapter, ScriptedLLM, collect

SCHEDULING = {"schedule", "jobs_list", "job_cancel"}


@pytest.fixture
def stack(tmp_path):
    llm = LLMSession()
    fast, smart = ScriptedLLM("fast"), ScriptedLLM("smart")
    llm.setup("fast", fast)
    llm.setup("smart", smart)
    voice = FakeVoice()
    agent = AgentSession(llm)
    agent.setup(
        home=tmp_path,
        agents=ConfigAgents(
            subagents={"helper": ConfigSubagent(role="You help.", description="looks things up")}
        ),
        default_language="yue",
        say=voice.say,
        can_speak=lambda: True,
    )
    perception = PerceptionSession()
    perception.setup(None, tmp_path / "events_v1.db")
    automation = AutomationSession()
    automation.setup(
        tmp_path / "automation_v1.db",
        ConfigAutomation(tick_s=1.0, heartbeat_minutes=30, quiet_hours=None),
        agent,
        perception,
    )
    channels = ChannelSession()
    ChannelSession.shared = channels
    tg = RecordingAdapter()
    channels.register(tg)
    return agent, automation, perception, fast, voice, tg


async def test_schedule_tool_and_scheduler_delivery(stack):
    agent, automation, _perception, fast, voice, tg = stack
    text = await collect(agent, "八點提我食藥")
    assert "搞掂" in text
    jobs = [j for j in automation.jobs.list_jobs() if not j.builtin]
    assert len(jobs) == 1 and jobs[0].trigger_kind == "at" and jobs[0].owner == "dad"
    assert jobs[0].next_run_ts is not None and jobs[0].next_run_ts < time.time()
    ran = await automation.scheduler.tick()
    assert ran >= 1 and voice.spoken and "提你食藥" in voice.spoken[-1]
    assert automation.jobs.get(jobs[0].id).state == "done"
    delivered = [r for r in agent.dialogue.recent(5) if r.meta.get("delivery")]
    assert delivered and delivered[0].delivered_to == "voice"
    reminders = [r for r in agent.dialogue.recent(10) if "提你食藥啦" in r.content]
    assert len(reminders) == 1  # one row per delivered message, not the turn's copy as well
    # remote delivery goes to the originating text channel
    automation.jobs.save(
        Job(
            "tg",
            "at",
            "2020-01-01T08:00",
            "提你飲水",
            owner="mum",
            channel="telegram",
            delivery="remote",
        )
    )
    await automation.scheduler.tick()
    assert tg.sent and tg.sent[-1].channel == "telegram" and tg.sent[-1].to == "mum"
    # heartbeat says NO_REPLY → nothing delivered; its prompt lists what was already said
    hb = automation.jobs.by_name("heartbeat")
    spoken_before = len(voice.spoken)
    await automation.run_job(hb)
    assert len(voice.spoken) == spoken_before
    prompt = fast.calls[-1][-1]
    assert "never repeat" in prompt and "Already said" in prompt and "提你食藥啦" in prompt
    assert "[express" not in prompt.split("Already said", 1)[1]
    await automation.scheduler.tick(time.time() + 3600)
    await automation.scheduler.tick(time.time() + 7200)  # it ran an hour ago: it is told when
    assert "Your last heartbeat was at" in fast.calls[-1][-1]


async def test_event_jobs_fire_from_the_bus(stack):
    _agent, automation, perception, _fast, voice, _tg = stack
    automation.jobs.save(
        Job(
            "welcome",
            "event",
            "presence.enter",
            "提你食藥",
            owner="dad",
            channel="voice",
            delivery="in_person",
        )
    )
    before = len(voice.spoken)
    await perception.publish(PerceptionEvent("face.seen", Severity.DEBUG))
    assert len(voice.spoken) == before
    await perception.publish(PerceptionEvent("presence.enter", Severity.NOTICE, {"zone": "door"}))
    assert len(voice.spoken) == before + 1 and "提你食藥" in voice.spoken[-1]
    welcome = automation.jobs.by_name("welcome")
    assert welcome.runs == 1 and welcome.state == "active"


async def test_scheduling_tools_are_the_main_agents_only(stack):
    agent, *_ = stack
    main = {t.name for t in agent.tools_for(agent.main.profile)}
    helper = {t.name for t in agent.tools_for(agent.agents["helper"].profile)}
    assert SCHEDULING <= main and "delegate" in main
    assert not SCHEDULING & helper and "delegate" not in helper  # its allowlist is "*"
    assert {t.origin for t in agent.registry.all() if t.name in SCHEDULING} == {"automation"}


async def test_master_switch_stops_everything_and_comes_back(stack):
    agent, automation, perception, _fast, voice, _tg = stack
    await automation.start()
    assert automation.status()["running"] and SCHEDULING <= set(agent.registry.names())
    automation.jobs.save(
        Job("welcome", "event", "presence.enter", "提你食藥", delivery="in_person")
    )
    await automation.apply(ConfigAutomation(enabled=False, heartbeat_minutes=30))
    status = automation.status()
    assert not status["enabled"] and not status["running"] and status["tools"] == []
    assert not SCHEDULING & set(agent.registry.names())
    assert automation.jobs.by_name("heartbeat").state == "paused"
    before = len(voice.spoken)
    await perception.publish(PerceptionEvent("presence.enter", Severity.NOTICE))
    assert len(voice.spoken) == before  # events are ignored while off
    await automation.apply(ConfigAutomation(enabled=True, heartbeat_minutes=30))
    assert automation.status()["running"] and SCHEDULING <= set(agent.registry.names())
    assert automation.jobs.by_name("heartbeat").state == "active"
    await automation.stop()
    assert not automation.status()["running"]
