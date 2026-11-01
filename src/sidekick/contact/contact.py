"""sidekick.contact.contact — ContactSession: who is who in the household

Overview
    Profiles plus voice and face identification behind one façade: `identify_voice(clip)`,
    `identify_face(frame)`, `enroll_voice(contact, clips)`, `enroll_face(contact, frames)`,
    `enroll_self(clips)` (the robot's own TTS voice), `resolve_speaker("tg:42")` (remote ids,
    the dashboard's `owner` and a person befriended in this run to contacts),
    `display_name(id)`, CRUD. `interaction` fuses the identifications with the direction of
    arrival; `agent` scopes memory and names the speaker in its prompt.
Design
    Identifiers are lazy and synchronous (callers use `asyncio.to_thread`); centroids are read
    from the store per call (a household has a handful) so enrollment takes effect at once.
    Unknown speakers stay `guest:<n>` for a session; there are no roles or modes. Identities
    never merge by name (block #63): `create` takes a free id (`阿明_2`) instead of overwriting a
    contact, so a stranger befriended under a household member's name stays someone else;
    `update` is the only way to change a profile. `start()`
    enrolls the robot's own voice from three clips of the `synthesize` function `setup` was
    given (when `contacts.enroll_self` is on and it is not enrolled yet), merges unnamed people
    who are a contact's voice and forgets unnamed people unseen for `PEOPLE_RETENTION_DAYS`,
    then once a day; `stop()` ends that loop.
    **Voices keep learning (block #80).** One night's three utterances do not cover the next
    morning (the owner scored 0.41–0.54 against them): `learn_voice` folds an utterance
    identified as a contact into the contact's centroid with its weight capped at
    `VOICE_LEARN_WEIGHT`, so a new hour or place in the room keeps moving it, and
    `merge_person` hands an unnamed person to a contact once the person's centroid (≥
    `MERGE_MIN_UTTERANCES`) is within `MERGE_SCORE` of that contact and clearly closer to it
    than to any other — the voice split in two the morning before (`person:25` vs 发瘟鸡: 0.57)
    is one again. Merging is by voice evidence, never by name (block #63 still holds).
    The store stays open while Bobby's service is stopped (the Contacts page); `stop()` drops
    the voice and face models and `check()` counts the household (block #87).
Depends on
    sidekick.log, sidekick.storage, sidekick.audio.

See Also
--------
    AGENTS.md "Contact and identification", PLAN.md block "[2026-10-26 #18]".

"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from sidekick.audio import AudioClip
from sidekick.log import Log

from .face import (
    DETECTOR_NAME,
    RECOGNIZER_NAME,
    DetectedFace,
    FaceConfiguration,
    FaceIdentifier,
    Frame,
    brighten_frame,
)
from .schemas import (
    OWNER_ALIAS,
    SELF_ID,
    Contact,
    Identification,
    Person,
    Vector,
    cosine,
    is_person,
    slugify,
)
from .store import ContactStore
from .voice import MODEL_NAME as VOICE_MODEL_NAME
from .voice import VoiceConfiguration, VoiceIdentifier

Synthesize = Callable[[str], Awaitable[AudioClip | None]]

PEOPLE_RETENTION_DAYS = 7.0  # unnamed people (block #35)
VOICE_LEARN_WEIGHT = 50  # a contact's centroid against each newly learned utterance (block #80)
MERGE_MIN_UTTERANCES = 4  # an unnamed person needs this many before a merge is considered
MERGE_SCORE = 0.55  # person centroid vs contact centroid
MERGE_MARGIN = 0.1  # ...and this much closer to it than to the next contact
NAME_TTL_S = 30.0  # display names are cached this long (dropped on any contact change)
COUNTS_TTL_S = 30.0  # `live()` counts members and people seen at most this often
SELF_ENROLL_TEXTS = (
    "你好，我係 Bobby，係屋企嘅小管家。",
    "今日天氣好好，記得帶遮出門呀。",
    "我聽到你講嘢啦，有咩可以幫到你？",
)


class ContactSession:
    """Household identity."""

    shared: ClassVar[ContactSession]

    def __init__(self) -> None:
        self.store: ContactStore | None = None
        self.voice: VoiceIdentifier | None = None
        self.face: FaceIdentifier | None = None
        self._guest_counter = 0
        self._touched: dict[str, float] = {}
        self._promoted: dict[str, str] = {}  # person id → contact, befriended in this run
        self.last_voice: Identification | None = None
        self.last_face: Identification | None = None
        self.last_voice_at = 0.0
        self.last_face_at = 0.0
        self._names: dict[str, tuple[float, str]] = {}  # display names, kept NAME_TTL_S
        self._counts: tuple[float, dict[str, Any]] | None = None  # for `live()`, COUNTS_TTL_S
        self.synthesize: Synthesize | None = None
        self.enroll_self_on_start = False
        self._prune_task: asyncio.Task[None] | None = None

    def setup(
        self,
        db_path: Path,
        models_dir: Path,
        config: Any = None,
        synthesize: Synthesize | None = None,
    ) -> None:
        """Open the store and prepare the identifiers (models load lazily)."""
        self.store = ContactStore(db_path)
        self.synthesize = synthesize
        self.enroll_self_on_start = bool(getattr(config, "enroll_self", False))
        voice_threshold = (
            float(getattr(config, "voice_threshold", 0.5)) if config is not None else 0.5
        )
        face_threshold = (
            float(getattr(config, "face_threshold", 0.363)) if config is not None else 0.363
        )
        tv_zone = getattr(config, "tv_zone", None) if config is not None else None
        self.voice = VoiceIdentifier(
            VoiceConfiguration(models_dir / VOICE_MODEL_NAME, threshold=voice_threshold)
        )
        self.face = FaceIdentifier(
            FaceConfiguration(
                models_dir / DETECTOR_NAME,
                models_dir / RECOGNIZER_NAME,
                threshold=face_threshold,
                tv_zone=(float(tv_zone[0]), float(tv_zone[1]), float(tv_zone[2]), float(tv_zone[3]))
                if tv_zone and len(tv_zone) == 4
                else None,
            )
        )

    async def start(self) -> None:
        """Enroll the robot's own voice when needed, merge split voices, prune people daily."""
        if self.enroll_self_on_start and not self.self_enrolled():
            await self._enroll_self()
        if self.ready:
            try:
                await asyncio.to_thread(self.merge_people)
            except Exception as exc:
                Log.warning(f"merging people failed: {exc!r}")
        if self._prune_task is None:
            self._prune_task = asyncio.create_task(self._prune_daily(), name="contact-prune")

    async def stop(self) -> None:
        """End the daily pruning and drop the voice and face models (the store stays open)."""
        if self._prune_task is not None:
            self._prune_task.cancel()
            self._prune_task = None
        for identifier in (self.voice, self.face):
            if identifier is not None:
                identifier.release()

    def check(self) -> list[dict[str, Any]]:
        """Readiness items: nothing to prove, the household counted (advice when empty)."""
        if not self.ready:
            return [{"id": "store", "title": "contacts", "level": "warn", "detail": "no store"}]
        members = [c for c in self.contacts() if c.id != "self"]
        owner = any(getattr(c, "is_owner", False) for c in members)
        items = [
            {
                "id": "household",
                "title": "household",
                "level": "ok" if members else "warn",
                "detail": (f"{len(members)} member(s)" + ("" if owner else " · no owner"))
                if members
                else "nobody enrolled yet (Contacts → New member)",
            }
        ]
        if not self.self_enrolled():
            items.append(
                {
                    "id": "self_voice",
                    "title": "Bobby's own voice",
                    "level": "warn",
                    "detail": "not enrolled yet (needs a working TTS)",
                }
            )
        return items

    async def _enroll_self(self) -> None:
        """The robot's own TTS voice, so echo residuals are recognised as `self`."""
        if self.synthesize is None:
            return
        clips = []
        for text in SELF_ENROLL_TEXTS:
            clip = await self.synthesize(text)
            if clip is not None:
                clips.append(clip)
        if clips:
            used = await asyncio.to_thread(self.enroll_self, clips)
            Log.info(f"self voice enrolled from {used} TTS clip(s)")
        else:
            Log.warning("self voice not enrolled: TTS unavailable")

    async def _prune_daily(self) -> None:
        while True:
            try:
                if self.ready:
                    forgotten = await asyncio.to_thread(self.prune_people, PEOPLE_RETENTION_DAYS)
                    if forgotten:
                        Log.info(f"forgot {forgotten} unnamed person(s) not seen for a week")
            except Exception as exc:
                Log.warning(f"people pruning failed: {exc!r}")
            await asyncio.sleep(86400.0)

    def set_config(self, config: Any) -> None:
        """Apply changed thresholds and the TV zone live (Contacts page)."""
        if self.voice is not None:
            self.voice.configuration = replace(
                self.voice.configuration,
                threshold=float(
                    getattr(config, "voice_threshold", self.voice.configuration.threshold)
                ),
            )
        if self.face is not None:
            tv_zone = getattr(config, "tv_zone", None)
            self.face.configuration = replace(
                self.face.configuration,
                threshold=float(
                    getattr(config, "face_threshold", self.face.configuration.threshold)
                ),
                tv_zone=(float(tv_zone[0]), float(tv_zone[1]), float(tv_zone[2]), float(tv_zone[3]))
                if tv_zone and len(tv_zone) == 4
                else None,
            )
        Log.info(
            f"contact config applied: voice {self.voice.configuration.threshold if self.voice else None} · face {self.face.configuration.threshold if self.face else None} · tv zone {tv_zone if self.face else None}"
        )

    @property
    def ready(self) -> bool:
        """Whether a store is open."""
        return self.store is not None

    # ---------------------------------------------------------------- contacts

    def contacts(self) -> list[Contact]:
        """Everyone (including `self` when enrolled)."""
        return self.store.list_contacts() if self.store is not None else []

    def get(self, contact_id: str) -> Contact | None:
        """One contact."""
        return self.store.get(contact_id) if self.store is not None else None

    def create(
        self,
        name: str,
        *,
        aliases: Iterable[str] = (),
        language: str | None = None,
        is_owner: bool = False,
        notes: str = "",
        contact_id: str | None = None,
    ) -> Contact:
        """Add a household member under a free id (never overwrites one; `update` edits)."""
        assert self.store is not None
        contact = Contact(
            contact_id or self.store.free_id(slugify(name)),
            name,
            tuple(aliases),
            notes,
            language,
            is_owner,
        )
        self._changed()
        return self.store.upsert(contact)

    def update(self, contact: Contact) -> Contact:
        """Replace a profile."""
        assert self.store is not None
        self._changed()
        return self.store.upsert(contact)

    def delete(self, contact_id: str) -> bool:
        """Remove a contact."""
        self._changed()
        return self.store.delete(contact_id) if self.store is not None else False

    def _changed(self) -> None:
        self._names.clear()
        self._counts = None

    def bind_remote(self, contact_id: str, channel: str, remote_id: str) -> Contact | None:
        """Attach a Telegram chat id / WeChat user id to a contact."""
        contact = self.get(contact_id)
        if contact is None or self.store is None:
            return None
        remote = dict(contact.remote_ids)
        remote[channel] = remote_id.removeprefix("tg:").removeprefix("wx:")
        self._changed()
        return self.store.upsert(
            Contact(
                contact.id,
                contact.name,
                contact.aliases,
                contact.notes,
                contact.language,
                contact.is_owner,
                remote,
                contact.created_ts,
            )
        )

    def resolve_speaker(self, speaker: str) -> str:
        """The contact a speaker id stands for, or the id unchanged.

        Remote ids (`tg:42`, `wx:u1`) bound to a contact, the dashboard's `owner` once an owner
        contact exists, and a `person:n` befriended while this process runs (its turn may still
        be going) resolve to that contact.
        """
        if self.store is None:
            return speaker
        if speaker in self._promoted:
            return self._promoted[speaker]
        if speaker == OWNER_ALIAS:
            owner = self.owner()
            return owner.id if owner is not None else speaker
        for prefix, channel in (("tg:", "telegram"), ("wx:", "wechat")):
            if speaker.startswith(prefix):
                contact = self.store.by_remote_id(channel, speaker[len(prefix) :])
                return contact.id if contact is not None else speaker
        return speaker

    def touch(self, contact_id: str, now: float | None = None, force: bool = False) -> bool:
        """Record that a contact was just identified (rate-limited to one write per 10 s)."""
        if self.store is None or not contact_id or is_person(contact_id) or contact_id == SELF_ID:
            return False
        now = time.time() if now is None else now
        last = self._touched.get(contact_id)
        if not force and last is not None and now - last < 10.0:
            return False
        if self.store.get(contact_id) is None:
            return False
        self._touched[contact_id] = now
        self.store.touch_contact(contact_id, now)
        return True

    def last_seen(self, contact_id: str) -> float | None:
        """When the contact was last identified by voice or face (None = never recorded)."""
        contact = self.get(contact_id)
        return contact.last_seen_ts if contact is not None else None

    def display_name(self, speaker: str) -> str:
        """Human label for prompts and the dashboard (`person:n` stays as is: not named yet).

        Kept `NAME_TTL_S` (any change to a contact drops the cache): the Live page and every
        prompt ask for it, and a lookup is a SQL query.
        """
        now = time.monotonic()
        cached = self._names.get(speaker)
        if cached is not None and now - cached[0] < NAME_TTL_S:
            return cached[1]
        contact = self.get(speaker)
        name = (
            speaker
            if contact is None
            else f"{contact.name}{' (owner)' if contact.is_owner else ''}"
        )
        self._names[speaker] = (now, name)
        return name

    def owner(self) -> Contact | None:
        """The owner contact, if any."""
        return next((c for c in self.contacts() if c.is_owner), None)

    def new_guest(self) -> str:
        """A fresh guest id."""
        self._guest_counter += 1
        return f"guest:{self._guest_counter}"

    # ------------------------------------------------------------------- voice

    def identify_voice(self, clip: AudioClip) -> Identification:
        """Who is speaking (synchronous; call in a thread)."""
        if self.store is None or self.voice is None:
            return Identification(None, 0.0, "voice", 0.0)
        centroids = self.store.embeddings("voice", self.voice.model)
        result = self.voice.identify(clip, centroids)
        self.last_voice = result
        self.last_voice_at = time.time()
        return result

    def identify_vector(self, vector: Vector) -> Identification:
        """`identify_voice` for an embedding the caller already has (it also keeps it)."""
        if self.store is None or self.voice is None:
            return Identification(None, 0.0, "voice", 0.0)
        centroids = self.store.embeddings("voice", self.voice.model)
        if not centroids:
            return Identification(None, 0.0, "voice", self.voice.configuration.threshold)
        result = self.voice.match(vector, centroids)
        self.last_voice = result
        self.last_voice_at = time.time()
        return result

    def learn_voice(self, contact_id: str, vector: Vector) -> bool:
        """Fold an utterance identified as a contact into the contact's voice (block #80)."""
        if (
            self.store is None
            or self.voice is None
            or not contact_id
            or is_person(contact_id)
            or contact_id == SELF_ID
            or self.store.get(contact_id) is None
        ):
            return False
        self.store.add_sample(
            contact_id, "voice", self.voice.model, vector, max_weight=VOICE_LEARN_WEIGHT
        )
        return True

    def embed_voice(self, clip: AudioClip) -> Vector | None:
        """Unit-norm voice embedding of a clip, or None when too short or no model is loaded."""
        if self.voice is None or clip.duration_s < self.voice.configuration.min_clip_s:
            return None
        try:
            return self.voice.embed(clip)
        except Exception as exc:
            Log.debug(f"embed voice: {exc!r}")
            return None

    @property
    def voice_threshold(self) -> float:
        """Cosine score above which two clips count as the same voice."""
        return self.voice.configuration.threshold if self.voice is not None else 0.5

    @staticmethod
    def voice_similarity(a: Vector, b: Vector) -> float:
        """Cosine similarity of two embeddings."""
        return cosine(a, b)

    # ------------------------------------------------------------------ people

    READY_UTTERANCES = 6
    READY_SESSIONS = 2
    READY_UTTERANCES_ONE_SESSION = 8
    READY_FACES = 3
    ASK_AGAIN_DAYS = 1.0
    DECLINE_DAYS = 7.0

    def new_person(self, vector: Vector) -> str:
        """Start tracking an unknown voice; returns its `person:n` id."""
        assert self.store is not None and self.voice is not None
        person_id = self.store.next_person_id()
        self.store.create_person(person_id)
        self.store.add_sample(person_id, "voice", self.voice.model, vector)
        self.store.touch_person(person_id, utterance=True)  # the utterance that revealed them
        Log.info(f"new person {person_id}")
        return person_id

    def fold_person(
        self,
        person_id: str,
        *,
        voice: Vector | None = None,
        face: Vector | None = None,
        session: str | None = None,
    ) -> Person | None:
        """Add a voice / face sample to a person and count the utterance and session."""
        if self.store is None or self.store.person(person_id) is None:
            return None
        if voice is not None and self.voice is not None:
            self.store.add_sample(person_id, "voice", self.voice.model, voice)
        if face is not None and self.face is not None:
            self.store.add_sample(person_id, "face", self.face.model, face)
        return self.store.touch_person(person_id, utterance=voice is not None, session=session)

    def person(self, person_id: str) -> Person | None:
        """One person seen."""
        return self.store.person(person_id) if self.store is not None else None

    def people(self) -> list[Person]:
        """Everyone heard but not befriended."""
        return self.store.people() if self.store is not None else []

    def person_ready(self, person_id: str, now: float | None = None) -> bool:
        """Enough samples to be asked for a name, and not asked / declined recently."""
        person = self.person(person_id)
        if person is None:
            return False
        ts = time.time() if now is None else now
        if person.declined_ts and ts - person.declined_ts < self.DECLINE_DAYS * 86400.0:
            return False
        if person.ready_ts and ts - person.ready_ts < self.ASK_AGAIN_DAYS * 86400.0:
            return False
        if person.asked_ts and ts - person.asked_ts < self.ASK_AGAIN_DAYS * 86400.0:
            return False
        enough_voice = (
            person.utterances >= self.READY_UTTERANCES and person.sessions >= self.READY_SESSIONS
        ) or person.utterances >= self.READY_UTTERANCES_ONE_SESSION
        return enough_voice

    def mark_person(self, person_id: str, what: str) -> None:
        """`ready`, `asked` or `declined`."""
        if self.store is not None:
            self.store.mark_person(person_id, f"{what}_ts")

    def promote_person(
        self, person_id: str, name: str, language: str | None = None
    ) -> Contact | None:
        """Befriend: the person becomes a contact and keeps every sample collected so far."""
        if self.store is None or self.store.person(person_id) is None:
            return None
        contact = self.create(name, language=language)
        moved = self.store.move_embeddings(person_id, contact.id)
        self.store.delete_person(person_id, keep_embeddings=True)
        self._changed()
        self._promoted[person_id] = contact.id
        self.touch(contact.id, force=True)  # they are here right now: no greeting for a while
        Log.info(f"befriended {person_id} as {contact.id} ({moved} centroid(s) moved)")
        return contact

    def merge_person(self, person_id: str) -> str | None:
        """Hand an unnamed person to the contact whose voice they are; the contact id or None.

        Only with `MERGE_MIN_UTTERANCES` behind the person's centroid, a score of at least
        `MERGE_SCORE` against the contact's and a `MERGE_MARGIN` over the next contact. Voice
        and face samples move into the contact's centroids (weighted by their counts) and the
        person id resolves to the contact for the rest of this run.
        """
        if self.store is None or self.voice is None or not is_person(person_id):
            return None
        person = self.store.person(person_id)
        mine = self.store.embeddings("voice", self.voice.model, person_id)
        if person is None or not mine or person.utterances < MERGE_MIN_UTTERANCES:
            return None
        scored = sorted(
            (
                (e.contact_id, cosine(mine[0].vector, e.vector))
                for e in self.store.embeddings("voice", self.voice.model)
                if not is_person(e.contact_id) and e.contact_id != SELF_ID
            ),
            key=lambda item: -item[1],
        )
        if not scored or scored[0][1] < MERGE_SCORE:
            return None
        if len(scored) > 1 and scored[0][1] - scored[1][1] < MERGE_MARGIN:
            return None
        contact_id, score = scored[0]
        if self.store.get(contact_id) is None:
            return None
        self.store.move_embeddings(person_id, contact_id)
        self.store.delete_person(person_id, keep_embeddings=True)
        self._promoted[person_id] = contact_id
        self._changed()
        Log.info(
            f"{person_id} is {contact_id}'s voice ({score:.2f}, {person.utterances} utterances): merged"
        )
        return contact_id

    def merge_people(self) -> list[tuple[str, str]]:
        """`merge_person` for everyone seen (at start): the (person, contact) pairs merged."""
        merged: list[tuple[str, str]] = []
        for person in self.people():
            contact_id = self.merge_person(person.id)
            if contact_id is not None:
                merged.append((person.id, contact_id))
        return merged

    def forget_person(self, person_id: str) -> bool:
        """Drop a person and their samples."""
        return self.store.delete_person(person_id) if self.store is not None else False

    def prune_people(self, days: float = 7.0) -> int:
        """Forget people not seen for `days` (run daily by `start()`)."""
        return self.store.prune_people(days) if self.store is not None else 0

    def enroll_voice(self, contact_id: str, clips: Iterable[AudioClip]) -> int:
        """Fold utterances into the contact's voice centroid; returns how many were used."""
        assert self.store is not None and self.voice is not None
        used = 0
        for clip in clips:
            if clip.duration_s < self.voice.configuration.enroll_min_clip_s:
                continue
            try:
                vector = self.voice.embed(clip)
            except Exception as exc:
                Log.warning(f"enroll voice: {exc!r}")
                continue
            self.store.add_sample(contact_id, "voice", self.voice.model, vector)
            used += 1
        Log.info(f"voice enrollment for {contact_id}: {used} clip(s)")
        return used

    def enroll_self(self, clips: Iterable[AudioClip]) -> int:
        """The robot's own TTS voice."""
        assert self.store is not None
        if self.store.get(SELF_ID) is None:
            self.store.upsert(
                Contact(
                    SELF_ID,
                    "Bobby (self)",
                    ("robot", "bobby"),
                    "the robot's own TTS voice",
                    None,
                    False,
                )
            )
        self.store.clear_embeddings(SELF_ID, "voice")
        return self.enroll_voice(SELF_ID, clips)

    def self_enrolled(self) -> bool:
        """Whether the robot's voice is known."""
        return bool(
            self.store and self.voice and self.store.embeddings("voice", self.voice.model, SELF_ID)
        )

    # -------------------------------------------------------------------- face

    def identify_face(self, frame: Frame) -> tuple[Identification, DetectedFace | None]:
        """Who is in front of the camera (largest face); dark frames are gamma-lifted first."""
        if self.store is None or self.face is None:
            return Identification(None, 0.0, "face", 0.0), None
        centroids = self.store.embeddings("face", self.face.model)
        result = self.face.identify(brighten_frame(frame), centroids)
        self.last_face = result[0]
        self.last_face_at = time.time()
        return result

    def enroll_face(self, contact_id: str, frames: Iterable[Frame]) -> int:
        """Fold frames (largest face each) into the contact's face centroid."""
        assert self.store is not None and self.face is not None
        used = 0
        for frame in frames:
            try:
                frame = brighten_frame(frame)
                faces = self.face.detect(frame)
                if not faces:
                    continue
                vector = self.face.embed(frame, faces[0])
            except Exception as exc:
                Log.warning(f"enroll face: {exc!r}")
                continue
            self.store.add_sample(contact_id, "face", self.face.model, vector)
            used += 1
        Log.info(f"face enrollment for {contact_id}: {used} frame(s)")
        return used

    # --------------------------------------------------------------- reporting

    def live(self) -> dict[str, Any]:
        """Vital signs for the Live page: the latest identifications and the counts.

        Members, people seen and people ready to befriend come from SQL at most every
        `COUNTS_TTL_S`; everything else is in memory.
        """
        now = time.monotonic()
        if self.store is not None and (
            self._counts is None or now - self._counts[0] > COUNTS_TTL_S
        ):
            people = self.people()
            members = [c for c in self.contacts() if c.id != SELF_ID]
            self._counts = (
                now,
                {
                    "members": len(members),
                    "owner": next((c.name for c in members if c.is_owner), None),
                    "people": len(people),
                    "ready": sum(1 for p in people if self.person_ready(p.id)),
                    "self_enrolled": self.self_enrolled(),
                },
            )

        def ident(result: Identification | None, at: float) -> dict[str, Any] | None:
            if result is None or not at:
                return None
            return {
                "contact": result.contact_id,
                "name": self.display_name(result.contact_id) if result.contact_id else None,
                "score": round(float(result.score), 3),
                "ago_s": round(time.time() - at, 1),
            }

        return {
            "ready": self.store is not None,
            "voice": ident(self.last_voice, self.last_voice_at),
            "face": ident(self.last_face, self.last_face_at),
            **(self._counts[1] if self._counts is not None else {}),
        }

    def snapshot(self) -> dict[str, Any]:
        """Dashboard state."""
        return {
            "contacts": self.store.summary() if self.store is not None else [],
            "people": [p.as_dict() for p in self.people()],
            "self_enrolled": self.self_enrolled(),
            "last_voice": None
            if self.last_voice is None
            else {
                "contact": self.last_voice.contact_id,
                "score": self.last_voice.score,
                "candidates": list(self.last_voice.candidates),
            },
            "last_face": None
            if self.last_face is None
            else {"contact": self.last_face.contact_id, "score": self.last_face.score},
            "voice_threshold": self.voice.configuration.threshold if self.voice else None,
            "face_threshold": self.face.configuration.threshold if self.face else None,
        }


def frames_from_bgr(frames: Iterable[np.ndarray]) -> list[Frame]:
    """Type helper for callers holding raw arrays."""
    return [np.asarray(f, dtype=np.uint8) for f in frames]
