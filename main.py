import asyncio
import json
import os
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from src.account_manager import AccountManager
from src.broadcaster import BroadcastManager
from src.notifier import Notifier

with open("config.json", 'r', encoding='utf-8') as f:
    config = json.load(f)
TOKEN = config["notification_bot"]["token"]
CHAT_ID = str(config["notification_bot"]["chat_id"])

stop_loop = False
current_broadcast_task = None
waiting_for_input = {}  # {chat_id: {'type': 'code'/'password'/'message'/'interval', 'account_index': idx, 'phone': phone}}

main_keyboard = ReplyKeyboardMarkup([
    [KeyboardButton("🚀 Начать рассылку")],
    [KeyboardButton("⏹ Завершить рассылку")],
    [KeyboardButton("✏️ Изменить текст")],
    [KeyboardButton("⏱ Изменить интервал")],
    [KeyboardButton("📊 Статистика")],
    [KeyboardButton("📜 Логи")]
], resize_keyboard=True, one_time_keyboard=False)

def is_authorized(update):
    return str(update.effective_chat.id) == CHAT_ID

async def ask_code_or_password(type_: str, phone: str, account_index: int):
    """Callback для AccountManager – отправляет запрос через бота и ждёт ответ"""
    global waiting_for_input
    chat_id = int(CHAT_ID)
    waiting_for_input[chat_id] = {
        'type': type_,
        'account_index': account_index,
        'phone': phone
    }
    # Отправляем сообщение пользователю
    bot = Application.current().bot if hasattr(Application, 'current') else None
    if bot is None:
        # fallback: используем глобальный экземпляр бота (создадим в main)
        bot = _global_bot
    if type_ == 'code':
        await bot.send_message(chat_id, f"📱 Введите код подтверждения для {phone}:")
    else:
        await bot.send_message(chat_id, f"🔐 Введите пароль 2FA для {phone}:")
    # Ждём, пока пользователь ответит
    while chat_id in waiting_for_input and waiting_for_input[chat_id].get('type') == type_:
        await asyncio.sleep(0.5)
    result = waiting_for_input[chat_id].get('value')
    del waiting_for_input[chat_id]
    return result

# Глобальная переменная для бота (заполняется в main)
_global_bot = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("❌ Не авторизован")
        return
    await update.message.reply_text(
        "🤖 *Бот управления рассылкой*\nИспользуйте кнопки ниже.",
        reply_markup=main_keyboard,
        parse_mode='Markdown'
    )

async def broadcast_loop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global stop_loop
    acc_mgr = AccountManager(gui_callback=ask_code_or_password)
    notifier = Notifier(TOKEN, CHAT_ID)

    while not stop_loop:
        with open("config.json", 'r') as f:
            settings = json.load(f)["broadcast_settings"]
        interval_hours = settings.get("interval_hours", 1)
        interval_seconds = interval_hours * 3600

        await update.message.reply_text(f"🔄 Новый цикл рассылки (интервал {interval_hours} ч)")

        for idx, acc in enumerate(acc_mgr.accounts):
            if stop_loop:
                break
            try:
                client = await acc_mgr.get_client(idx)
                broadcaster = BroadcastManager(client, settings, notifier)
                await broadcaster.broadcast_to_all_chats()
                await client.disconnect()
                await update.message.reply_text(f"✅ {acc['phone']}: отправлено {broadcaster.sent_count}")
            except Exception as e:
                await update.message.reply_text(f"❌ {acc['phone']}: {e}")

        if not stop_loop:
            await update.message.reply_text(f"💤 Цикл завершён. Ожидание {interval_hours} час(ов)...")
            for _ in range(int(interval_seconds)):
                if stop_loop:
                    break
                await asyncio.sleep(1)

    await update.message.reply_text("🔴 Рассылка полностью остановлена.")

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global stop_loop, current_broadcast_task, waiting_for_input
    if not is_authorized(update):
        await update.message.reply_text("❌ Не авторизован")
        return
    text = update.message.text
    chat_id = update.effective_chat.id

    # Если ожидаем ввод кода/пароля/текста/интервала
    if chat_id in waiting_for_input:
        # Если ожидается код или пароль
        if waiting_for_input[chat_id]['type'] in ('code', 'password'):
            waiting_for_input[chat_id]['value'] = text
            return
        # Если ожидается изменение текста или интервала
        elif waiting_for_input[chat_id]['type'] == 'message':
            with open("config.json", 'r') as f:
                data = json.load(f)
            data["broadcast_settings"]["message"] = text
            with open("config.json", 'w') as f:
                json.dump(data, f, indent=4)
            await update.message.reply_text(f"✅ Текст обновлён:\n{text}")
            del waiting_for_input[chat_id]
            return
        elif waiting_for_input[chat_id]['type'] == 'interval':
            try:
                val = float(text)
                if val <= 0:
                    raise ValueError
                with open("config.json", 'r') as f:
                    data = json.load(f)
                data["broadcast_settings"]["interval_hours"] = val
                with open("config.json", 'w') as f:
                    json.dump(data, f, indent=4)
                await update.message.reply_text(f"✅ Интервал обновлён: {val} ч")
            except:
                await update.message.reply_text("❌ Неверный формат. Введите положительное число.")
            del waiting_for_input[chat_id]
            return

    # Обработка основных кнопок
    if text == "🚀 Начать рассылку":
        if current_broadcast_task and not current_broadcast_task.done():
            await update.message.reply_text("ℹ️ Рассылка уже запущена. Сначала остановите.")
            return
        stop_loop = False
        await update.message.reply_text("🚀 Запускаю циклическую рассылку...")
        current_broadcast_task = asyncio.create_task(broadcast_loop(update, context))

    elif text == "⏹ Завершить рассылку":
        stop_loop = True
        if current_broadcast_task:
            current_broadcast_task.cancel()
            current_broadcast_task = None
        await update.message.reply_text("⏹ Рассылка остановлена.")

    elif text == "✏️ Изменить текст":
        waiting_for_input[chat_id] = {'type': 'message'}
        await update.message.reply_text("Введите новый текст сообщения для рассылки:")

    elif text == "⏱ Изменить интервал":
        waiting_for_input[chat_id] = {'type': 'interval'}
        await update.message.reply_text("Введите новый интервал между циклами (в часах):")

    elif text == "📊 Статистика":
        stats_file = "stats.json"
        if os.path.exists(stats_file):
            with open(stats_file, 'r') as f:
                stats = json.load(f)
            total_sent = stats.get("total_sent", 0)
            last_reset = stats.get("last_reset", "неизвестно")
        else:
            total_sent = 0
            last_reset = "никогда"
        await update.message.reply_text(
            f"📊 *Общая статистика*\nВсего отправлено: {total_sent}\nПоследний сброс: {last_reset}",
            parse_mode='Markdown'
        )

    elif text == "📜 Логи":
        log_file = "logs/broadcast.log"
        if not os.path.exists(log_file):
            await update.message.reply_text("📜 Лог-файл не найден.")
        else:
            with open(log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            last_lines = lines[-30:] if len(lines) > 30 else lines
            log_text = "".join(last_lines)[-4000:]
            await update.message.reply_text(f"📜 *Последние логи:*\n```\n{log_text}\n```", parse_mode='Markdown')

def main():
    global _global_bot
    app = Application.builder().token(TOKEN).build()
    _global_bot = app.bot
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))
    app.run_polling()

if __name__ == "__main__":
    main()
