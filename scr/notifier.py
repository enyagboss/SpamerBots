import asyncio
import json
import os
from telegram import Bot
from telegram.error import TelegramError
from utils.logger import get_logger
from datetime import datetime

logger = get_logger(__name__)

class Notifier:
    def __init__(self, token: str, chat_id: str):
        self.bot = Bot(token=token)
        self.chat_id = chat_id

    async def send_notification(self, text: str):
        try:
            await self.bot.send_message(chat_id=self.chat_id, text=text)
        except TelegramError as e:
            logger.error(f"Не удалось отправить уведомление: {e}")

    def send_sync(self, text: str):
        asyncio.create_task(self.send_notification(text))

    async def update_stats(self, increment: int = 1):
        """Увеличивает счётчик отправленных сообщений в stats.json"""
        stats_file = "stats.json"
        stats = {}
        if os.path.exists(stats_file):
            with open(stats_file, 'r') as f:
                stats = json.load(f)
        stats["total_sent"] = stats.get("total_sent", 0) + increment
        stats["last_reset"] = stats.get("last_reset", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        with open(stats_file, 'w') as f:
            json.dump(stats, f, indent=4)