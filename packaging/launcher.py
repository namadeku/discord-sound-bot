"""PyInstaller entry point for DiscordSoundBot.exe."""

import sys


def _self_check() -> int:
    """Used by scripts/build.ps1: exit 1 if voice dependencies weren't bundled.

    Errors are turned into an exit code because an uncaught exception in a windowed
    PyInstaller app shows a modal dialog and would hang the build.
    """
    try:
        import davey  # noqa: F401, PLC0415
        import discord  # noqa: PLC0415
        import nacl.secret  # noqa: F401, PLC0415

        discord.opus._load_default()  # pyright: ignore[reportPrivateUsage]
    except Exception:
        return 1
    return 0 if discord.opus.is_loaded() and discord.voice_client.has_nacl else 1


if "--self-check" in sys.argv:
    sys.exit(_self_check())

from discord_sound_bot.gui import main  # noqa: E402

main()
