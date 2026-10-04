"""Desktop settings window: start/stop the bot and edit all settings."""

from __future__ import annotations

import contextlib
import ctypes
import logging
import logging.handlers
import os
import queue
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

from discord_sound_bot.config import (
    LOG_PATH,
    Config,
    IntroSound,
    RandomSounds,
    SwearCounter,
    list_audio_files,
    load_config,
    load_token,
    save_config,
    save_token,
)
from discord_sound_bot.runner import BotRunner

log = logging.getLogger("discord_sound_bot")

NO_SOUND = "— нет —"
AUTO_CHANNEL = "Авто (системный канал сервера)"
POLL_MS = 200


def _parse_id(text: str) -> int | None:
    """Pull a Discord ID from "Name — 123" or plain "123"."""
    tail = text.rsplit("—", 1)[-1].strip()
    return int(tail) if tail.isdigit() else None


class IntroDialog(tk.Toplevel):
    def __init__(
        self,
        app: App,
        members: list[tuple[int, str]],
        intro: IntroSound | None = None,
    ) -> None:
        super().__init__(app.root)
        self.app = app
        self.result: IntroSound | None = None
        self.title("Звук при входе")
        self.resizable(False, False)
        self.transient(app.root)

        body = ttk.Frame(self, padding=12)
        body.grid(sticky="nsew")

        ttk.Label(body, text="Участник:").grid(row=0, column=0, sticky="w", pady=4)
        self.member_var = tk.StringVar()
        member_values = [f"{name} — {uid}" for uid, name in members]
        member_box = ttk.Combobox(
            body, textvariable=self.member_var, values=member_values, width=48
        )
        member_box.grid(row=0, column=1, columnspan=2, sticky="ew", pady=4)
        hint = (
            "Выберите из списка"
            if members
            else "Запустите бота, чтобы выбрать из списка, или впишите ID пользователя"
        )
        ttk.Label(body, text=hint, foreground="gray").grid(
            row=1, column=1, columnspan=2, sticky="w"
        )

        ttk.Label(body, text="Звук:").grid(row=2, column=0, sticky="w", pady=4)
        self.file_var = tk.StringVar()
        ttk.Combobox(body, textvariable=self.file_var, values=app.audio_files(), width=38).grid(
            row=2, column=1, sticky="ew", pady=4
        )
        ttk.Button(body, text="Обзор…", command=self._browse).grid(row=2, column=2, padx=(4, 0))

        if intro:
            self.member_var.set(f"{intro.user_name} — {intro.user_id}")
            self.file_var.set(intro.file)

        buttons = ttk.Frame(body)
        buttons.grid(row=3, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="OK", command=self._ok).pack(side="left", padx=4)
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(side="left")

        self.bind("<Return>", lambda _: self._ok())
        self.bind("<Escape>", lambda _: self.destroy())
        self.grab_set()
        member_box.focus_set()

    def _browse(self) -> None:
        file = self.app.browse_sound(self)
        if file:
            self.file_var.set(file)

    def _ok(self) -> None:
        text = self.member_var.get().strip()
        user_id = _parse_id(text)
        file = self.file_var.get().strip()
        if user_id is None:
            messagebox.showerror("Ошибка", "Выберите участника или впишите его ID.", parent=self)
            return
        if not file:
            messagebox.showerror("Ошибка", "Выберите звук.", parent=self)
            return
        name = text.rsplit("—", 1)[0].strip() if "—" in text else str(user_id)
        self.result = IntroSound(user_id, name, file)
        self.destroy()


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.config = load_config()
        self.events: queue.Queue[Any] = queue.Queue()
        self.runner = BotRunner(on_state_change=lambda running: self.events.put(("state", running)))
        self.channels: list[tuple[int, str]] = []

        root.title("Discord Sound Bot")
        root.geometry("760x560")
        root.minsize(640, 480)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_top_bar()
        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        notebook.add(self._build_intros_tab(notebook), text="Приветствия")
        notebook.add(self._build_random_tab(notebook), text="Случайные звуки")
        notebook.add(self._build_swears_tab(notebook), text="Счётчик мата")
        notebook.add(self._build_general_tab(notebook), text="Общее")
        notebook.add(self._build_log_tab(notebook), text="Журнал")
        self.notebook = notebook

        self._setup_logging()
        self._load_into_ui()
        root.after(POLL_MS, self._poll_events)

        if not load_token():
            notebook.select(3)
            log.info("Вставьте токен бота на вкладке «Общее» и нажмите «Запустить».")
        elif self.config.auto_start:
            self.start_bot()

    # ----- layout ----------------------------------------------------------

    def _build_top_bar(self) -> None:
        bar = ttk.Frame(self.root, padding=8)
        bar.pack(fill="x")
        self.status_var = tk.StringVar(value="● Остановлен")
        self.status_label = tk.Label(
            bar, textvariable=self.status_var, fg="#b00020", font=("Segoe UI", 11, "bold")
        )
        self.status_label.pack(side="left")
        ttk.Button(bar, text="💾 Сохранить и применить", command=self.save).pack(side="right")
        self.start_button = ttk.Button(bar, text="▶ Запустить", command=self.toggle_bot)
        self.start_button.pack(side="right", padx=8)

    def _build_intros_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=8)
        ttk.Label(tab, text="Какой звук играет, когда участник заходит в голосовой канал:").pack(
            anchor="w"
        )

        table_frame = ttk.Frame(tab)
        table_frame.pack(fill="both", expand=True, pady=6)
        self.intro_table = ttk.Treeview(
            table_frame, columns=("user", "id", "file"), show="headings", selectmode="browse"
        )
        for col, title, width in (
            ("user", "Участник", 220),
            ("id", "ID", 160),
            ("file", "Звук", 260),
        ):
            self.intro_table.heading(col, text=title)
            self.intro_table.column(col, width=width)
        scroll = ttk.Scrollbar(table_frame, command=self.intro_table.yview)
        self.intro_table.configure(yscrollcommand=scroll.set)
        self.intro_table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.intro_table.bind("<Double-1>", lambda _: self._edit_intro())

        buttons = ttk.Frame(tab)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Добавить", command=self._add_intro).pack(side="left")
        ttk.Button(buttons, text="Изменить", command=self._edit_intro).pack(side="left", padx=4)
        ttk.Button(buttons, text="Удалить", command=self._remove_intro).pack(side="left")
        ttk.Button(buttons, text="▶ Прослушать", command=self._preview_intro).pack(side="right")

        default_row = ttk.Frame(tab)
        default_row.pack(fill="x", pady=(12, 0))
        ttk.Label(default_row, text="Звук для всех остальных:").pack(side="left")
        self.default_intro_var = tk.StringVar()
        self.default_intro_box = ttk.Combobox(
            default_row, textvariable=self.default_intro_var, state="readonly", width=40
        )
        self.default_intro_box.pack(side="left", padx=8)
        return tab

    def _build_random_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=8)
        self.random_enabled = tk.BooleanVar()
        ttk.Checkbutton(
            tab,
            text="Проигрывать случайные звуки, пока бот в голосовом канале",
            variable=self.random_enabled,
        ).pack(anchor="w")

        interval = ttk.Frame(tab)
        interval.pack(anchor="w", pady=8)
        self.random_min = tk.DoubleVar()
        self.random_max = tk.DoubleVar()
        ttk.Label(interval, text="Раз в").pack(side="left")
        ttk.Spinbox(
            interval, from_=0.5, to=1440, increment=0.5, textvariable=self.random_min, width=7
        ).pack(side="left", padx=4)
        ttk.Label(interval, text="–").pack(side="left")
        ttk.Spinbox(
            interval, from_=0.5, to=1440, increment=0.5, textvariable=self.random_max, width=7
        ).pack(side="left", padx=4)
        ttk.Label(interval, text="минут (случайно в этом промежутке)").pack(side="left")

        ttk.Label(
            tab, text="Отметьте звуки, которые могут играть (Ctrl/Shift + клик — несколько):"
        ).pack(anchor="w")
        list_frame = ttk.Frame(tab)
        list_frame.pack(fill="both", expand=True, pady=6)
        self.random_list = tk.Listbox(
            list_frame, selectmode="extended", exportselection=False, activestyle="none"
        )
        scroll = ttk.Scrollbar(list_frame, command=self.random_list.yview)
        self.random_list.configure(yscrollcommand=scroll.set)
        self.random_list.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        buttons = ttk.Frame(tab)
        buttons.pack(fill="x")
        ttk.Button(
            buttons, text="Выбрать все", command=lambda: self.random_list.select_set(0, "end")
        ).pack(side="left")
        ttk.Button(
            buttons, text="Снять все", command=lambda: self.random_list.select_clear(0, "end")
        ).pack(side="left", padx=4)
        ttk.Button(buttons, text="Обновить список", command=self._refresh_sounds).pack(side="left")
        ttk.Button(buttons, text="▶ Прослушать", command=self._preview_random).pack(side="right")
        return tab

    def _build_swears_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=8)
        self.swears_enabled = tk.BooleanVar()
        ttk.Checkbutton(tab, text="Считать мат в чате", variable=self.swears_enabled).pack(
            anchor="w"
        )
        ttk.Label(
            tab,
            text=(
                "Слова или их корни, по одному в строке. Считается любое слово, которое "
                "содержит корень\n(например, «бля» засчитает и «блять»)."
            ),
        ).pack(anchor="w", pady=(8, 2))
        self.words_text = ScrolledText(tab, height=8, width=30, font=("Segoe UI", 10))
        self.words_text.pack(anchor="w", fill="x")

        report = ttk.Frame(tab)
        report.pack(fill="x", pady=8)
        ttk.Label(report, text="Канал для статистики:").grid(row=0, column=0, sticky="w")
        self.channel_var = tk.StringVar()
        self.channel_box = ttk.Combobox(report, textvariable=self.channel_var, width=45)
        self.channel_box.grid(row=0, column=1, sticky="w", padx=8)
        ttk.Button(report, text="Обновить", command=self._refresh_channels).grid(row=0, column=2)

        ttk.Label(report, text="Публиковать каждые:").grid(row=1, column=0, sticky="w", pady=6)
        every = ttk.Frame(report)
        every.grid(row=1, column=1, sticky="w", padx=8)
        self.report_hours = tk.DoubleVar()
        ttk.Spinbox(
            every, from_=0, to=720, increment=1, textvariable=self.report_hours, width=7
        ).pack(side="left")
        ttk.Label(every, text="часов (0 — только по команде /stats)").pack(side="left", padx=4)

        self.reset_after = tk.BooleanVar()
        ttk.Checkbutton(
            tab, text="Обнулять счётчик после каждой публикации", variable=self.reset_after
        ).pack(anchor="w")

        buttons = ttk.Frame(tab)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Опубликовать статистику сейчас", command=self._report_now).pack(
            side="left"
        )
        ttk.Button(buttons, text="Обнулить статистику", command=self._reset_stats).pack(
            side="left", padx=8
        )
        return tab

    def _build_general_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=8)
        tab.columnconfigure(1, weight=1)

        ttk.Label(tab, text="Токен бота:").grid(row=0, column=0, sticky="w", pady=4)
        self.token_var = tk.StringVar()
        ttk.Entry(tab, textvariable=self.token_var, show="•").grid(
            row=0, column=1, sticky="ew", padx=8
        )
        ttk.Button(tab, text="Сохранить токен", command=self._save_token).grid(row=0, column=2)
        self.token_hint = ttk.Label(tab, foreground="gray")
        self.token_hint.grid(row=1, column=1, sticky="w", padx=8)

        ttk.Label(tab, text="Папка со звуками:").grid(row=2, column=0, sticky="w", pady=(12, 4))
        self.sounds_dir_var = tk.StringVar()
        ttk.Entry(tab, textvariable=self.sounds_dir_var).grid(
            row=2, column=1, sticky="ew", padx=8, pady=(12, 4)
        )
        dir_buttons = ttk.Frame(tab)
        dir_buttons.grid(row=2, column=2, pady=(12, 4))
        ttk.Button(dir_buttons, text="Обзор…", command=self._browse_dir).pack(side="left")
        ttk.Button(dir_buttons, text="Открыть", command=self._open_dir).pack(side="left", padx=4)

        ttk.Label(tab, text="Громкость:").grid(row=3, column=0, sticky="w", pady=4)
        self.volume_var = tk.DoubleVar()
        volume_row = ttk.Frame(tab)
        volume_row.grid(row=3, column=1, sticky="ew", padx=8)
        self.volume_label = ttk.Label(volume_row, width=5)
        ttk.Scale(
            volume_row,
            from_=0,
            to=2,
            variable=self.volume_var,
            command=lambda _: self.volume_label.configure(
                text=f"{round(self.volume_var.get() * 100)}%"
            ),
        ).pack(side="left", fill="x", expand=True)
        self.volume_label.pack(side="left", padx=4)

        self.leave_var = tk.BooleanVar()
        ttk.Checkbutton(
            tab,
            text="Выходить из голосового канала, когда в нём никого нет",
            variable=self.leave_var,
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=4)
        self.autostart_var = tk.BooleanVar()
        ttk.Checkbutton(
            tab, text="Запускать бота сразу при открытии программы", variable=self.autostart_var
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=4)

        help_text = (
            "Первый запуск:\n"
            "1. discord.com/developers/applications → New Application → Bot → Reset Token, "
            "вставьте токен выше.\n"
            "2. Там же на вкладке Bot включите «Server Members Intent» и "
            "«Message Content Intent».\n"
            "3. OAuth2 → URL Generator: scopes «bot» и «applications.commands»; права: "
            "View Channels, Send Messages, Connect, Speak. Откройте ссылку и добавьте бота "
            "на сервер.\n"
            "4. Положите mp3/wav/ogg в папку со звуками.\n\n"
            "Команды в Discord: /stats, /join, /leave, /sound"
        )
        ttk.Label(tab, text=help_text, foreground="#444", wraplength=680, justify="left").grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(16, 0)
        )
        return tab

    def _build_log_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=8)
        self.log_text = ScrolledText(tab, state="disabled", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)
        return tab

    # ----- config <-> UI ---------------------------------------------------

    def _load_into_ui(self) -> None:
        cfg = self.config
        for row in self.intro_table.get_children():
            self.intro_table.delete(row)
        for intro in cfg.intros:
            self._insert_intro(intro)
        self.default_intro_var.set(cfg.default_intro or NO_SOUND)

        self.random_enabled.set(cfg.random_sounds.enabled)
        self.random_min.set(cfg.random_sounds.min_minutes)
        self.random_max.set(cfg.random_sounds.max_minutes)

        self.swears_enabled.set(cfg.swears.enabled)
        self.words_text.delete("1.0", "end")
        self.words_text.insert("1.0", "\n".join(cfg.swears.words))
        channel_id = cfg.swears.report_channel_id
        self.channel_var.set(f"ID — {channel_id}" if channel_id else AUTO_CHANNEL)
        self.channel_box.configure(values=[AUTO_CHANNEL])
        self.report_hours.set(cfg.swears.report_every_hours)
        self.reset_after.set(cfg.swears.reset_after_report)

        self.sounds_dir_var.set(cfg.sounds_dir)
        self.volume_var.set(cfg.volume)
        self.volume_label.configure(text=f"{round(cfg.volume * 100)}%")
        self.leave_var.set(cfg.leave_when_empty)
        self.autostart_var.set(cfg.auto_start)
        self._update_token_hint()
        self._refresh_sounds(keep=cfg.random_sounds.files)

    def _collect_config(self) -> Config:
        intros = [
            IntroSound(int(values[1]), str(values[0]), str(values[2]))
            for values in (
                self.intro_table.item(row, "values") for row in self.intro_table.get_children()
            )
        ]
        default_intro = self.default_intro_var.get()
        files = [str(self.random_list.get(i)) for i in self.random_list.curselection()]
        words = [w.strip() for w in self.words_text.get("1.0", "end").splitlines() if w.strip()]

        def number(var: tk.DoubleVar, fallback: float) -> float:
            try:
                return max(float(var.get()), 0.0)
            except (tk.TclError, ValueError):
                return fallback

        return Config(
            sounds_dir=self.sounds_dir_var.get().strip() or self.config.sounds_dir,
            volume=round(self.volume_var.get(), 2),
            leave_when_empty=self.leave_var.get(),
            auto_start=self.autostart_var.get(),
            intros=intros,
            default_intro="" if default_intro == NO_SOUND else default_intro,
            random_sounds=RandomSounds(
                enabled=self.random_enabled.get(),
                files=files,
                min_minutes=number(self.random_min, 5),
                max_minutes=number(self.random_max, 20),
            ),
            swears=SwearCounter(
                enabled=self.swears_enabled.get(),
                words=words,
                report_channel_id=_parse_id(self.channel_var.get()),
                report_every_hours=number(self.report_hours, 24),
                reset_after_report=self.reset_after.get(),
            ),
        )

    def save(self) -> None:
        self.config = self._collect_config()
        save_config(self.config)
        self.runner.apply_config(self.config)
        log.info("Настройки сохранены")

    # ----- sounds ----------------------------------------------------------

    def audio_files(self) -> list[str]:
        return list_audio_files(Path(self.sounds_dir_var.get()))

    def _refresh_sounds(self, keep: list[str] | None = None) -> None:
        selected = (
            set(keep)
            if keep is not None
            else {str(self.random_list.get(i)) for i in self.random_list.curselection()}
        )
        files = self.audio_files()
        self.random_list.delete(0, "end")
        for index, file in enumerate(files):
            self.random_list.insert("end", file)
            if file in selected:
                self.random_list.select_set(index)
        self.default_intro_box.configure(values=[NO_SOUND, *files])
        if not files:
            log.info("В папке со звуками пока пусто: %s", self.sounds_dir_var.get())

    def browse_sound(self, parent: tk.Misc) -> str | None:
        sounds_dir = Path(self.sounds_dir_var.get())
        path = filedialog.askopenfilename(
            parent=parent,
            initialdir=sounds_dir if sounds_dir.is_dir() else None,
            filetypes=[("Аудио", "*.mp3 *.wav *.ogg *.flac *.m4a *.aac *.opus *.webm")],
        )
        if not path:
            return None
        chosen = Path(path)
        try:
            return chosen.relative_to(sounds_dir).as_posix()
        except ValueError:
            return str(chosen)

    def _preview(self, file: str) -> None:
        path = Path(file) if Path(file).is_absolute() else Path(self.sounds_dir_var.get()) / file
        if path.is_file():
            os.startfile(path)
        else:
            messagebox.showerror("Ошибка", f"Файл не найден:\n{path}")

    def _preview_random(self) -> None:
        selection = self.random_list.curselection()
        if selection:
            self._preview(str(self.random_list.get(selection[-1])))

    def _browse_dir(self) -> None:
        path = filedialog.askdirectory(initialdir=self.sounds_dir_var.get())
        if path:
            self.sounds_dir_var.set(str(Path(path)))
            self._refresh_sounds()

    def _open_dir(self) -> None:
        path = Path(self.sounds_dir_var.get())
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)

    # ----- intros ----------------------------------------------------------

    def _insert_intro(self, intro: IntroSound, at: str | None = None) -> None:
        values = (intro.user_name, str(intro.user_id), intro.file)
        if at:
            self.intro_table.item(at, values=values)
        else:
            self.intro_table.insert("", "end", values=values)

    def _members(self) -> list[tuple[int, str]]:
        bot = self.runner.bot
        if not (bot and bot.is_ready()):
            return []
        try:
            return self.runner.call(bot.list_members())
        except Exception:
            log.exception("Не удалось получить список участников")
            return []

    def _add_intro(self) -> None:
        dialog = IntroDialog(self, self._members())
        self.root.wait_window(dialog)
        if dialog.result:
            for row in self.intro_table.get_children():
                if self.intro_table.item(row, "values")[1] == str(dialog.result.user_id):
                    self._insert_intro(dialog.result, at=row)
                    return
            self._insert_intro(dialog.result)

    def _edit_intro(self) -> None:
        selection = self.intro_table.selection()
        if not selection:
            return
        name, user_id, file = self.intro_table.item(selection[0], "values")
        dialog = IntroDialog(self, self._members(), IntroSound(int(user_id), str(name), str(file)))
        self.root.wait_window(dialog)
        if dialog.result:
            self._insert_intro(dialog.result, at=selection[0])

    def _remove_intro(self) -> None:
        for row in self.intro_table.selection():
            self.intro_table.delete(row)

    def _preview_intro(self) -> None:
        selection = self.intro_table.selection()
        if selection:
            self._preview(str(self.intro_table.item(selection[0], "values")[2]))

    # ----- swear stats -----------------------------------------------------

    def _ready_bot(self) -> bool:
        if self.runner.bot and self.runner.bot.is_ready():
            return True
        messagebox.showinfo("Бот не запущен", "Сначала запустите бота.")
        return False

    def _refresh_channels(self) -> None:
        if not self._ready_bot() or self.runner.bot is None:
            return
        self.channels = self.runner.call(self.runner.bot.list_text_channels())
        self.channel_box.configure(
            values=[AUTO_CHANNEL, *(f"{name} — {cid}" for cid, name in self.channels)]
        )
        current = _parse_id(self.channel_var.get())
        for cid, name in self.channels:
            if cid == current:
                self.channel_var.set(f"{name} — {cid}")

    def _report_now(self) -> None:
        if not self._ready_bot() or self.runner.bot is None:
            return
        self.save()
        try:
            sent = self.runner.call(self.runner.bot.send_reports_now())
        except Exception:
            log.exception("Не удалось опубликовать статистику")
            return
        log.info("Статистика опубликована на серверах: %d", sent)

    def _reset_stats(self) -> None:
        if not self._ready_bot() or self.runner.bot is None:
            return
        if messagebox.askyesno("Обнулить статистику", "Точно обнулить счётчик мата?"):
            self.runner.call(self.runner.bot.reset_stats())
            log.info("Статистика обнулена")

    # ----- bot control -----------------------------------------------------

    def _update_token_hint(self) -> None:
        has_token = bool(load_token())
        self.token_hint.configure(
            text="Токен сохранён (не показывается)" if has_token else "Токен ещё не задан"
        )

    def _save_token(self) -> None:
        token = self.token_var.get().strip()
        if not token:
            messagebox.showerror("Ошибка", "Вставьте токен.")
            return
        save_token(token)
        self.token_var.set("")
        self._update_token_hint()
        log.info("Токен сохранён")

    def toggle_bot(self) -> None:
        if self.runner.running:
            self.runner.stop()
        else:
            self.start_bot()

    def start_bot(self) -> None:
        token = load_token()
        if not token:
            messagebox.showerror("Нет токена", "Сначала сохраните токен на вкладке «Общее».")
            self.notebook.select(3)
            return
        self.save()
        self.status_var.set("● Подключение…")
        self.status_label.configure(fg="#c77700")
        self.runner.start(token, self.config)

    def _set_running(self, running: bool) -> None:
        self.status_var.set("● Работает" if running else "● Остановлен")
        self.status_label.configure(fg="#1b7f3b" if running else "#b00020")
        self.start_button.configure(text="■ Остановить" if running else "▶ Запустить")

    def _on_close(self) -> None:
        if self.runner.running:
            self.runner.stop()
            self.runner.join()
        self.root.destroy()

    # ----- logging ---------------------------------------------------------

    def _setup_logging(self) -> None:
        formatter = logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%H:%M:%S")
        ui_handler = logging.handlers.QueueHandler(self.events)
        ui_handler.setLevel(logging.INFO)
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
        )
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        self.log_formatter = formatter
        for name in ("discord_sound_bot", "discord"):
            logger = logging.getLogger(name)
            logger.setLevel(logging.INFO)
            logger.addHandler(file_handler)
        log.addHandler(ui_handler)
        logging.getLogger("discord").addHandler(_WarningsOnly(ui_handler))

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if isinstance(event, logging.LogRecord):
                    self._append_log(self.log_formatter.format(event))
                elif event[0] == "state":
                    self._set_running(bool(event[1]))
        except queue.Empty:
            pass
        self.root.after(POLL_MS, self._poll_events)

    def _append_log(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")


class _WarningsOnly(logging.Handler):
    """Forward only warnings and errors from discord.py to the UI log."""

    def __init__(self, target: logging.Handler) -> None:
        super().__init__(logging.WARNING)
        self.target = target

    def emit(self, record: logging.LogRecord) -> None:
        self.target.handle(record)


def main() -> None:
    with contextlib.suppress(AttributeError, OSError):
        # Crisp text on high-DPI screens instead of bitmap-scaled blur.
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
