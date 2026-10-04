from collections import Counter
from pathlib import Path

from discord_sound_bot.swears import SwearStats, count_swears

WORDS = ["бля", "блять", "хуй", "сука"]


def test_counts_roots_inside_words() -> None:
    assert count_swears("Сука, ну бляха муха", WORDS) == Counter({"сука": 1, "бля": 1})


def test_token_counts_once_for_longest_root() -> None:
    assert count_swears("блять блять", WORDS) == Counter({"блять": 2})


def test_latin_lookalikes_and_yo_are_normalized() -> None:
    assert count_swears("XУЙ и cyka", WORDS) == Counter({"хуй": 1, "сука": 1})
    assert count_swears("ёлка", ["елк"]) == Counter({"елк": 1})


def test_clean_text_and_empty_word_list() -> None:
    assert count_swears("добрый день", WORDS) == Counter()
    assert count_swears("сука", ["", "  "]) == Counter()


def test_stats_persist_and_report(tmp_path: Path) -> None:
    path = tmp_path / "stats.json"
    stats = SwearStats(path)
    stats.add(1, 10, "Вася", Counter({"бля": 3, "сука": 1}))
    stats.add(1, 20, "Петя", Counter({"бля": 1}))
    stats.add(2, 10, "Вася", Counter({"хуй": 5}))

    report = SwearStats(path).format_report(1, lambda uid: "Василий" if uid == 10 else None)

    assert "Всего: **5**" in report
    assert report.index("Василий") < report.index("Петя")
    assert "🥇 **Василий** — 4" in report
    assert "бля — 4" in report
    assert "хуй" not in report


def test_reset_and_mark_reported(tmp_path: Path) -> None:
    stats = SwearStats(tmp_path / "stats.json")
    stats.add(1, 10, "Вася", Counter({"бля": 1}))
    before = stats.guild(1).last_report_at

    stats.mark_reported(1, reset=False)
    assert stats.guild(1).counts
    assert stats.guild(1).last_report_at >= before

    stats.mark_reported(1, reset=True)
    assert "Никто не ругался" in stats.format_report(1)
