"""extensions.robot.tools — body capabilities exposed to the agent (the only such bridge)

Overview
    `TOOLS(ctx)` returns the robot tools: `look` (camera snapshot described by the `smart` slot
    when it has vision, else a plain summary; an optional `question` says what to look for, a
    dark frame is gamma-lifted first and the model is told to say only what it clearly sees —
    a 26/255 frame of a child holding a card came back as "a person sleeping", block #89),
    `express`, `look_at`, `who_is_here`,
    `privacy_mode` (confirm-gated), `enroll_voice` (conversational enrollment of the current
    speaker over the next utterances), `set_volume`, and the befriending trio — `people_seen`
    (who has been around without a name), `befriend(person_id, name)` (the person's collected
    voice / face become a contact; not confirm-gated, befriending is the agent's own call) and
    `decline_befriend`.
Design
    Every tool talks to `BodySession` / `ContactSession` / `PerceptionSession` /
    `InteractionSession` through the `ExtensionContext`; nothing touches the SDK (invariant 10)
    and nothing wakes or sleeps the robot (invariant 11). Tools return short Cantonese-friendly
    sentences the main agent can relay. A voice is never learned into someone else by name
    (block #63): `enroll_voice` from an unnamed speaker befriends them exactly as `befriend`
    does (the samples collected so far kept), and from a named speaker it learns into their own
    contact only, when the name they give is theirs.
Depends on
    sidekick.agent, sidekick.extension, sidekick.body, sidekick.llm (optional vision, when the
    context says the smart slot's provider supports images), numpy.
"""

from __future__ import annotations

import asyncio
import base64
import math
import time
from typing import Any

import numpy as np

from sidekick.agent import Tool, ToolContext, ToolResult
from sidekick.contact import brighten_frame, is_person
from sidekick.extension import ExtensionContext

DIRECTIONS = {
    "left": 60.0,
    "right": -60.0,
    "front": 0.0,
    "center": 0.0,
    "centre": 0.0,
    "左": 60.0,
    "右": -60.0,
    "前": 0.0,
}


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or []}


