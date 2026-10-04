"""Runs the Discord client in a background thread so the GUI stays responsive."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable, Coroutine
from typing import Any

import discord

from discord_sound_bot.bot import SoundBot
from discord_sound_bot.config import Config

log = logging.getLogger(__name__)


class BotRunner:
    def __init__(self, on_state_change: Callable[[bool], None]) -> None:
        self._on_state_change = on_state_change
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.bot: SoundBot | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, token: str, config: Config) -> None:
        if self.running:
            return
        self._thread = threading.Thread(target=self._run, args=(token, config), daemon=True)
        self._thread.start()

    def _run(self, token: str, config: Config) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        self.bot = SoundBot(config)
        self._on_state_change(True)
        try:
            loop.run_until_complete(self.bot.start(token))
        except discord.LoginFailure:
            log.error("Неверный токен бота. Проверь его на вкладке «Общее».")
        except discord.PrivilegedIntentsRequired:
            log.error(
                "Включи «Server Members Intent» и «Message Content Intent» "
                "в Discord Developer Portal → Bot."
            )
        except Exception:
            log.exception("Бот упал")
        finally:
            if not self.bot.is_closed():
                loop.run_until_complete(self.bot.close())
            loop.close()
            self.bot = None
            self._loop = None
            log.info("Бот остановлен")
            self._on_state_change(False)

    def call[T](self, coro: Coroutine[Any, Any, T], timeout: float = 10) -> T:
        """Run a coroutine on the bot's loop from another thread and wait for the result."""
        if self._loop is None:
            coro.close()
            raise RuntimeError("Бот не запущен")
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def apply_config(self, config: Config) -> None:
        if self.bot and self._loop:
            self._loop.call_soon_threadsafe(self.bot.apply_config, config)

    def stop(self) -> None:
        if self.bot and self._loop and not self.bot.is_closed():
            asyncio.run_coroutine_threadsafe(self.bot.close(), self._loop)

    def join(self, timeout: float = 10) -> None:
        if self._thread:
            self._thread.join(timeout)
