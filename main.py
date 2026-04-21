#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import json
import os
import random
import time
from datetime import datetime
from telethon import TelegramClient, errors
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ==================== КОНФИГУРАЦИЯ ====================
CONFIG_FILE = "config.json"
CHATS_FILE = "chats.txt"
STATS_FILE = "stats.json"
ACCOUNTS_DIR = "accounts"
os.makedirs(ACCOUNTS_DIR, exist_ok=True)

# Загрузка конфига
if not os.path.exists(CONFIG_FILE):
    default_config = {
        "broadcast_settings": {
            "message": "Привет! Это автоматическое сообщение.",
            "media_path": None,
            "interval_hours": 1,
            "delay_range": "30-60",
            "use_human_delays": True,
            "typing_emulation": True,
            "mode": "file"
        },
        "notification_bot": {
            "token": "ВАШ_ТОКЕН",
            "chat_id": "ВАШ_CHAT_ID"
        },
        "accounts": []
    }
    with open(CONFIG_FILE, "w") as f:
        json.dump(default_config, f, indent=4)

with open(CONFIG_FILE, "r") as f:
    config = json.load(f)

TOKEN = config["notification_bot"]["token"]
CHAT_ID = str(config["notification_bot"]["chat_id"])

# Глобальные состояния
stop_loop = False
current_broadcast_task = None
waiting_for_input = {}  # {chat_id: {'type': ..., 'account_index': ...}}

# Клавиатура
main_keyboard = ReplyKeyboardMarkup([
    [KeyboardButton("🚀 Начать рассылку")],
    [KeyboardButton("⏹ Завершить рассылку")],
    [KeyboardButton("➕ Добавить аккаунт")],
    [KeyboardButton("🗑 Удалить аккаунт")],
    [KeyboardButton("✏️ Изменить текст")],
    [KeyboardButton("⏱ Изменить интервал")],
    [KeyboardButton("📊 Статистика")],
    [KeyboardButton("📜 Логи")]
], resize_keyboard=True, one_time_keyboard=False)

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def is_authorized(update):
    return str(update.effective_chat.id) == CHAT_ID

