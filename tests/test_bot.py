import random

import pytest

from discord_sound_bot.bot import SoundBot, random_delay_seconds
from discord_sound_bot.config import Config


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
