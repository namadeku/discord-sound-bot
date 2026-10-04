import base64
from pathlib import Path

from discord_sound_bot.config import (
    BASE_DIR,
    Config,
    IntroSound,
    app_version,
    ffmpeg_executable,
    invite_url,
    list_audio_files,
    load_config,
    load_token,
    save_config,
    save_token,
)


def test_config_roundtrip(tmp_path: Path) -> None:
    config = Config(sounds_dir=str(tmp_path), intros=[IntroSound(42, "Вася", "vasya.mp3")])
    config.random_sounds.files = ["a.mp3"]
    config.swears.report_channel_id = 123
    path = tmp_path / "config.json"

    save_config(config, path)

    assert load_config(path) == config


def test_missing_config_gives_defaults(tmp_path: Path) -> None:
    assert load_config(tmp_path / "nope.json") == Config()


def test_intro_for_falls_back_to_default() -> None:
    config = Config(intros=[IntroSound(1, "a", "a.mp3")], default_intro="any.mp3")

    assert config.intro_for(1) == "a.mp3"
    assert config.intro_for(2) == "any.mp3"
    assert Config().intro_for(2) is None


def test_resolve_sound(tmp_path: Path) -> None:
    config = Config(sounds_dir=str(tmp_path))
    absolute = tmp_path / "x" / "abs.mp3"

    assert config.resolve_sound("a.mp3") == tmp_path / "a.mp3"
    assert config.resolve_sound(str(absolute)) == absolute


def test_list_audio_files(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    for name in ("b.MP3", "a.wav", "notes.txt", "sub/c.ogg"):
        (tmp_path / name).write_bytes(b"")

    assert list_audio_files(tmp_path) == ["a.wav", "b.MP3", "sub/c.ogg"]
    assert list_audio_files(tmp_path / "missing") == []


def test_token_save_keeps_other_lines(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    env = tmp_path / ".env"
    env.write_text("OTHER=1\nDISCORD_TOKEN=old\n", encoding="utf-8")

    save_token(" new-token ", env)

    assert load_token(env) == "new-token"
    assert "OTHER=1" in env.read_text(encoding="utf-8")
    assert load_token(tmp_path / "missing.env") == ""


def test_invite_url_from_token() -> None:
    app_id = "123456789012345678"
    token = base64.b64encode(app_id.encode()).decode().rstrip("=") + ".abc.def"

    url = invite_url(token)

    assert url is not None
    assert f"client_id={app_id}" in url
    assert "permissions=3148800" in url
    assert invite_url("") is None
    assert invite_url("not-a-token!") is None


def test_ffmpeg_falls_back_to_path() -> None:
    assert ffmpeg_executable() in {"ffmpeg", str(BASE_DIR / "ffmpeg.exe")}


def test_app_version_is_known() -> None:
    assert app_version() != "dev"
