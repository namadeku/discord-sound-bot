"""Swear word counting and persistent per-user statistics."""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from discord_sound_bot.config import write_json_atomic

# Latin letters people use to dodge filters ("xyй") mapped to Cyrillic look-alikes.
_LOOKALIKES = str.maketrans("aeopcxykmtbh3ё", "аеорсхукмтвнзе")
_WORD_RE = re.compile(r"\w+")


def normalize(text: str) -> str:
    return text.lower().translate(_LOOKALIKES)


def count_swears(text: str, words: Iterable[str]) -> Counter[str]:
    """Count tokens containing any of the given word roots.

    Each token counts once, attributed to the longest matching root, so roots
    like "бля" and "блять" don't double count.
    """
    roots = sorted(
        {normalize(w.strip()): w.strip() for w in words if w.strip()}.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    result: Counter[str] = Counter()
    if not roots:
        return result
    for token in _WORD_RE.findall(normalize(text)):
        for root, original in roots:
            if root in token:
                result[original] += 1
                break
    return result


@dataclass
class GuildStats:
    counts: dict[int, Counter[str]] = field(default_factory=dict)
    names: dict[int, str] = field(default_factory=dict)
    last_report_at: float = field(default_factory=time.time)


class SwearStats:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.guilds: dict[int, GuildStats] = {}
        self._load()

    def guild(self, guild_id: int) -> GuildStats:
        return self.guilds.setdefault(guild_id, GuildStats())

    def add(self, guild_id: int, user_id: int, user_name: str, counts: Counter[str]) -> None:
        if not counts:
            return
        stats = self.guild(guild_id)
        stats.counts.setdefault(user_id, Counter()).update(counts)
        stats.names[user_id] = user_name
        self.save()

    def reset(self, guild_id: int) -> None:
        stats = self.guild(guild_id)
        stats.counts.clear()
        stats.last_report_at = time.time()
        self.save()

    def mark_reported(self, guild_id: int, *, reset: bool) -> None:
        if reset:
            self.reset(guild_id)
        else:
            self.guild(guild_id).last_report_at = time.time()
            self.save()

    def format_report(
        self, guild_id: int, resolve_name: Callable[[int], str | None] | None = None
    ) -> str:
        stats = self.guild(guild_id)
        per_user = {uid: sum(c.values()) for uid, c in stats.counts.items() if sum(c.values())}
        if not per_user:
            return "📊 **Статистика мата**\nНикто не ругался. Пока что."

        def name(uid: int) -> str:
            resolved = resolve_name(uid) if resolve_name else None
            return resolved or stats.names.get(uid) or f"<{uid}>"

        medals = ["🥇", "🥈", "🥉"]
        lines = ["📊 **Статистика мата**", f"Всего: **{sum(per_user.values())}**", ""]
        ranked = sorted(per_user.items(), key=lambda item: item[1], reverse=True)
        for place, (uid, total) in enumerate(ranked):
            prefix = medals[place] if place < len(medals) else f"{place + 1}."
            top_words = ", ".join(f"{w}: {n}" for w, n in stats.counts[uid].most_common(3))
            lines.append(f"{prefix} **{name(uid)}** — {total} ({top_words})")

        totals: Counter[str] = Counter()
        for c in stats.counts.values():
            totals.update(c)
        lines += ["", "По словам: " + ", ".join(f"{w} — {n}" for w, n in totals.most_common())]
        return "\n".join(lines)

    def save(self) -> None:
        data: dict[str, Any] = {
            str(gid): {
                "counts": {str(uid): dict(c) for uid, c in g.counts.items()},
                "names": {str(uid): n for uid, n in g.names.items()},
                "last_report_at": g.last_report_at,
            }
            for gid, g in self.guilds.items()
        }
        write_json_atomic(self.path, data)

    def _load(self) -> None:
        if not self.path.exists():
            return
        data: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        for gid, g in data.items():
            self.guilds[int(gid)] = GuildStats(
                counts={int(uid): Counter(c) for uid, c in g.get("counts", {}).items()},
                names={int(uid): str(n) for uid, n in g.get("names", {}).items()},
                last_report_at=float(g.get("last_report_at", time.time())),
            )
