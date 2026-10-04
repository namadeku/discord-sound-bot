"""Bot settings stored in config.json next to the project, plus the token in .env."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "config.json"
STATS_PATH = BASE_DIR / "stats.json"
ENV_PATH = BASE_DIR / ".env"
LOG_PATH = BASE_DIR / "bot.log"
DEFAULT_SOUNDS_DIR = BASE_DIR / "sounds"

AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus", ".webm"})

DEFAULT_SWEAR_WORDS = ["бля", "хуй", "хуе", "пизд", "ебат", "ебал", "сука"]


@dataclass
class IntroSound:
    """Sound played when a specific user joins a voice channel."""

    user_id: int
    user_name: str
    file: str


@dataclass
class RandomSounds:
    enabled: bool = True
    files: list[str] = field(default_factory=list)
    min_minutes: float = 5.0
    max_minutes: float = 20.0


@dataclass
class SwearCounter:
    enabled: bool = True
    words: list[str] = field(default_factory=lambda: list(DEFAULT_SWEAR_WORDS))
    report_channel_id: int | None = None
    report_every_hours: float = 24.0
    reset_after_report: bool = False


@dataclass
class Config:
    sounds_dir: str = str(DEFAULT_SOUNDS_DIR)
    volume: float = 0.8
    leave_when_empty: bool = True
    auto_start: bool = True
    join_delay_seconds: float = 20.0
    intros: list[IntroSound] = field(default_factory=list)
    default_intro: str = ""
    random_sounds: RandomSounds = field(default_factory=RandomSounds)
    swears: SwearCounter = field(default_factory=SwearCounter)

    def intro_for(self, user_id: int) -> str | None:
        for intro in self.intros:
            if intro.user_id == user_id:
                return intro.file
        return self.default_intro or None

    def resolve_sound(self, file: str) -> Path:
        """Relative names are looked up in sounds_dir; absolute paths are used as is."""
        path = Path(file)
        return path if path.is_absolute() else Path(self.sounds_dir) / path

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Config:
        default = cls()
        random_data = data.get("random_sounds", {})
        swear_data = data.get("swears", {})
        return cls(
            sounds_dir=str(data.get("sounds_dir", default.sounds_dir)),
            volume=float(data.get("volume", default.volume)),
            leave_when_empty=bool(data.get("leave_when_empty", default.leave_when_empty)),
            auto_start=bool(data.get("auto_start", default.auto_start)),
            join_delay_seconds=float(data.get("join_delay_seconds", default.join_delay_seconds)),
            intros=[
                IntroSound(int(i["user_id"]), str(i.get("user_name", "")), str(i["file"]))
                for i in data.get("intros", [])
            ],
            default_intro=str(data.get("default_intro", "")),
            random_sounds=RandomSounds(
                enabled=bool(random_data.get("enabled", True)),
                files=[str(f) for f in random_data.get("files", [])],
                min_minutes=float(random_data.get("min_minutes", 5.0)),
                max_minutes=float(random_data.get("max_minutes", 20.0)),
            ),
            swears=SwearCounter(
                enabled=bool(swear_data.get("enabled", True)),
                words=[str(w) for w in swear_data.get("words", DEFAULT_SWEAR_WORDS)],
                report_channel_id=(
                    int(swear_data["report_channel_id"])
                    if swear_data.get("report_channel_id")
                    else None
                ),
                report_every_hours=float(swear_data.get("report_every_hours", 24.0)),
                reset_after_report=bool(swear_data.get("reset_after_report", False)),
            ),
        )


def load_config(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        return Config()
    return Config.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_config(config: Config, path: Path = CONFIG_PATH) -> None:
    write_json_atomic(path, config.to_dict())


def write_json_atomic(path: Path, data: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def list_audio_files(sounds_dir: Path) -> list[str]:
    """Audio files in sounds_dir (recursively), as paths relative to it."""
    if not sounds_dir.is_dir():
        return []
    return sorted(
        p.relative_to(sounds_dir).as_posix()
        for p in sounds_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
    )


def load_token(path: Path = ENV_PATH) -> str:
    if env_token := os.environ.get("DISCORD_TOKEN"):
        return env_token
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "DISCORD_TOKEN":
            return value.strip().strip("\"'")
    return ""


def save_token(token: str, path: Path = ENV_PATH) -> None:
    """Replace DISCORD_TOKEN in .env, keeping any other lines."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [line for line in lines if line.partition("=")[0].strip() != "DISCORD_TOKEN"]
    lines.append(f"DISCORD_TOKEN={token.strip()}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
