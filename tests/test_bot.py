import asyncio
import random
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from discord_sound_bot.bot import SoundBot, random_delay_seconds
from discord_sound_bot.config import Config, IntroSound


@pytest.mark.parametrize(("low", "high"), [(1, 3), (3, 1), (0, 0), (2, 2)])
def test_random_delay_within_bounds(low: float, high: float) -> None:
    rng = random.Random(0)
    lo, hi = sorted((max(low, 0.1), max(high, 0.1)))
    for _ in range(100):
        assert lo * 60 <= random_delay_seconds(low, high, rng) <= hi * 60


def test_bot_builds_with_commands(tmp_path) -> None:
    bot = SoundBot(Config(), stats_path=tmp_path / "stats.json")

    names = {c.name for c in bot.tree.get_commands()}

    assert names == {"stats", "join", "leave", "sound"}
    assert bot.intents.members
    assert bot.intents.message_content
    assert bot.intents.voice_states


class _FakeBot(SoundBot):
    """SoundBot with voice I/O replaced by recorders."""

    def __init__(self, config: Config, stats_path: Path) -> None:
        super().__init__(config, stats_path)
        self.joined: list[object] = []
        self.played: list[str] = []

    async def _ensure_voice(self, channel):  # type: ignore[override]
        self.joined.append(channel)
        return object()

    async def play(self, guild, file, *, interrupt=False):  # type: ignore[override]
        self.played.append(file)
        return True


def _member_in(channel: SimpleNamespace, user_id: int = 1) -> Any:
    member = SimpleNamespace(
        id=user_id,
        bot=False,
        display_name=f"user{user_id}",
        guild=SimpleNamespace(id=100, voice_client=None),
    )
    member.voice = SimpleNamespace(channel=channel)
    channel.members.append(member)
    return member


def test_bot_joins_after_delay_and_plays_first_users_intro(tmp_path: Path) -> None:
    config = Config(intros=[IntroSound(1, "a", "a.mp3")], join_delay_seconds=0.05)
    bot = _FakeBot(config, tmp_path / "stats.json")
    channel = SimpleNamespace(name="voice", members=[])
    first, second = _member_in(channel, 1), _member_in(channel, 2)

    async def scenario() -> None:
        await bot._on_member_joined(first, channel)  # type: ignore[arg-type]
        await bot._on_member_joined(second, channel)  # type: ignore[arg-type]
        assert bot.joined == []  # still waiting
        await asyncio.gather(*bot._pending_joins.values())

    asyncio.run(scenario())

    assert bot.joined == [channel]
    assert bot.played == ["a.mp3"]


def test_bot_skips_join_if_channel_emptied(tmp_path: Path) -> None:
    bot = _FakeBot(Config(join_delay_seconds=0.05), tmp_path / "stats.json")
    channel = SimpleNamespace(name="voice", members=[])
    member = _member_in(channel)

    async def scenario() -> None:
        await bot._on_member_joined(member, channel)  # type: ignore[arg-type]
        channel.members.clear()
        member.voice = None
        await asyncio.gather(*bot._pending_joins.values())

    asyncio.run(scenario())

    assert bot.joined == []
    assert not bot._pending_joins
