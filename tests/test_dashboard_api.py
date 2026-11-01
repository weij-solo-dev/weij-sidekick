"""Dashboard routes over a null body and a stopped interaction session."""

from __future__ import annotations

from fastapi.testclient import TestClient

from sidekick.body import BodyNullBackend, BodySession
from sidekick.config import ConfigSession
from sidekick.dashboard import DashboardContext, build_app
from sidekick.interaction import InteractionSession
from sidekick.storage import StorageSession


def test_routes(tmp_path):
    storage = StorageSession(tmp_path / "home")
    StorageSession.shared = storage
    storage.ensure_layout()
    config = ConfigSession(storage)
    spec = ConfigSession.default_spec()
    spec.credentials["minimax"] = {"api_key": "sk-cp-SECRET000000000000000000"}
    config.save(spec)
    body = BodySession(BodyNullBackend())
    body.connect()
    interaction = InteractionSession()
    ctx = DashboardContext(
        config,
        spec,
        body=body,
        interaction=interaction,
        log_path=storage.layout.logs_dir / "sidekick.log",
    )
    client = TestClient(build_app(ctx))
    try:
        assert "sidekick" in client.get("/").text
        assert "fetch(" in client.get("/dashboard_app.js").text
        health = client.get("/api/health").json()
        assert health["body"]["state"] == "awake" and health["slots"]["llm.fast"] == "minimax"
        cfg = client.get("/api/config").json()
        assert "SECRET" not in str(cfg) and cfg["interaction"]["speaker_gate"] == "soft"
        updated = client.post(
            "/api/config/interaction",
            json={
                "values": {
                    "speaker_gate": "strict",
                    "triggers": {"wake_name": True, "touch": False},
                }
            },
        ).json()
        assert updated["speaker_gate"] == "strict" and updated["triggers"]["touch"] is False
        assert config.load().interaction.speaker_gate == "strict"
        assert (
            client.post("/api/config/interaction", json={"values": {"nope": 1}}).status_code == 422
        )
        assert client.get("/api/interaction").json()["state"] == "unconfigured"
        assert client.get("/api/interaction/decisions").json() == []
        assert client.get("/api/interaction/clip/abc").status_code == 404
        assert client.post("/api/say", json={"text": "hi"}).status_code == 409
        assert client.get("/api/traces/llm").json() == []
        assert client.get("/api/traces/nope").status_code == 404
        assert client.get("/api/logs").json() == []
        assert client.post("/api/body/express", json={"name": "nod"}).json()["ok"] is True
        catalog = client.get("/api/body/expressions").json()
        assert {"name": "curious", "kind": "emotion"}.items() <= next(
            e for e in catalog if e["name"] == "curious"
        ).items()
    finally:
        body.close()