def TOOLS(ctx: ExtensionContext) -> list[Tool]:
    """Build the robot tools."""
    body = ctx.body

    async def express(arguments: dict[str, Any], tctx: ToolContext) -> ToolResult:
        name = str(arguments.get("name", "")).strip()
        if body is None:
            return ToolResult.error("no body")
        interaction = ctx.interaction
        if interaction is not None and getattr(interaction, "expressions", None) is not None:
            ok = interaction.expressions.express(name)
        else:
            ok = body.express(name)
        return ToolResult(ok, f"expressed {name}" if ok else f"unknown expression {name}")

    async def look_at(arguments: dict[str, Any], tctx: ToolContext) -> ToolResult:
        if body is None:
            return ToolResult.error("no body")
        direction = str(arguments.get("direction", "front")).strip().lower()
        pitch_deg = float(arguments.get("pitch_deg", 0.0) or 0.0)
        if direction in ("up", "上"):
            yaw_deg, pitch_deg = 0.0, 25.0
        elif direction in ("down", "下"):
            yaw_deg, pitch_deg = 0.0, -20.0
        elif direction in DIRECTIONS:
            yaw_deg = DIRECTIONS[direction]
        else:
            try:
                yaw_deg = float(direction)
            except ValueError:
                return ToolResult.error("direction must be left/right/up/down/front or degrees")
        body.look(math.radians(yaw_deg), math.radians(pitch_deg), duration_s=0.8)
        return ToolResult(True, f"looking {direction}")

    async def look(arguments: dict[str, Any], tctx: ToolContext) -> ToolResult:
        if body is None:
            return ToolResult.error("no body")
        frame = body.frame(0.5)
        if frame is None:
            return ToolResult.error("the camera gave no image")
        height, width = frame.shape[:2]
        brightness = float(np.mean(frame))
        faces = ""
        if ctx.contacts is not None and getattr(ctx.contacts, "ready", False):
            try:
                identification, face = await asyncio.to_thread(ctx.contacts.identify_face, frame)
                if face is not None:
                    who = (
                        ctx.contacts.display_name(identification.contact_id)
                        if identification.contact_id
                        else "someone I don't recognise"
                    )
                    faces = f" A face is in view: {who}."
            except Exception as exc:
                faces = f" (face check failed: {exc!r})"
        summary = f"Camera frame {width}x{height}, {'dark' if brightness < 40 else 'dim' if brightness < 90 else 'well lit'} (mean {brightness:.0f}/255).{faces}"
        if (
            ctx.setting("describe_with_vision", True)
            and ctx.llm is not None
            and ctx.spec is not None
        ):
            question = str(arguments.get("question") or "").strip()
            description = await _describe(ctx, brighten_frame(frame), question, brightness)
            if description:
                summary += f" What I see: {description}"
        return ToolResult(True, summary)

    async def who_is_here(arguments: dict[str, Any], tctx: ToolContext) -> ToolResult:
        parts: list[str] = []
        if ctx.perception is not None:
            presence = ctx.perception.presence()
            parts.append(
                "someone is in front of me"
                if presence.someone_present
                else "I don't see anyone right now"
            )
            if presence.frontal:
                parts.append("and they are looking at me")
        if ctx.contacts is not None and getattr(ctx.contacts, "ready", False):
            last = ctx.contacts.last_voice
            if last is not None and last.contact_id and not last.is_self:
                parts.append(
                    f"the last voice I heard was {ctx.contacts.display_name(last.contact_id)} ({last.score:.2f})"
                )
            elif last is not None and not last.is_self:
                parts.append("the last voice was someone I don't know")
            if body is not None:
                frame = body.frame(0.5)
                if frame is not None:
                    identification, face = await asyncio.to_thread(
                        ctx.contacts.identify_face, frame
                    )
                    if face is not None:
                        parts.append(
                            f"face: {ctx.contacts.display_name(identification.contact_id) if identification.contact_id else 'unknown'}"
                        )
        return ToolResult(True, "; ".join(parts) or "no perception available")

    async def privacy_mode(arguments: dict[str, Any], tctx: ToolContext) -> ToolResult:
        on = bool(arguments.get("on", True))
        interaction = ctx.interaction
        if interaction is None:
            return ToolResult.error("no voice front end")
        if on:
            if interaction.started:
                await interaction.stop()
            if body is not None:
                body.track_face(False)
            return ToolResult(
                True, "privacy mode on: I stopped listening and looking", expression="sad"
            )
        if not interaction.started:
            await interaction.start()
        return ToolResult(True, "privacy mode off: listening again", expression="happy")

    async def _befriend(person_id: str, name: str, language: str | None) -> Any:
        """The person becomes a contact (samples kept) and the open session follows the new id."""
        contacts = _people_ready()
        if contacts is None:
            return None
        contact = await asyncio.to_thread(contacts.promote_person, person_id, name, language)
        interaction = ctx.interaction
        if (
            contact is not None
            and interaction is not None
            and hasattr(interaction, "rename_speaker")
        ):
            interaction.rename_speaker(person_id, contact.id)
        return contact

    async def enroll_voice(arguments: dict[str, Any], tctx: ToolContext) -> ToolResult:
        name = str(arguments.get("name", "")).strip()
        language = str(arguments.get("language") or "").strip() or None
        contacts = ctx.contacts
        interaction = ctx.interaction
        if contacts is None or not getattr(contacts, "ready", False):
            return ToolResult.error("contacts not available")
        if not name:
            return ToolResult.error("name is required")
        if interaction is None or not interaction.started:
            return ToolResult.error("voice front end not running")
        speaker = contacts.resolve_speaker(tctx.speaker)
        if is_person(speaker):  # no name yet and asking to be remembered: befriending
            contact = await _befriend(speaker, name, language)
            if contact is None:
                return ToolResult.error(f"{speaker} is not known (already befriended?)")
        else:
            contact = contacts.get(speaker)
            if contact is None or contact.is_self:
                return ToolResult.error("only the person talking in the room can be learned")
            names = {
                contact.id.lower(),
                contact.name.lower(),
                *(a.lower() for a in contact.aliases),
            }
            if name.lower() not in names:
                return ToolResult.error(
                    f"this voice is {contact.name}'s, not {name}'s; a new household member is "
                    "enrolled on the dashboard (Contacts)"
                )
        count = int(ctx.setting("enroll_utterances", 3) or 3)
        if not interaction.start_enrollment(contact.id, count):
            return ToolResult(
                True,
                f"{contact.name} is known; the voice heard so far is kept (no conversation open "
                "to learn more)",
                {"contact_id": contact.id},
            )
        return ToolResult(
            True,
            f"enrolling {contact.name}: the next {count} utterances will be learned",
            {"contact_id": contact.id},
        )

    async def set_volume(arguments: dict[str, Any], tctx: ToolContext) -> ToolResult:
        if body is None or not hasattr(body.backend, "set_volume"):
            return ToolResult.error("volume control not available")
        volume = int(arguments.get("volume", 70))
        volume = max(10, min(100, volume))
        ok = bool(body.backend.set_volume(volume))
        return ToolResult(ok, f"volume {volume}" if ok else "could not set volume")

    def _people_ready() -> Any:
        contacts = ctx.contacts
        if (
            contacts is None
            or not getattr(contacts, "ready", False)
            or not hasattr(contacts, "people")
        ):
            return None
        return contacts

    async def people_seen(arguments: dict[str, Any], tctx: ToolContext) -> ToolResult:
        contacts = _people_ready()
        if contacts is None:
            return ToolResult.error("contacts not available")
        people = contacts.people()
        if not people:
            return ToolResult(True, "nobody without a name has been around")
        now = time.time()
        lines = []
        for person in people[:10]:
            ago = now - person.last_seen_ts
            when = f"{ago / 60:.0f} min ago" if ago < 3600 else f"{ago / 3600:.1f} h ago"
            lines.append(
                f"- {person.id}: heard {person.utterances} time(s) over {person.sessions} "
                f"session(s), face {person.face_samples} frame(s), last seen {when}"
                + (" (declined)" if person.declined_ts else "")
            )
        return ToolResult(True, "\n".join(lines))

    async def befriend(arguments: dict[str, Any], tctx: ToolContext) -> ToolResult:
        contacts = _people_ready()
        if contacts is None:
            return ToolResult.error("contacts not available")
        person_id = str(arguments.get("person_id") or tctx.speaker or "").strip()
        name = str(arguments.get("name", "")).strip()
        language = str(arguments.get("language") or "").strip() or None
        if not name:
            return ToolResult.error("name is required")
        if not is_person(person_id):
            return ToolResult.error("person_id must be a person:N speaker")
        contact = await _befriend(person_id, name, language)
        if contact is None:
            return ToolResult.error(f"{person_id} is not known (already befriended?)")
        return ToolResult(
            True,
            f"befriended {name} ({contact.id}); their voice and face so far are kept",
            expression="happy",
        )

    async def decline_befriend(arguments: dict[str, Any], tctx: ToolContext) -> ToolResult:
        contacts = _people_ready()
        if contacts is None:
            return ToolResult.error("contacts not available")
        person_id = str(arguments.get("person_id") or tctx.speaker or "").strip()
        if not is_person(person_id):
            return ToolResult.error("person_id must be a person:N speaker")
        contacts.mark_person(person_id, "declined")
        return ToolResult(True, f"noted: {person_id} will not be asked again for a week")

    catalog = body.expression_catalog() if body is not None else []

    def names(kind: str) -> str:
        return ", ".join(e["name"] for e in catalog if e["kind"] == kind)

    return [
        Tool(
            "express",
            "Play one of your own expressions (performed, never spoken; most replies need none). "
            f"Beats: {names('beat')}. Emotions, only for a real feeling: {names('emotion')}. "
            f"Performances, only when asked (never mid-reply): {names('performance')}. "
            "Prefer the [express:name] tag inside the reply text.",
            _schema({"name": {"type": "string"}}, ["name"]),
            express,
        ),
        Tool(
            "look_at",
            "Turn the head: left, right, up, down, front, or a yaw in degrees.",
            _schema(
                {"direction": {"type": "string"}, "pitch_deg": {"type": "number"}}, ["direction"]
            ),
            look_at,
        ),
        Tool(
            "look",
            "Take a camera snapshot and describe what is in front of the robot. Pass `question`"
            " when they ask about something in particular (a card they hold up, who is there).",
            _schema(
                {
                    "question": {
                        "type": "string",
                        "description": "what to look for, in English (e.g. 'what is on the card"
                        " they are holding up?')",
                    }
                }
            ),
            look,
        ),
        Tool(
            "who_is_here",
            "Who the camera and microphone recognise right now.",
            _schema({}),
            who_is_here,
        ),
        Tool(
            "privacy_mode",
            "Stop (on=true) or resume (on=false) listening and looking.",
            _schema({"on": {"type": "boolean"}}),
            privacy_mode,
            confirm=True,
        ),
        Tool(
            "enroll_voice",
            "Learn more of the current speaker's voice over their next utterances (they asked to "
            "be remembered). A person:N speaker is befriended by it, as with befriend; a named "
            "speaker only under their own name.",
            _schema(
                {
                    "name": {"type": "string"},
                    "language": {"type": "string", "description": "zh, en or yue"},
                },
                ["name"],
            ),
            enroll_voice,
        ),
        Tool(
            "set_volume",
            "Set the speaker volume (10–100).",
            _schema({"volume": {"type": "integer"}}, ["volume"]),
            set_volume,
        ),
        Tool(
            "people_seen",
            "People heard (and maybe seen) around the house who have no name yet (person:N), with how often.",
            _schema({}),
            people_seen,
        ),
        Tool(
            "befriend",
            "Make a person:N speaker a named acquaintance after they told you their name and agreed to be remembered; their collected voice and face are kept.",
            _schema(
                {
                    "person_id": {"type": "string"},
                    "name": {"type": "string"},
                    "language": {"type": "string", "description": "zh, en or yue"},
                },
                ["person_id", "name"],
            ),
            befriend,
        ),
        Tool(
            "decline_befriend",
            "The person:N speaker did not want to be remembered (or ignored the question): do not ask again for a week.",
            _schema({"person_id": {"type": "string"}}, ["person_id"]),
            decline_befriend,
        ),
    ]


