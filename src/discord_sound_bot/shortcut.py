"""Desktop shortcut for the app (Windows)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from discord_sound_bot.config import BASE_DIR, FROZEN

SHORTCUT_NAME = "Discord Sound Bot.lnk"

# Paths are passed through environment variables so no quoting is needed.
_PS_SCRIPT = """
$desktop = [Environment]::GetFolderPath('Desktop')
$lnk = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop $env:DSB_NAME))
$lnk.TargetPath = $env:DSB_TARGET
$lnk.WorkingDirectory = $env:DSB_WORKDIR
$lnk.IconLocation = $env:DSB_ICON
$lnk.Description = 'Discord Sound Bot'
$lnk.Save()
"""


def app_executable() -> Path:
    """The .exe a shortcut should start: the packaged app or the venv GUI launcher."""
    if FROZEN:
        return Path(sys.executable)
    return Path(sys.prefix) / "Scripts" / "discord-sound-bot.exe"


def create_desktop_shortcut() -> None:
    target = app_executable()
    windows_dir = os.environ.get("SYSTEMROOT", r"C:\Windows")
    icon = f"{target},0" if FROZEN else rf"{windows_dir}\System32\SndVol.exe,0"
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_SCRIPT],
        env={
            **os.environ,
            "DSB_NAME": SHORTCUT_NAME,
            "DSB_TARGET": str(target),
            "DSB_WORKDIR": str(BASE_DIR),
            "DSB_ICON": icon,
        },
        check=True,
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
