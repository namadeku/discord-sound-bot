"""Discord client: intro sounds, random sounds and swear statistics."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from pathlib import Path

import discord
from discord import app_commands

from discord_sound_bot.config import STATS_PATH, Config, list_audio_files
from discord_sound_bot.swears import SwearStats, count_swears

log = logging.getLogger(__name__)

REPORT_CHECK_SECONDS = 60


def random_delay_seconds(min_minutes: float, max_minutes: float, rng: random.Random) -> float:
    """Seconds until the next random sound; tolerates swapped or tiny bounds."""
    low, high = sorted((max(min_minutes, 0.1), max(max_minutes, 0.1)))
    return rng.uniform(low, high) * 60


def humans_in(channel: discord.VoiceChannel | discord.StageChannel) -> list[discord.Member]:
    return [m for m in channel.members if not m.bot]


class SoundBot(discord.Client):
    def __init__(self, config: Config, stats_path: Path = STATS_PATH) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.voice_states = True
        super().__init__(intents=intents)
        self.config = config
        self.stats = SwearStats(stats_path)
        self.tree = app_commands.CommandTree(self)
        self._rng = random.Random()
        self._play_locks: dict[int, asyncio.Lock] = {}
        self._random_tasks: dict[int, asyncio.Task[None]] = {}
        self._report_task: asyncio.Task[None] | None = None
        self._register_commands()

    # ----- lifecycle -------------------------------------------------------

    async def setup_hook(self) -> None:
        self._report_task = asyncio.create_task(self._report_loop())

    async def on_ready(self) -> None:
        log.info("Бот запущен как %s, серверов: %d", self.user, len(self.guilds))
        for guild in self.guilds:
            self.tree.copy_global_to(guild=guild)
            try:
                await self.tree.sync(guild=guild)
            except discord.HTTPException:
                log.exception("Не удалось зарегистрировать команды на сервере %s", guild.name)

    async def close(self) -> None:
        for task in self._random_tasks.values():
            task.cancel()
        if self._report_task:
            self._report_task.cancel()
        for vc in list(self.voice_clients):
            await vc.disconnect(force=True)
        await super().close()

    def apply_config(self, config: Config) -> None:
        """Swap settings at runtime; loops read self.config on every iteration."""
        self.config = config
        log.info("Настройки применены")

    # ----- voice -----------------------------------------------------------

    def _voice_client(self, guild: discord.Guild) -> discord.VoiceClient | None:
        vc = guild.voice_client
        return vc if isinstance(vc, discord.VoiceClient) and vc.is_connected() else None

    async def _ensure_voice(
        self, channel: discord.VoiceChannel | discord.StageChannel
    ) -> discord.VoiceClient | None:
        vc = self._voice_client(channel.guild)
        if vc and vc.channel == channel:
            return vc
        if vc:
            current = vc.channel
            if isinstance(current, discord.VoiceChannel | discord.StageChannel) and humans_in(
                current
            ):
                # Don't abandon people in another channel.
                return None
            await vc.move_to(channel)
            return vc
        try:
            vc = await channel.connect(self_deaf=True)
        except (discord.ClientException, TimeoutError):
            log.exception("Не удалось подключиться к каналу %s", channel.name)
            return None
        self._start_random_loop(channel.guild)
        return vc

    async def play(self, guild: discord.Guild, file: str, *, interrupt: bool = False) -> bool:
        """Play a sound and wait for it to finish. Returns False if it couldn't play."""
        vc = self._voice_client(guild)
        path = self.config.resolve_sound(file)
        if vc is None:
            return False
        if not path.is_file():
            log.warning("Файл не найден: %s", path)
            return False
        lock = self._play_locks.setdefault(guild.id, asyncio.Lock())
        if interrupt and vc.is_playing():
            vc.stop()
        async with lock:
            loop = asyncio.get_running_loop()
            done = asyncio.Event()

            def after(error: Exception | None) -> None:
                if error:
                    log.error("Ошибка воспроизведения %s: %s", path.name, error)
                loop.call_soon_threadsafe(done.set)

            source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(str(path)), volume=self.config.volume
            )
            vc.play(source, after=after)
            log.info("▶ %s (%s)", path.name, guild.name)
            await done.wait()
        return True

    def _start_random_loop(self, guild: discord.Guild) -> None:
        task = self._random_tasks.get(guild.id)
        if task is None or task.done():
            self._random_tasks[guild.id] = asyncio.create_task(self._random_loop(guild))

    async def _random_loop(self, guild: discord.Guild) -> None:
        while self._voice_client(guild):
            cfg = self.config.random_sounds
            await asyncio.sleep(random_delay_seconds(cfg.min_minutes, cfg.max_minutes, self._rng))
            cfg = self.config.random_sounds
            vc = self._voice_client(guild)
            if not (cfg.enabled and cfg.files and vc) or vc.is_playing():
                continue
            if isinstance(vc.channel, discord.VoiceChannel | discord.StageChannel) and humans_in(
                vc.channel
            ):
                await self.play(guild, self._rng.choice(cfg.files))

    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        if member.bot:
            return
        if before.channel and before.channel != after.channel:
            await self._leave_if_empty(member.guild)
        if after.channel and before.channel != after.channel:
            file = self.config.intro_for(member.id)
            if file and await self._ensure_voice(after.channel):
                await asyncio.sleep(0.5)  # let the joining client start receiving audio
                await self.play(member.guild, file, interrupt=True)

    async def _leave_if_empty(self, guild: discord.Guild) -> None:
        vc = self._voice_client(guild)
        if not (vc and self.config.leave_when_empty):
            return
        if isinstance(vc.channel, discord.VoiceChannel | discord.StageChannel) and not humans_in(
            vc.channel
        ):
            log.info("В канале %s никого нет, выхожу", vc.channel.name)
            await vc.disconnect()

    # ----- swear counter ---------------------------------------------------

    async def on_message(self, message: discord.Message) -> None:
        cfg = self.config.swears
        if not cfg.enabled or message.author.bot or message.guild is None:
            return
        counts = count_swears(message.content, cfg.words)
        if counts:
            self.stats.add(message.guild.id, message.author.id, message.author.display_name, counts)

    def report_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        channel_id = self.config.swears.report_channel_id
        candidates: list[discord.TextChannel | None] = [
            guild.get_channel(channel_id) if channel_id else None,  # type: ignore[list-item]
            guild.system_channel,
            *guild.text_channels,
        ]
        for channel in candidates:
            if (
                isinstance(channel, discord.TextChannel)
                and channel.permissions_for(guild.me).send_messages
            ):
                return channel
        return None

    def _resolve_name(self, guild: discord.Guild, user_id: int) -> str | None:
        member = guild.get_member(user_id)
        return member.display_name if member else None

    async def send_report(self, guild: discord.Guild) -> bool:
        channel = self.report_channel(guild)
        if channel is None:
            log.warning("На сервере %s нет канала для статистики", guild.name)
            return False
        text = self.stats.format_report(guild.id, lambda uid: self._resolve_name(guild, uid))
        await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
        self.stats.mark_reported(guild.id, reset=self.config.swears.reset_after_report)
        log.info("Статистика отправлена в #%s (%s)", channel.name, guild.name)
        return True

    async def _report_loop(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            cfg = self.config.swears
            if cfg.enabled and cfg.report_every_hours > 0:
                for guild in self.guilds:
                    due = self.stats.guild(guild.id).last_report_at + cfg.report_every_hours * 3600
                    if time.time() >= due:
                        try:
                            await self.send_report(guild)
                        except discord.HTTPException:
                            log.exception("Не удалось отправить статистику")
            await asyncio.sleep(REPORT_CHECK_SECONDS)

    # ----- data for the GUI ------------------------------------------------

    async def list_members(self) -> list[tuple[int, str]]:
        members = {m.id: f"{m.display_name} (@{m.name})" for g in self.guilds for m in g.members}
        members.pop(self.user.id if self.user else 0, None)
        return sorted(members.items(), key=lambda item: item[1].lower())

    async def list_text_channels(self) -> list[tuple[int, str]]:
        return [(c.id, f"#{c.name} ({g.name})") for g in self.guilds for c in g.text_channels]

    async def send_reports_now(self) -> int:
        sent = 0
        for guild in self.guilds:
            sent += await self.send_report(guild)
        return sent

    async def reset_stats(self) -> None:
        for guild in self.guilds:
            self.stats.reset(guild.id)

    # ----- slash commands --------------------------------------------------

    def _register_commands(self) -> None:
        tree = self.tree

        @tree.command(name="stats", description="Показать статистику мата")
        @app_commands.guild_only()
        async def stats_cmd(interaction: discord.Interaction) -> None:
            assert interaction.guild
            guild = interaction.guild
            text = self.stats.format_report(guild.id, lambda uid: self._resolve_name(guild, uid))
            await interaction.response.send_message(
                text, allowed_mentions=discord.AllowedMentions.none()
            )

        @tree.command(name="join", description="Позвать бота в твой голосовой канал")
        @app_commands.guild_only()
        async def join_cmd(interaction: discord.Interaction) -> None:
            member = interaction.user
            if not (isinstance(member, discord.Member) and member.voice and member.voice.channel):
                await interaction.response.send_message("Сначала зайди в голосовой канал.")
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            vc = await self._ensure_voice(member.voice.channel)
            await interaction.followup.send(
                "Иду!" if vc else "Не могу: я уже сижу с людьми в другом канале.",
                ephemeral=True,
            )

        @tree.command(name="leave", description="Выгнать бота из голосового канала")
        @app_commands.guild_only()
        async def leave_cmd(interaction: discord.Interaction) -> None:
            assert interaction.guild
            vc = self._voice_client(interaction.guild)
            if vc:
                await vc.disconnect()
            await interaction.response.send_message("Ушёл.", ephemeral=True)

        @tree.command(name="sound", description="Проиграть звук")
        @app_commands.describe(name="Имя файла из папки со звуками")
        @app_commands.guild_only()
        async def sound_cmd(interaction: discord.Interaction, name: str) -> None:
            member = interaction.user
            if not (isinstance(member, discord.Member) and member.voice and member.voice.channel):
                await interaction.response.send_message(
                    "Сначала зайди в голосовой канал.", ephemeral=True
                )
                return
            await interaction.response.send_message(f"▶ {name}", ephemeral=True)
            if await self._ensure_voice(member.voice.channel):
                await self.play(member.guild, name, interrupt=True)

        @sound_cmd.autocomplete("name")
        async def sound_autocomplete(
            interaction: discord.Interaction, current: str
        ) -> list[app_commands.Choice[str]]:
            files = list_audio_files(Path(self.config.sounds_dir))
            matches = [f for f in files if current.lower() in f.lower()]
            return [app_commands.Choice(name=f[:100], value=f) for f in matches[:25]]
