"""Hedged streams (block #78): a late first answer is asked again, the first to answer wins."""

from __future__ import annotations

import asyncio
import time

from sidekick.llm import LLMInferOptions, LLMMessage, LLMResult, LLMSession, LLMStreamEvent


class TimedBackend:
    """Call n answers after `delays[n]` seconds; `("fail", s)` fails after s seconds."""

    def __init__(self, delays):
        self.delays = list(delays)
        self.calls = 0
        self.cancelled = 0

    async def infer(self, messages, options):  # pragma: no cover - not used
        raise NotImplementedError

    async def stream(self, messages, options):
        index = self.calls
        self.calls += 1
        delay = self.delays[index]
        try:
            if isinstance(delay, tuple):
                await asyncio.sleep(delay[1])
                failure = LLMResult(False, None, "fake", "fake", "m", "****", error_message="boom")
                yield LLMStreamEvent("done", result=failure)
                return
            await asyncio.sleep(delay)
            yield LLMStreamEvent("start")
            yield LLMStreamEvent("text", text=f"answer {index}")
            result = LLMResult(True, f"answer {index}", "fake", "fake", "m", "****")
            yield LLMStreamEvent("done", result=result)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise


def session_with(backend):
    llm = LLMSession()
    llm.configure_trace(None)
    llm.setup("fast", backend)
    return llm


async def run(llm, hedge):
    return [
        event
        async for event in llm.stream(
            "fast", [LLMMessage("user", "hi")], LLMInferOptions(), task="t", hedge_after_s=hedge
        )
    ]


def texts(events):
    return [e.text for e in events if e.kind == "text"]


async def test_a_late_answer_is_asked_again_and_the_first_answer_wins():
    backend = TimedBackend([0.6, 0.05])
    llm = session_with(backend)
    started = time.monotonic()
    events = await run(llm, 0.1)
    assert time.monotonic() - started < 0.45  # not the 0.6 s of the first request
    assert texts(events) == ["answer 1"] and events[-1].result.success
    assert backend.calls == 2 and backend.cancelled == 1
    slot = llm.live()["slots"]["fast"]
    assert slot["hedged"] == 1 and slot["hedge_won"] == 1
    assert slot["errors_1h"] == 0 and slot["cancelled_1h"] == 1  # the slower one is no error
    recent = llm.calls.recent()
    assert any(c["task"] == "t.hedge" and c["ok"] for c in recent)
    assert any(c["task"] == "t" and c["error"] == "hedge lost" for c in recent)


async def test_a_quick_answer_is_never_asked_twice():
    backend = TimedBackend([0.01])
    llm = session_with(backend)
    assert texts(await run(llm, 0.2)) == ["answer 0"] and backend.calls == 1
    assert "hedged" not in llm.live()["slots"]["fast"]


async def test_the_first_request_still_wins_when_it_answers_first():
    backend = TimedBackend([0.15, 0.6])
    llm = session_with(backend)
    assert texts(await run(llm, 0.1)) == ["answer 0"]
    assert backend.cancelled == 1 and llm.hedges["fast"] == {"sent": 1, "won": 0}


async def test_a_failed_request_does_not_win_while_the_other_may_answer():
    backend = TimedBackend([("fail", 0.15), 0.25])
    events = await run(session_with(backend), 0.1)
    assert texts(events) == ["answer 1"] and events[-1].result.success
    both = TimedBackend([("fail", 0.15), ("fail", 0.2)])
    events = await run(session_with(both), 0.1)
    assert events[-1].kind == "done" and not events[-1].result.success
    early = TimedBackend([("fail", 0.01)])  # failing before the threshold: no second request
    events = await run(session_with(early), 0.2)
    assert early.calls == 1 and not events[-1].result.success


async def test_no_threshold_means_one_request_and_a_stop_cancels_both():
    backend = TimedBackend([0.3])
    assert (await run(session_with(backend), None))[-1].result.success and backend.calls == 1
    backend = TimedBackend([1.0, 1.0])
    llm = session_with(backend)
    stream = llm.stream(
        "fast", [LLMMessage("user", "hi")], LLMInferOptions(), task="t", hedge_after_s=0.05
    )
    pending = asyncio.ensure_future(stream.__anext__())
    await asyncio.sleep(0.2)  # both requests are out
    pending.cancel()  # a barge-in
    try:
        await pending
    except asyncio.CancelledError:
        pass
    await stream.aclose()
    await asyncio.sleep(0.05)
    assert backend.calls == 2 and backend.cancelled == 2
    assert llm.calls.summary()["fast"]["inflight"] == 0
