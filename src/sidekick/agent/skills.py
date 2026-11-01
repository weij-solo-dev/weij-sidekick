"""sidekick.agent.skills — Markdown skills stored in SQLite, injected by description, read on demand

Overview
    A skill is an OpenClaw-style Markdown document with a `name` / `description` header and a
    body of instructions. Agents see the list of descriptions in their prompt and call
    `skill_read` for the body when relevant. Skills come from users (dashboard, tools) or
    extensions (`origin = extension:<name>`), live in `skills_v1.db`, and are CRUD-able by tools.
Design
    Header format: a leading `---` block with `name:` and `description:` lines; anything else is
    the body. `parse_markdown()` is tolerant (a `# Title` heading also works as the name).
    Disabled skills are kept but not injected.
Depends on
    sidekick.log, sidekick.storage.

See Also
--------
    AGENTS.md "Agent swarm" (Skills).

"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from sidekick.log import Log
from sidekick.storage import Database

from .schemas import Skill

MIGRATIONS = [
    """
    CREATE TABLE IF NOT EXISTS skills (
        name TEXT PRIMARY KEY, description TEXT NOT NULL, body TEXT NOT NULL,
        origin TEXT NOT NULL, enabled INTEGER NOT NULL, updated_ts REAL NOT NULL
    );
    """
]

_HEADER = re.compile(r"\A\s*---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_markdown(text: str) -> tuple[str, str, str]:
    """`(name, description, body)` from a skill document."""
    name = description = ""
    body = text
    match = _HEADER.match(text)
    if match:
        for line in match.group(1).splitlines():
            key, _, value = line.partition(":")
            if key.strip().lower() == "name":
                name = value.strip()
            elif key.strip().lower() == "description":
                description = value.strip()
        body = text[match.end() :]
    if not name:
        heading = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        if heading:
            name = heading.group(1).strip()
    if not description:
        first = next(
            (
                line.strip()
                for line in body.splitlines()
                if line.strip() and not line.startswith("#")
            ),
            "",
        )
        description = first[:140]
    return name, description, body.strip()


def render_markdown(skill: Skill) -> str:
    """Skill back to its document form."""
    return f"---\nname: {skill.name}\ndescription: {skill.description}\n---\n{skill.body}\n"


# A skill this short is inlined in the prompt instead of read with a tool round (block #71).
INLINE_SKILL_CHARS = 1200


class SkillStore:
    """CRUD over skills."""

    def __init__(self, path: Path) -> None:
        self.db = Database(path, MIGRATIONS)

    @staticmethod
    def _row(row: Any) -> Skill:
        return Skill(
            name=row["name"],
            description=row["description"],
            body=row["body"],
            origin=row["origin"],
            enabled=bool(row["enabled"]),
            updated_ts=row["updated_ts"],
        )

    def upsert(self, skill: Skill) -> Skill:
        """Create or replace."""
        skill = Skill(
            skill.name.strip(),
            skill.description.strip(),
            skill.body.strip(),
            skill.origin,
            skill.enabled,
            time.time(),
        )
        if not skill.name:
            raise ValueError("skill needs a name")
        self.db.execute(
            "INSERT INTO skills (name, description, body, origin, enabled, updated_ts) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(name) DO UPDATE SET description = excluded.description, body = excluded.body,"
            " origin = excluded.origin, enabled = excluded.enabled, updated_ts = excluded.updated_ts",
            (
                skill.name,
                skill.description,
                skill.body,
                skill.origin,
                int(skill.enabled),
                skill.updated_ts,
            ),
        )
        Log.info(f"skill saved: {skill.name} ({skill.origin})")
        return skill

    def upsert_markdown(self, text: str, origin: str = "user") -> Skill:
        """Create or replace from a document."""
        name, description, body = parse_markdown(text)
        return self.upsert(Skill(name, description, body, origin))

    def get(self, name: str) -> Skill | None:
        """One skill."""
        rows = self.db.query("SELECT * FROM skills WHERE name = ?", (name,))
        return self._row(rows[0]) if rows else None

    def delete(self, name: str) -> bool:
        """Remove."""
        return self.db.execute("DELETE FROM skills WHERE name = ?", (name,)) > 0

    def delete_origin(self, origin: str) -> int:
        """Remove every skill an extension contributed."""
        return self.db.execute("DELETE FROM skills WHERE origin = ?", (origin,))

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """Toggle."""
        return (
            self.db.execute("UPDATE skills SET enabled = ? WHERE name = ?", (int(enabled), name))
            > 0
        )

    def list(self, enabled_only: bool = False) -> list[Skill]:
        """All skills by name."""
        sql = (
            "SELECT * FROM skills"
            + (" WHERE enabled = 1" if enabled_only else "")
            + " ORDER BY name"
        )
        return [self._row(r) for r in self.db.query(sql)]

    def descriptions_block(
        self, allow: tuple[str, ...] = ("*",), inline_chars: int = INLINE_SKILL_CHARS
    ) -> str:
        """Prompt block listing available skills; a short skill's body comes along.

        A body of at most `inline_chars` rides in the prompt (a cached prefix), so a story or a
        briefing starts without a `skill_read` round first (about 2 s, block #71); longer
        skills are still read on demand.
        """
        skills = [s for s in self.list(enabled_only=True) if "*" in allow or s.name in allow]
        if not skills:
            return ""
        inline = [s for s in skills if len(s.body) <= inline_chars]
        lines = [
            f"- {s.name}: {s.description}" + (" (below, no need to read it)" if s in inline else "")
            for s in skills
        ]
        block = "Skills you can read with skill_read(name) when relevant:\n" + "\n".join(lines)
        for skill in inline:
            block += f"\n\nSkill {skill.name}:\n{skill.body.strip()}"
        return block