def log_message(msg):
    """Пишет в консоль и в файл лога"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {msg}"
    print(log_entry)
    with open("logs/broadcast.log", "a", encoding="utf-8") as f:
        f.write(log_entry + "\n")

async def update_stats(increment=1):
    stats = {}
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, "r") as f:
            stats = json.load(f)
    stats["total_sent"] = stats.get("total_sent", 0) + increment
    stats["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, indent=4)

def load_accounts():
    with open(CONFIG_FILE, "r") as f:
        data = json.load(f)
    return data.get("accounts", [])

def save_accounts(accounts):
    with open(CONFIG_FILE, "r") as f:
        data = json.load(f)
    data["accounts"] = accounts
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)

# ==================== РАБОТА С АККАУНТАМИ ====================
class AccountManager:
    def __init__(self):
        self.accounts = load_accounts()
        self.active_clients = {}

    async def get_client(self, index):
        if index in self.active_clients:
            return self.active_clients[index]
        acc = self.accounts[index]
        session_path = os.path.join(ACCOUNTS_DIR, f"user_{acc['phone'].replace('+', '')}")
        client = TelegramClient(session_path, acc["api_id"], acc["api_hash"])
        await client.connect()
        if not await client.is_user_authorized():
            await client.send_code_request(acc["phone"])
            # Код нужно ввести в консоли (при запуске на сервере)
            code = input(f"Введите код для {acc['phone']}: ")
            try:
                await client.sign_in(acc["phone"], code)
            except errors.SessionPasswordNeededError:
                pwd = input(f"2FA пароль для {acc['phone']}: ")
                await client.sign_in(password=pwd)
        self.active_clients[index] = client
        return client

    async def close_client(self, index):
        if index in self.active_clients:
            await self.active_clients[index].disconnect()
            del self.active_clients[index]

# ==================== РАССЫЛКА ====================
class BroadcastManager:
    def __init__(self, client, settings, notifier=None):
        self.client = client
        self.settings = settings
        self.notifier = notifier
        self.sent_count = 0
        self.running = True

    async def join_chat(self, chat_link):
        try:
            if 't.me/joinchat/' in chat_link:
                hash_part = chat_link.split('joinchat/')[-1].split('?')[0]
                await self.client(ImportChatInviteRequest(hash_part))
            else:
                entity = await self.client.get_entity(chat_link)
                await self.client(JoinChannelRequest(entity))
            return True
        except errors.UserAlreadyParticipantError:
            return True
        except Exception as e:
            log_message(f"Ошибка вступления {chat_link}: {e}")
            return False

    async def send_to_chat(self, entity, link=None):
        name = getattr(entity, 'title', None) or getattr(entity, 'first_name', str(entity.id))
        try:
            if self.settings.get("typing_emulation"):
                async with self.client.action(entity, 'typing'):
                    await asyncio.sleep(random.uniform(2, 5))
            media = self.settings.get("media_path")
            if media and os.path.exists(media):
                await self.client.send_file(entity, media, caption=self.settings["message"])
            else:
                await self.client.send_message(entity, self.settings["message"])
            self.sent_count += 1
            await update_stats()
            log_message(f"✓ Отправлено в {name}")
            return True
        except errors.ChatWriteForbiddenError:
            log_message(f"⛔ Бан в {name}, покидаем")
            try:
                await self.client.delete_dialog(entity)
            except:
                pass
            if link and self.settings.get("mode") == "file":
                # удаляем ссылку из chats.txt
                with open(CHATS_FILE, "r") as f:
                    lines = f.readlines()
                with open(CHATS_FILE, "w") as f:
                    for line in lines:
                        if link not in line:
                            f.write(line)
        except errors.FloodWaitError as e:
            log_message(f"⚠️ FloodWait {e.seconds} в {name}")
            await asyncio.sleep(e.seconds)
        except Exception as e:
            log_message(f"❌ Ошибка в {name}: {e}")
        return False

    async def broadcast(self):
        mode = self.settings.get("mode", "file")
        if mode == "all":
            dialogs = await self.client.get_dialogs()
            targets = [(d.entity, None) for d in dialogs if not (d.is_user and d.entity.is_self) and d.name != "Saved Messages"]
            log_message(f"🚀 Рассылка во все чаты ({len(targets)} чатов)")
        else:
            if not os.path.exists(CHATS_FILE):
                log_message("Файл chats.txt не найден")
                return
            with open(CHATS_FILE, "r") as f:
                lines = [l.strip() for l in f if l.strip() and not l.startswith('#')]
            targets = []
            for link in lines:
                if await self.join_chat(link):
                    entity = await self.client.get_entity(link)
                    targets.append((entity, link))
                else:
                    log_message(f"⚠️ Не вступили в {link}")
            log_message(f"🚀 Рассылка по файлу ({len(targets)} чатов)")

        delay_str = self.settings.get("delay_range", "30-60")
        if '-' in delay_str:
            dmin, dmax = map(float, delay_str.split('-'))
        else:
            dmin = dmax = float(delay_str)
        use_human = self.settings.get("use_human_delays", True)

        for entity, link in targets:
            if not self.running:
                break
            await self.send_to_chat(entity, link)
            if use_human:
                delay = random.expovariate(1.0 / ((dmin + dmax) / 2))
                delay = max(dmin, min(delay, dmax))
            else:
                delay = random.uniform(dmin, dmax)
            await asyncio.sleep(delay)

        log_message(f"✅ Рассылка завершена. Отправлено {self.sent_count}")

# ==================== ОСНОВНАЯ ЛОГИКА БОТА ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("❌ Не авторизован")
        return
    await update.message.reply_text(
        "🤖 *Telegram Broadcaster Bot*\nУправление рассылкой через кнопки.",
        reply_markup=main_keyboard,
        parse_mode='Markdown'
    )

async def broadcast_loop(update: Update):
    global stop_loop
    stop_loop = False
    acc_mgr = AccountManager()
    if not acc_mgr.accounts:
        await update.message.reply_text("❌ Нет добавленных аккаунтов. Добавьте через кнопку.")
        return
    await update.message.reply_text("🚀 Запуск циклической рассылки...")
    while not stop_loop:
        with open(CONFIG_FILE, "r") as f:
            settings = json.load(f)["broadcast_settings"]
        interval = settings.get("interval_hours", 1) * 3600
        await update.message.reply_text(f"🔄 Новый цикл (интервал {interval/3600} ч)")
        for idx, acc in enumerate(acc_mgr.accounts):
            if stop_loop:
                break
            try:
                client = await acc_mgr.get_client(idx)
                broadcaster = BroadcastManager(client, settings)
                await broadcaster.broadcast()
                await acc_mgr.close_client(idx)
                await update.message.reply_text(f"✅ {acc['phone']}: {broadcaster.sent_count} сообщений")
            except Exception as e:
                await update.message.reply_text(f"❌ {acc['phone']}: {e}")
        if not stop_loop:
            await update.message.reply_text(f"💤 Ожидание {interval/3600} ч...")
            for _ in range(int(interval)):
                if stop_loop:
                    break
                await asyncio.sleep(1)
    await update.message.reply_text("🔴 Рассылка остановлена")

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global stop_loop, current_broadcast_task, waiting_for_input
    if not is_authorized(update):
        await update.message.reply_text("❌ Не авторизован")
        return
    text = update.message.text
    chat_id = update.effective_chat.id

    # Обработка ввода данных для добавления аккаунта
    if chat_id in waiting_for_input:
        data = waiting_for_input[chat_id]
        if data['type'] == 'add_account':
            # ожидаем: api_id, api_hash, phone
            step = data.get('step', 0)
            if step == 0:
                try:
                    data['api_id'] = int(text)
                    data['step'] = 1
                    await update.message.reply_text("Введите API Hash:")
                except:
                    await update.message.reply_text("❌ API ID должно быть числом. Попробуйте снова:")
                return
            elif step == 1:
                data['api_hash'] = text.strip()
                data['step'] = 2
                await update.message.reply_text("Введите номер телефона (в формате +1234567890):")
                return
            elif step == 2:
                phone = text.strip()
                if not phone.startswith('+'):
                    phone = '+' + phone
                # сохраняем аккаунт
                with open(CONFIG_FILE, "r") as f:
                    cfg = json.load(f)
                cfg["accounts"].append({
                    "api_id": data['api_id'],
                    "api_hash": data['api_hash'],
                    "phone": phone
                })
                with open(CONFIG_FILE, "w") as f:
                    json.dump(cfg, f, indent=4)
                await update.message.reply_text(f"✅ Аккаунт {phone} добавлен.")
                del waiting_for_input[chat_id]
                return
        elif data['type'] == 'remove_account':
            try:
                idx = int(text) - 1
                with open(CONFIG_FILE, "r") as f:
                    cfg = json.load(f)
                if 0 <= idx < len(cfg["accounts"]):
                    removed = cfg["accounts"].pop(idx)
                    with open(CONFIG_FILE, "w") as f:
                        json.dump(cfg, f, indent=4)
                    await update.message.reply_text(f"✅ Аккаунт {removed['phone']} удалён.")
                else:
                    await update.message.reply_text("❌ Неверный номер.")
            except:
                await update.message.reply_text("❌ Ошибка. Введите номер из списка.")
            del waiting_for_input[chat_id]
            return
        elif data['type'] == 'message':
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
            cfg["broadcast_settings"]["message"] = text
            with open(CONFIG_FILE, "w") as f:
                json.dump(cfg, f, indent=4)
            await update.message.reply_text("✅ Текст обновлён.")
            del waiting_for_input[chat_id]
            return
        elif data['type'] == 'interval':
            try:
                val = float(text)
                if val <= 0: raise ValueError
                with open(CONFIG_FILE, "r") as f:
                    cfg = json.load(f)
                cfg["broadcast_settings"]["interval_hours"] = val
                with open(CONFIG_FILE, "w") as f:
                    json.dump(cfg, f, indent=4)
                await update.message.reply_text(f"✅ Интервал установлен {val} ч.")
            except:
                await update.message.reply_text("❌ Введите положительное число.")
            del waiting_for_input[chat_id]
            return

    # Основные кнопки
    if text == "🚀 Начать рассылку":
        if current_broadcast_task and not current_broadcast_task.done():
            await update.message.reply_text("ℹ️ Рассылка уже идёт.")
            return
        current_broadcast_task = asyncio.create_task(broadcast_loop(update))

    elif text == "⏹ Завершить рассылку":
        stop_loop = True
        if current_broadcast_task:
            current_broadcast_task.cancel()
            current_broadcast_task = None
        await update.message.reply_text("⏹ Рассылка остановлена.")

    elif text == "➕ Добавить аккаунт":
        waiting_for_input[chat_id] = {'type': 'add_account', 'step': 0}
        await update.message.reply_text("Введите API ID:")

    elif text == "🗑 Удалить аккаунт":
        with open(CONFIG_FILE, "r") as f:
            cfg = json.load(f)
        accounts = cfg["accounts"]
        if not accounts:
            await update.message.reply_text("Нет аккаунтов для удаления.")
            return
        msg = "Выберите номер для удаления:\n"
        for i, acc in enumerate(accounts, 1):
            msg += f"{i}. {acc['phone']}\n"
        waiting_for_input[chat_id] = {'type': 'remove_account'}
        await update.message.reply_text(msg)

    elif text == "✏️ Изменить текст":
        waiting_for_input[chat_id] = {'type': 'message'}
        await update.message.reply_text("Введите новый текст сообщения:")

    elif text == "⏱ Изменить интервал":
        waiting_for_input[chat_id] = {'type': 'interval'}
        await update.message.reply_text("Введите интервал (часы):")

    elif text == "📊 Статистика":
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, "r") as f:
                stats = json.load(f)
            total = stats.get("total_sent", 0)
            last = stats.get("last_update", "неизвестно")
            await update.message.reply_text(f"📊 *Статистика*\nВсего отправлено: {total}\nПоследнее обновление: {last}", parse_mode='Markdown')
        else:
            await update.message.reply_text("Статистика пока пуста.")

    elif text == "📜 Логи":
        log_path = "logs/broadcast.log"
        if not os.path.exists(log_path):
            await update.message.reply_text("Лог-файл не найден.")
        else:
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            last_lines = lines[-30:] if len(lines) > 30 else lines
            log_text = "".join(last_lines)
            if len(log_text) > 4000:
                log_text = log_text[-4000:]
            await update.message.reply_text(f"📜 *Последние логи:*\n```\n{log_text}\n```", parse_mode='Markdown')

    else:
        await update.message.reply_text("Используйте кнопки меню.")

def main():
    # Создаём папку для логов
    os.makedirs("logs", exist_ok=True)
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))
    log_message("Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()