def _vision_prompt(question: str, brightness: float) -> str:
    """What the vision model is asked: one honest sentence, about the question when there is one."""
    ask = question or "Describe this room scene."
    lighting = (
        " The room is dark: the photo was brightened and is grainy, so say only what you can"
        " make out clearly and say plainly when you cannot."
        if brightness < 40
        else ""
    )
    return (
        f"{ask} Answer in one short sentence.{lighting} Do not guess what people are doing"
        " (asleep, eating, …) unless it is plain to see."
    )


async def _describe(
    ctx: ExtensionContext, frame: np.ndarray, question: str = "", brightness: float = 128.0
) -> str:
    """Ask the smart slot to describe the frame when the provider supports images."""
    try:
        import cv2

        from sidekick.llm import LLMInferOptions, LLMMessage
    except Exception:
        return ""
    llm = ctx.llm
    if llm is None or not llm.is_ready("smart"):
        return ""
    if not ctx.vision:
        return ""
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
    if not ok:
        return ""
    data_url = "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode()
    content: Any = [
        {"type": "text", "text": _vision_prompt(question, brightness)},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]
    try:
        result = await llm.infer(
            "smart",
            [LLMMessage("user", content)],
            LLMInferOptions(max_tokens=120),
            task="robot.look",
        )
    except Exception:
        return ""
    return (result.output or "").strip() if result.success else ""