def test_agent_routes(tmp_path):
    from sidekick.agent import AgentSession
    from sidekick.automation import AutomationSession
    from sidekick.config import ConfigAgents, ConfigAutomation
    from sidekick.llm import LLMSession

    storage = StorageSession(tmp_path / "home")
    StorageSession.shared = storage
    storage.ensure_layout()
    config = ConfigSession(storage)
    spec = ConfigSession.default_spec()
    config.save(spec)
    agent = AgentSession(LLMSession())
    agent.setup(home=tmp_path / "home", agents=ConfigAgents())
    automation = AutomationSession()
    automation.setup(
        tmp_path / "home" / "automation_v1.db", ConfigAutomation(heartbeat_minutes=30), agent
    )
    ctx = DashboardContext(config, spec, agent=agent, automation=automation)
    client = TestClient(build_app(ctx))
    main = client.get("/api/agent").json()["agents"]["main"]
    assert main["slot"] == "fast" and "description" in main  # the Swarm view's agent table
    assert client.get("/api/agent/timeline").json() == []
    # chat without an LLM backend reports the error instead of raising
    reply = client.post("/api/agent/chat", json={"text": "你好"}).json()
    assert reply["error"] and reply["reply"] == ""
    assert reply["tools"] == [] and reply["ms"] >= 0  # the test card's tool calls and timings
    newest = client.get("/api/agent/timeline").json()[0]
    assert newest["role"] == "user"
    said = client.get("/api/agent/timeline?conversation=true").json()
    assert said[0]["content"] == "你好"
    assert client.get(f"/api/agent/timeline?conversation=true&before={said[0]['ts']}").json() == []
    # memory
    agent.memory.remember("owner", "鍾意飲奶茶")
    pyramid = client.get("/api/agent/memory").json()
    facts = pyramid["facts"]
    assert facts[0]["text"] == "鍾意飲奶茶" and facts[0]["origin"] == "explicit"
    assert pyramid["episodes"] == [] and pyramid["writer"]["state"] in ("idle", "off")
    assert client.delete(f"/api/agent/memory/{facts[0]['id']}").json()["removed"] == 1
    added = client.post(
        "/api/agent/memory", json={"scope": "household", "text": "廚房燈掣喺門口左邊"}
    ).json()
    assert added["scope"] == "household" and added["channel"] == "dashboard"
    assert [f["id"] for f in client.get("/api/agent/memory").json()["facts"]] == [added["id"]]
    assert client.post("/api/agent/memory", json={"scope": "x", "text": ""}).status_code == 422
    unnamed = client.post("/api/agent/memory", json={"scope": "person:3", "text": "我叫阿明"})
    assert unnamed.status_code == 400  # unnamed people keep no memory (block #63)
    # jobs
    created = client.post(
        "/api/automation/jobs", json={"name": "pills", "prompt": "食藥", "cron": "0 8 * * *"}
    ).json()
    assert created["next_run_ts"]
    jobs = client.get("/api/automation/jobs").json()
    assert {j["name"] for j in jobs} == {"heartbeat", "pills"}
    assert (
        client.post(f"/api/automation/jobs/{created['id']}/pause", json={}).json()["state"]
        == "paused"
    )
    assert client.post(f"/api/automation/jobs/{created['id']}/delete", json={}).json()["ok"]
    assert client.get("/api/automation").json()["tools"] == ["schedule", "jobs_list", "job_cancel"]
    tools = {t["name"]: t for t in client.get("/api/agent/tools").json()}
    assert tools["schedule"]["main_only"] and tools["schedule"]["origin"] == "automation"
    assert tools["schedule"]["agents"] == ["main"] and tools["delegate"]["main_only"]
    assert tools["remember"]["origin"] == "core" and not tools["remember"]["main_only"]
    assert "properties" in tools["schedule"]["parameters"]
    assert client.post("/api/automation/jobs", json={"name": "x", "prompt": "y"}).status_code == 422
    assert (
        client.post(
            "/api/automation/jobs", json={"name": "x", "prompt": "y", "cron": "bad"}
        ).status_code
        == 422
    )
    # skills
    assert (
        client.put(
            "/api/agent/skills", json={"markdown": "---\nname: s1\ndescription: d\n---\nbody"}
        ).json()["name"]
        == "s1"
    )
    assert client.get("/api/agent/skills").json()[0]["body"] == "body"
    assert client.delete("/api/agent/skills/s1").json()["ok"]
    # subagents (block #76): yours are created, edited and deleted, live and in config.json
    agent.llm.setup("smart", object())  # a bound slot is all the route checks
    roster = client.get("/api/agent/agents").json()
    assert [a["name"] for a in roster] == ["main"] and roster[0]["origin"] == "core"
    made = client.put(
        "/api/agent/subagents/weather",
        json={"description": "天氣", "role": "You look up the weather.", "tools": ["time_now"]},
    )
    assert made.status_code == 200, made.text
    weather = made.json()
    assert weather["origin"] == "user" and weather["llm_slot"] == "smart"
    assert (
        weather["resolved_tools"] == ["time_now"] and weather["role"] == "You look up the weather."
    )
    assert config.load().agents.subagents["weather"].tools == ["time_now"]
    assert "weather: 天氣" in agent.agents_block  # the main agent's prompt lists it
    assert client.get("/api/agent").json()["agents"]["weather"]["origin"] == "user"
    edited = client.put(
        "/api/agent/subagents/weather", json={"role": "Weather only.", "max_steps": 3}
    ).json()
    assert (
        edited["max_steps"] == 3
        and edited["tools"] == ["*"]
        and "delegate" not in edited["resolved_tools"]
    )
    assert client.put("/api/agent/subagents/main", json={"role": "x"}).status_code == 422
    assert client.put("/api/agent/subagents/Bad Name", json={"role": "x"}).status_code == 422
    assert (
        client.put("/api/agent/subagents/w2", json={"role": "x", "llm_slot": "nope"}).status_code
        == 422
    )
    assert client.delete("/api/agent/subagents/weather").json()["ok"]
    assert [a["name"] for a in client.get("/api/agent/agents").json()] == ["main"]
    assert agent.agents_block == ""
    assert "weather" not in config.load().agents.subagents
    assert client.delete("/api/agent/subagents/weather").status_code == 404
    # the main agent's own knobs apply at once (block #78); the rest of the section waits
    applied = client.post("/api/config/agents", json={"values": {"main_hedge_s": 3.0}}).json()
    assert applied["note"] == "applied" and agent.main.profile.hedge_after_s == 3.0
    later = client.post("/api/config/agents", json={"values": {"memory_block_chars": 900}}).json()
    assert "next start" in later["note"]
    # mcp registry (no live connection: a bogus command fails to connect but stays registered)
    added = client.post(
        "/api/agent/mcp", json={"name": "bogus", "command": "/nonexistent/binary"}
    ).json()
    assert added["ok"]
    servers = client.get("/api/agent/mcp").json()
    assert servers[0]["name"] == "bogus" and servers[0]["tools"] == []
    assert client.delete("/api/agent/mcp/bogus").json()["ok"]
    assert client.post("/api/agent/mcp", json={"name": "nope"}).status_code == 422
