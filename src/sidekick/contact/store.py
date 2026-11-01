"""sidekick.contact.store — contacts and embeddings in `contact_v1.db`

Overview
    Two tables: `contacts` (profile) and `embeddings` (one row per enrolled vector, voice or face,
    with the model name so a model change invalidates the right rows). Enrollment averages new
    utterances into the stored centroid per (contact, kind, model) and counts the samples.
Design
    SQLite open-per-operation through `Database` (invariant 7). Vectors are float32 blobs.
    `free_id` gives a new contact an id nobody holds (`阿明_2`), so `upsert` overwrites only
    when a caller edits a contact it already has.
    Matching is done in Python over all stored centroids (a household has a handful), so no
    vector index is needed.
Depends on
    sidekick.log, sidekick.storage, numpy.

See Also
--------
    AGENTS.md "Contact and identification".

"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from sidekick.log import Log
from sidekick.storage import Database

from .schemas import (
    OWNER_ALIAS,
    PERSON_PREFIX,
    SELF_ID,
    Contact,
    Embedding,
    Person,
    Vector,
    normalized,
    slugify,
)

MIGRATIONS = [
    """
    CREATE TABLE IF NOT EXISTS contacts (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, aliases TEXT, notes TEXT, language TEXT,
        is_owner INTEGER NOT NULL, remote_ids TEXT, created_ts REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS embeddings (
        id INTEGER PRIMARY KEY AUTOINCREMENT, contact_id TEXT NOT NULL, kind TEXT NOT NULL,
        model TEXT NOT NULL, vector BLOB NOT NULL, dim INTEGER NOT NULL, samples INTEGER NOT NULL,
        ts REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS embeddings_contact ON embeddings(contact_id, kind, model);
    """,
    """
    CREATE TABLE IF NOT EXISTS people (
        id TEXT PRIMARY KEY, created_ts REAL NOT NULL, last_seen_ts REAL NOT NULL,
        sessions INTEGER NOT NULL DEFAULT 0, utterances INTEGER NOT NULL DEFAULT 0,
        asked_ts REAL, declined_ts REAL, ready_ts REAL, last_session TEXT
    );
    CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
    """,
    """
    ALTER TABLE contacts ADD COLUMN last_seen_ts REAL;
    """,
]


class ContactStore:
    """CRUD over contacts and their embeddings."""

    def __init__(self, path: Path) -> None:
        self.db = Database(path, MIGRATIONS)

    # ---------------------------------------------------------------- contacts

    @staticmethod
    def _contact(row: Any) -> Contact:
        return Contact(
            id=row["id"],
            name=row["name"],
            aliases=tuple(json.loads(row["aliases"] or "[]")),
            notes=row["notes"] or "",
            language=row["language"],
            is_owner=bool(row["is_owner"]),
            remote_ids=json.loads(row["remote_ids"] or "{}"),
            created_ts=row["created_ts"],
            last_seen_ts=row["last_seen_ts"],
        )

    def upsert(self, contact: Contact) -> Contact:
        """Create or replace a contact."""
        if not contact.id:
            contact = Contact(
                slugify(contact.name),
                contact.name,
                contact.aliases,
                contact.notes,
                contact.language,
                contact.is_owner,
                contact.remote_ids,
                contact.created_ts,
                contact.last_seen_ts,
            )
        self.db.execute(
            "INSERT INTO contacts (id, name, aliases, notes, language, is_owner, remote_ids, created_ts,"
            " last_seen_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET name = excluded.name, aliases = excluded.aliases, notes = excluded.notes,"
            " language = excluded.language, is_owner = excluded.is_owner, remote_ids = excluded.remote_ids",
            (
                contact.id,
                contact.name,
                json.dumps(list(contact.aliases), ensure_ascii=False),
                contact.notes,
                contact.language,
                int(contact.is_owner),
                json.dumps(contact.remote_ids, ensure_ascii=False),
                contact.created_ts,
                contact.last_seen_ts,
            ),
        )
        Log.info(f"contact saved: {contact.id} ({contact.name})")
        return contact

    def touch_contact(self, contact_id: str, now: float | None = None) -> None:
        """Refresh `last_seen_ts` (voice or face identified the person)."""
        self.db.execute(
            "UPDATE contacts SET last_seen_ts = ? WHERE id = ?",
            (time.time() if now is None else now, contact_id),
        )

    def get(self, contact_id: str) -> Contact | None:
        """One contact."""
        rows = self.db.query("SELECT * FROM contacts WHERE id = ?", (contact_id,))
        return self._contact(rows[0]) if rows else None

    def free_id(self, base: str) -> str:
        """`base`, or `base_2`, `base_3`, … when it is taken or reserved (`self`, `owner`)."""
        candidate, n = base, 1
        while candidate in (SELF_ID, OWNER_ALIAS) or self.get(candidate) is not None:
            n += 1
            candidate = f"{base}_{n}"
        return candidate

    def by_name(self, name: str) -> Contact | None:
        """Match on name or alias (case-insensitive)."""
        needle = name.strip().lower()
        for contact in self.list_contacts():
            if (
                contact.name.lower() == needle
                or needle in (a.lower() for a in contact.aliases)
                or contact.id == needle
            ):
                return contact
        return None

    def by_remote_id(self, channel: str, remote_id: str) -> Contact | None:
        """The contact bound to a channel id (`telegram`, `42`)."""
        for contact in self.list_contacts():
            if contact.remote_ids.get(channel) == remote_id:
                return contact
        return None

    def list_contacts(self) -> list[Contact]:
        """Every contact, owner first then by name."""
        rows = self.db.query("SELECT * FROM contacts ORDER BY is_owner DESC, name")
        return [self._contact(r) for r in rows]

    def delete(self, contact_id: str) -> bool:
        """Remove a contact and its embeddings."""
        self.db.execute("DELETE FROM embeddings WHERE contact_id = ?", (contact_id,))
        return self.db.execute("DELETE FROM contacts WHERE id = ?", (contact_id,)) > 0

    # -------------------------------------------------------------- embeddings

    @staticmethod
    def _embedding(row: Any) -> Embedding:
        vector = np.frombuffer(row["vector"], dtype=np.float32).copy()
        return Embedding(
            row["contact_id"],
            row["kind"],
            row["model"],
            vector,
            id=row["id"],
            ts=row["ts"],
            samples=row["samples"],
        )

    def embeddings(self, kind: str, model: str, contact_id: str | None = None) -> list[Embedding]:
        """Stored centroids for a kind and model."""
        if contact_id:
            rows = self.db.query(
                "SELECT * FROM embeddings WHERE kind = ? AND model = ? AND contact_id = ?",
                (kind, model, contact_id),
            )
        else:
            rows = self.db.query(
                "SELECT * FROM embeddings WHERE kind = ? AND model = ?", (kind, model)
            )
        return [self._embedding(r) for r in rows]

    def add_sample(
        self,
        contact_id: str,
        kind: str,
        model: str,
        vector: Vector,
        max_weight: int | None = None,
    ) -> Embedding:
        """Fold one sample into the contact's centroid (creating it when missing).

        `max_weight` caps the weight of the centroid against the new sample (a running mean that
        keeps learning: with 50, a new room or hour still moves it by 2 %); `samples` keeps the
        true count.
        """
        vector = normalized(np.asarray(vector, dtype=np.float32))
        existing = self.embeddings(kind, model, contact_id)
        if existing:
            current = existing[0]
            weight = current.samples if max_weight is None else min(current.samples, max_weight)
            merged = normalized(
                ((current.vector * weight + vector) / (weight + 1)).astype(np.float32)
            )
            self.db.execute(
                "UPDATE embeddings SET vector = ?, samples = ? WHERE id = ?",
                (merged.tobytes(), current.samples + 1, current.id),
            )
            return Embedding(
                contact_id,
                current.kind,
                model,
                merged,
                id=current.id,
                ts=current.ts,
                samples=current.samples + 1,
            )
        self.db.execute(
            "INSERT INTO embeddings (contact_id, kind, model, vector, dim, samples, ts) VALUES (?, ?, ?, ?, ?, 1, ?)",
            (
                contact_id,
                kind,
                model,
                vector.tobytes(),
                int(vector.shape[0]),
                __import__("time").time(),
            ),
        )
        return self.embeddings(kind, model, contact_id)[0]

    def set_embedding(
        self, contact_id: str, kind: str, model: str, vector: Vector, samples: int
    ) -> None:
        """Replace the centroid outright."""
        self.db.execute(
            "DELETE FROM embeddings WHERE contact_id = ? AND kind = ? AND model = ?",
            (contact_id, kind, model),
        )
        vector = normalized(np.asarray(vector, dtype=np.float32))
        self.db.execute(
            "INSERT INTO embeddings (contact_id, kind, model, vector, dim, samples, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                contact_id,
                kind,
                model,
                vector.tobytes(),
                int(vector.shape[0]),
                samples,
                __import__("time").time(),
            ),
        )

    def clear_embeddings(self, contact_id: str, kind: str | None = None) -> int:
        """Forget a contact's voice or face."""
        if kind:
            return self.db.execute(
                "DELETE FROM embeddings WHERE contact_id = ? AND kind = ?", (contact_id, kind)
            )
        return self.db.execute("DELETE FROM embeddings WHERE contact_id = ?", (contact_id,))

    # ------------------------------------------------------------------ people

    def _person(self, row: Any) -> Person:
        counts = {
            r["kind"]: int(r["samples"])
            for r in self.db.query(
                "SELECT kind, samples FROM embeddings WHERE contact_id = ?", (row["id"],)
            )
        }
        return Person(
            id=row["id"],
            created_ts=row["created_ts"],
            last_seen_ts=row["last_seen_ts"],
            sessions=int(row["sessions"]),
            utterances=int(row["utterances"]),
            voice_samples=counts.get("voice", 0),
            face_samples=counts.get("face", 0),
            asked_ts=row["asked_ts"],
            declined_ts=row["declined_ts"],
            ready_ts=row["ready_ts"],
            last_session=row["last_session"],
        )

    def next_person_id(self) -> str:
        """A fresh `person:n` (the counter never reuses a number)."""
        with self.db.transaction() as conn:
            row = conn.execute("SELECT value FROM counters WHERE name = 'person'").fetchone()
            value = int(row[0]) + 1 if row else 1
            conn.execute(
                "INSERT INTO counters (name, value) VALUES ('person', ?) "
                "ON CONFLICT(name) DO UPDATE SET value = excluded.value",
                (value,),
            )
        return f"{PERSON_PREFIX}{value}"

    def create_person(self, person_id: str, now: float | None = None) -> Person:
        """Insert the metadata row (embeddings are added separately)."""
        ts = time.time() if now is None else now
        self.db.execute(
            "INSERT OR IGNORE INTO people (id, created_ts, last_seen_ts) VALUES (?, ?, ?)",
            (person_id, ts, ts),
        )
        person = self.person(person_id)
        assert person is not None
        return person

    def person(self, person_id: str) -> Person | None:
        """One person."""
        rows = self.db.query("SELECT * FROM people WHERE id = ?", (person_id,))
        return self._person(rows[0]) if rows else None

    def people(self) -> list[Person]:
        """Everyone seen but not befriended, most recent first."""
        return [
            self._person(r)
            for r in self.db.query("SELECT * FROM people ORDER BY last_seen_ts DESC")
        ]

    def touch_person(
        self,
        person_id: str,
        *,
        utterance: bool = False,
        session: str | None = None,
        now: float | None = None,
    ) -> Person | None:
        """Count an utterance and / or a new session; refresh `last_seen`."""
        ts = time.time() if now is None else now
        current = self.person(person_id)
        if current is None:
            return None
        new_session = session is not None and session != current.last_session
        self.db.execute(
            "UPDATE people SET last_seen_ts = ?, utterances = utterances + ?, "
            "sessions = sessions + ?, last_session = COALESCE(?, last_session) WHERE id = ?",
            (ts, 1 if utterance else 0, 1 if new_session else 0, session, person_id),
        )
        return self.person(person_id)

    def mark_person(self, person_id: str, field: str, now: float | None = None) -> None:
        """Stamp `asked_ts`, `declined_ts` or `ready_ts`."""
        if field not in ("asked_ts", "declined_ts", "ready_ts"):
            raise ValueError(field)
        self.db.execute(
            f"UPDATE people SET {field} = ? WHERE id = ?",
            (time.time() if now is None else now, person_id),
        )

    def delete_person(self, person_id: str, keep_embeddings: bool = False) -> bool:
        """Remove the row (and its embeddings unless they were moved to a contact)."""
        if not keep_embeddings:
            self.clear_embeddings(person_id)
        return self.db.execute("DELETE FROM people WHERE id = ?", (person_id,)) > 0

    def move_embeddings(self, person_id: str, contact_id: str) -> int:
        """Hand a person's centroids to a contact (promotion); merges into existing ones."""
        moved = 0
        for row in self.db.query("SELECT * FROM embeddings WHERE contact_id = ?", (person_id,)):
            embedding = self._embedding(row)
            existing = self.embeddings(embedding.kind, embedding.model, contact_id)
            if existing:
                current = existing[0]
                total = current.samples + embedding.samples
                merged = normalized(
                    (
                        (current.vector * current.samples + embedding.vector * embedding.samples)
                        / max(1, total)
                    ).astype(np.float32)
                )
                self.db.execute(
                    "UPDATE embeddings SET vector = ?, samples = ? WHERE id = ?",
                    (merged.tobytes(), total, current.id),
                )
                self.db.execute("DELETE FROM embeddings WHERE id = ?", (embedding.id,))
            else:
                self.db.execute(
                    "UPDATE embeddings SET contact_id = ? WHERE id = ?", (contact_id, embedding.id)
                )
            moved += 1
        return moved

    def prune_people(self, days: float, now: float | None = None) -> int:
        """Forget people not seen for `days`."""
        cutoff = (time.time() if now is None else now) - days * 86400.0
        stale = [
            r["id"]
            for r in self.db.query("SELECT id FROM people WHERE last_seen_ts < ?", (cutoff,))
        ]
        for person_id in stale:
            self.delete_person(person_id)
        return len(stale)

    def summary(self) -> list[dict[str, Any]]:
        """Contacts with their enrollment counts (dashboard)."""
        out = []
        for contact in self.list_contacts():
            rows = self.db.query(
                "SELECT kind, model, samples FROM embeddings WHERE contact_id = ?", (contact.id,)
            )
            out.append(
                {
                    "id": contact.id,
                    "name": contact.name,
                    "aliases": list(contact.aliases),
                    "notes": contact.notes,
                    "language": contact.language,
                    "is_owner": contact.is_owner,
                    "remote_ids": contact.remote_ids,
                    "voice_samples": sum(r["samples"] for r in rows if r["kind"] == "voice"),
                    "face_samples": sum(r["samples"] for r in rows if r["kind"] == "face"),
                }
            )
        return out
