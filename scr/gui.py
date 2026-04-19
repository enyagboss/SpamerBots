import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog, simpledialog
import asyncio
import threading
import json
import os
from src.account_manager import AccountManager
from src.broadcaster import BroadcastManager
from src.notifier import Notifier
from utils.helpers import parse_delay_range

class MainGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Telegram Broadcaster Pro")
        self.root.geometry("1000x800")
        self.root.configure(bg='black')
        self.account_manager = AccountManager(gui_callback=self.ask_code_or_password)
        self.broadcast_manager = None
        self.loop = None
        self.thread = None
        self.running = False
        self.current_account_index = None
        self._code_future = None
        self._password_future = None

        self.create_widgets()
        self.load_settings()

    async def ask_code_or_password(self, type_, phone):
        """Вызывается из account_manager для запроса кода/пароля в GUI"""
        if type_ == "code":
            prompt = f"Введите код из Telegram для {phone}:"
            self._code_future = asyncio.Future()
            # Запускаем диалог в главном потоке
            self.root.after(0, lambda: self._show_code_dialog(prompt))
            return await self._code_future
        else:
            prompt = f"Введите пароль 2FA для {phone}:"
            self._password_future = asyncio.Future()
            self.root.after(0, lambda: self._show_password_dialog(prompt))
            return await self._password_future

    def _show_code_dialog(self, prompt):
        dialog = tk.Toplevel(self.root)
        dialog.title("Код подтверждения")
        dialog.geometry("400x150")
        dialog.configure(bg='black')
        dialog.transient(self.root)  # сделать дочерним
        dialog.grab_set()  # модальность
        tk.Label(dialog, text=prompt, bg='black', fg='#00FF00', font=("Consolas", 10)).pack(pady=10)
        entry = tk.Entry(dialog, bg='black', fg='#00FF00', insertbackground='green', font=("Consolas", 10))
        entry.pack(pady=5, padx=20, fill=tk.X)
        entry.focus_set()
        def submit():
            result = entry.get()
            dialog.destroy()
            if self._code_future and not self._code_future.done():
                self._code_future.set_result(result)
        tk.Button(dialog, text="OK", command=submit, bg='black', fg='#00FF00').pack(pady=10)
        dialog.bind('<Return>', lambda e: submit())
        # если окно закрыто крестиком, вернём None
        def on_close():
            dialog.destroy()
            if self._code_future and not self._code_future.done():
                self._code_future.set_result(None)
        dialog.protocol("WM_DELETE_WINDOW", on_close)

    def _show_password_dialog(self, prompt):
        dialog = tk.Toplevel(self.root)
        dialog.title("2FA пароль")
        dialog.geometry("400x150")
        dialog.configure(bg='black')
        dialog.transient(self.root)
        dialog.grab_set()
        tk.Label(dialog, text=prompt, bg='black', fg='#00FF00', font=("Consolas", 10)).pack(pady=10)
        entry = tk.Entry(dialog, bg='black', fg='#00FF00', insertbackground='green', font=("Consolas", 10), show='*')
        entry.pack(pady=5, padx=20, fill=tk.X)
        entry.focus_set()
        def submit():
            result = entry.get()
            dialog.destroy()
            if self._password_future and not self._password_future.done():
                self._password_future.set_result(result)
        tk.Button(dialog, text="OK", command=submit, bg='black', fg='#00FF00').pack(pady=10)
        dialog.bind('<Return>', lambda e: submit())
        def on_close():
            dialog.destroy()
            if self._password_future and not self._password_future.done():
                self._password_future.set_result(None)
        dialog.protocol("WM_DELETE_WINDOW", on_close)

    def create_widgets(self):
        font = ("Consolas", 10)
        # Настройки аккаунтов
        acc_frame = tk.LabelFrame(self.root, text="Управление аккаунтами", bg='black', fg='#00FF00', font=font)
        acc_frame.pack(fill=tk.X, padx=10, pady=5)

        self.account_listbox = tk.Listbox(acc_frame, bg='black', fg='#00FF00', height=4)
        self.account_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        btn_frame = tk.Frame(acc_frame, bg='black')
        btn_frame.pack(side=tk.RIGHT, padx=5)
        tk.Button(btn_frame, text="Добавить аккаунт", command=self.add_account_dialog, bg='black', fg='#00FF00').pack(pady=2)
        tk.Button(btn_frame, text="Удалить аккаунт", command=self.remove_account, bg='black', fg='#00FF00').pack(pady=2)

        # Параметры рассылки
        settings_frame = tk.LabelFrame(self.root, text="Настройки рассылки", bg='black', fg='#00FF00')
        settings_frame.pack(fill=tk.X, padx=10, pady=5)

        tk.Label(settings_frame, text="Текст сообщения:", bg='black', fg='#00FF00').grid(row=0, column=0, sticky='e')
        self.message_entry = tk.Entry(settings_frame, width=70, bg='black', fg='#00FF00')
        self.message_entry.grid(row=0, column=1, columnspan=3, padx=5, pady=2)

        tk.Label(settings_frame, text="Медиафайл:", bg='black', fg='#00FF00').grid(row=1, column=0, sticky='e')
        self.media_path_var = tk.StringVar()
        tk.Entry(settings_frame, textvariable=self.media_path_var, width=50, bg='black', fg='#00FF00').grid(row=1, column=1)
        tk.Button(settings_frame, text="Обзор", command=self.select_media, bg='black', fg='#00FF00').grid(row=1, column=2)

        tk.Label(settings_frame, text="Интервал (часы):", bg='black', fg='#00FF00').grid(row=2, column=0, sticky='e')
        self.interval_spin = tk.Spinbox(settings_frame, from_=0.1, to=24, increment=0.5, width=10, bg='black', fg='#00FF00')
        self.interval_spin.delete(0, tk.END)
        self.interval_spin.insert(0, "1")
        self.interval_spin.grid(row=2, column=1, sticky='w')

        tk.Label(settings_frame, text="Задержка (сек, min-max):", bg='black', fg='#00FF00').grid(row=3, column=0, sticky='e')
        self.delay_entry = tk.Entry(settings_frame, width=15, bg='black', fg='#00FF00')
        self.delay_entry.insert(0, "30-60")
        self.delay_entry.grid(row=3, column=1, sticky='w')

        self.human_delay_var = tk.BooleanVar(value=True)
        tk.Checkbutton(settings_frame, text="Искусственная задержка", variable=self.human_delay_var, bg='black', fg='#00FF00', selectcolor='black').grid(row=3, column=2, sticky='w')

        self.typing_var = tk.BooleanVar(value=True)
        tk.Checkbutton(settings_frame, text="Эмуляция набора текста", variable=self.typing_var, bg='black', fg='#00FF00', selectcolor='black').grid(row=3, column=3, sticky='w')

        self.mode_var = tk.StringVar(value="all")
        tk.Radiobutton(settings_frame, text="Все чаты аккаунта", variable=self.mode_var, value="all", bg='black', fg='#00FF00', selectcolor='black').grid(row=4, column=0, sticky='w')
        tk.Radiobutton(settings_frame, text="Из файла chats.txt", variable=self.mode_var, value="file", bg='black', fg='#00FF00', selectcolor='black').grid(row=4, column=1, sticky='w')

        # Лог
        log_frame = tk.LabelFrame(self.root, text="Лог", bg='black', fg='#00FF00')
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.log_area = scrolledtext.ScrolledText(log_frame, bg='black', fg='#00FF00', height=15)
        self.log_area.pack(fill=tk.BOTH, expand=True)

        # Кнопки управления
        btn_panel = tk.Frame(self.root, bg='black')
        btn_panel.pack(fill=tk.X, padx=10, pady=5)
        self.start_btn = tk.Button(btn_panel, text="СТАРТ", command=self.start_broadcast, bg='black', fg='#00FF00', width=10)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        self.stop_btn = tk.Button(btn_panel, text="СТОП", command=self.stop_broadcast, bg='black', fg='#00FF00', width=10, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        self.update_accounts_list()

    def load_settings(self):
        if os.path.exists("config.json"):
            with open("config.json", 'r') as f:
                data = json.load(f)
                settings = data.get("broadcast_settings", {})
                self.message_entry.insert(0, settings.get("message", ""))
                self.media_path_var.set(settings.get("media_path", ""))
                self.interval_spin.delete(0, tk.END)
                self.interval_spin.insert(0, str(settings.get("interval_hours", 1)))
                delay = settings.get("delay_range", "30-60")
                if isinstance(delay, list):
                    delay = f"{delay[0]}-{delay[1]}"
                self.delay_entry.delete(0, tk.END)
                self.delay_entry.insert(0, delay)
                self.human_delay_var.set(settings.get("use_human_delays", True))
                self.typing_var.set(settings.get("typing_emulation", True))
                self.mode_var.set(settings.get("mode", "all"))

    def save_settings_to_config(self):
        with open("config.json", 'r') as f:
            data = json.load(f)
        data["broadcast_settings"] = {
            "message": self.message_entry.get(),
            "media_path": self.media_path_var.get() or None,
            "interval_hours": float(self.interval_spin.get()),
            "delay_range": self.delay_entry.get(),
            "use_human_delays": self.human_delay_var.get(),
            "typing_emulation": self.typing_var.get(),
            "mode": self.mode_var.get()
        }
        with open("config.json", 'w') as f:
            json.dump(data, f, indent=4)

    def select_media(self):
        path = filedialog.askopenfilename()
        if path:
            self.media_path_var.set(path)

    def update_accounts_list(self):
        self.account_listbox.delete(0, tk.END)
        for acc in self.account_manager.accounts:
            self.account_listbox.insert(tk.END, acc["phone"])

    def add_account_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Добавить аккаунт")
        dialog.geometry("400x200")
        tk.Label(dialog, text="API ID:").grid(row=0, column=0)
        api_id_entry = tk.Entry(dialog)
        api_id_entry.grid(row=0, column=1)
        tk.Label(dialog, text="API Hash:").grid(row=1, column=0)
        api_hash_entry = tk.Entry(dialog)
        api_hash_entry.grid(row=1, column=1)
        tk.Label(dialog, text="Номер телефона:").grid(row=2, column=0)
        phone_entry = tk.Entry(dialog)
        phone_entry.grid(row=2, column=1)

        def save():
            api_id = int(api_id_entry.get())
            api_hash = api_hash_entry.get()
            phone = phone_entry.get()
            self.account_manager.add_account(api_id, api_hash, phone)
            self.update_accounts_list()
            dialog.destroy()

        tk.Button(dialog, text="Сохранить", command=save).grid(row=3, column=0, columnspan=2)

    def remove_account(self):
        sel = self.account_listbox.curselection()
        if sel:
            self.account_manager.remove_account(sel[0])
            self.update_accounts_list()

    def log(self, msg):
        self.log_area.insert(tk.END, f"{msg}\n")
        self.log_area.see(tk.END)

    def start_broadcast(self):
        if self.account_listbox.size() == 0:
            messagebox.showerror("Ошибка", "Добавьте хотя бы один аккаунт")
            return
        idx = self.account_listbox.curselection()
        if not idx:
            messagebox.showerror("Ошибка", "Выберите аккаунт")
            return
        self.save_settings_to_config()

        self.running = True
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.current_account_index = idx[0]

        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_async, daemon=True)
        self.thread.start()

    def _run_async(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._async_broadcast())

    async def _async_broadcast(self):
        client = None
        try:
            client = await self.account_manager.get_client(self.current_account_index)
            with open("config.json", 'r') as f:
                data = json.load(f)
            settings = data["broadcast_settings"]
            notifier = None
            bot_token = data.get("notification_bot", {}).get("token", "")
            bot_chat_id = data.get("notification_bot", {}).get("chat_id", "")
            if bot_token and bot_chat_id and bot_token != "ВАШ_ТОКЕН_БОТА" and bot_chat_id != "ВАШ_CHAT_ID":
                notifier = Notifier(bot_token, bot_chat_id)
            self.broadcast_manager = BroadcastManager(client, settings, notifier, log_callback=self.log)
            await self.broadcast_manager.broadcast_to_all_chats()
        except Exception as e:
            self.log(f"Ошибка в процессе рассылки: {e}")
        finally:
            if client:
                await self.account_manager.close_client(self.current_account_index)
            self.root.after(0, self._stop_broadcast_cleanup)

    def _stop_broadcast_cleanup(self):
        self.running = False
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        if self.loop and self.loop.is_running():
            async def cancel_tasks():
                tasks = [t for t in asyncio.all_tasks(self.loop) if t is not asyncio.current_task()]
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            asyncio.run_coroutine_threadsafe(cancel_tasks(), self.loop)
            self.loop.call_soon_threadsafe(self.loop.stop)
        self.log("Рассылка остановлена.")

    def stop_broadcast(self):
        if not self.running:
            return
        if self.broadcast_manager:
            self.broadcast_manager.running = False
        self.log("Остановка рассылки...")