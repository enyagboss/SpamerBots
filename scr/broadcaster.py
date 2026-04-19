# src/broadcaster.py
import asyncio
import random
import os
from telethon import errors
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.functions.channels import JoinChannelRequest
from utils.helpers import human_delay, emulate_typing, parse_delay_range
from utils.logger import get_logger

logger = get_logger(__name__)

class BroadcastManager:
    def __init__(self, client, settings: dict, notifier=None, log_callback=None, stop_event=None):
        self.client = client
        self.settings = settings
        self.notifier = notifier          # для отправки уведомлений в бота
        self.log_callback = log_callback  # для вывода в GUI
        self.stop_event = stop_event or asyncio.Event()
        self.running = False
        self.sent_count = 0
        self.replies_count = 0

    def _log(self, message):
        if self.log_callback:
            self.log_callback(message)
        logger.info(message)
        if self.notifier:
            # отправляем лог в бота асинхронно, не блокируя рассылку
            asyncio.create_task(self.notifier.send_notification(message))

    async def join_chat(self, chat_link: str):
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
            self._log(f"Ошибка вступления {chat_link}: {e}")
            return False

    async def leave_chat(self, chat_entity):
        try:
            await self.client.delete_dialog(chat_entity)
            self._log(f"Покинули чат {getattr(chat_entity, 'title', chat_entity.id)}")
            return True
        except Exception as e:
            self._log(f"Не удалось покинуть чат: {e}")
            return False

    async def remove_chat_from_file_by_entity(self, chat_entity, chat_link=None):
        filename = self.settings.get("chats_file", "chats.txt")
        try:
            search_strings = []
            if chat_link:
                search_strings.append(chat_link)
            if hasattr(chat_entity, 'username') and chat_entity.username:
                search_strings.append(f"@{chat_entity.username}")
                search_strings.append(f"https://t.me/{chat_entity.username}")
            search_strings.append(str(chat_entity.id))

            with open(filename, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            with open(filename, 'w', encoding='utf-8') as f:
                removed = False
                for line in lines:
                    if not removed and any(s in line for s in search_strings if s):
                        removed = True
                        self._log(f"Удалена строка: {line.strip()}")
                        continue
                    f.write(line)
            if not removed:
                self._log(f"Не найдена ссылка для удаления в {filename}")
        except Exception as e:
            self._log(f"Ошибка удаления ссылки: {e}")

    async def send_message_to_chat(self, chat_entity, chat_link=None):
        chat_name = getattr(chat_entity, 'title', None) or getattr(chat_entity, 'first_name', str(chat_entity.id))
        try:
            if self.settings.get("typing_emulation", False):
                await emulate_typing(self.client, chat_entity)
            media_path = self.settings.get("media_path")
            if media_path and os.path.exists(media_path):
                await self.client.send_file(chat_entity, media_path, caption=self.settings["message"])
            else:
                await self.client.send_message(chat_entity, self.settings["message"])
            self.sent_count += 1
            self._log(f"✓ Отправлено в {chat_name}")
            return True
        except errors.ChatWriteForbiddenError:
            self._log(f"⛔ Бан в {chat_name}. Покидаем чат и удаляем ссылку.")
            await self.leave_chat(chat_entity)
            if self.settings.get("mode") == "file" and self.settings.get("chats_file"):
                await self.remove_chat_from_file_by_entity(chat_entity, chat_link)
        except errors.FloodWaitError as e:
            self._log(f"⚠️ FloodWait {e.seconds} секунд в {chat_name}")
            await asyncio.sleep(e.seconds)
        except Exception as e:
            self._log(f"❌ Ошибка отправки в {chat_name}: {e}")
        return False

    async def broadcast_to_all_chats(self):
        self.running = True
        mode = self.settings.get("mode", "all")
        targets = []
        if mode == "all":
            dialogs = await self.client.get_dialogs()
            targets = [(d.entity, None) for d in dialogs if not (d.is_user and d.entity.is_self) and d.name != "Saved Messages"]
            self._log(f"🚀 Начинаем рассылку во все чаты аккаунта ({len(targets)} чатов)")
        else:
            chats_file = self.settings.get("chats_file", "chats.txt")
            try:
                with open(chats_file, 'r', encoding='utf-8') as f:
                    lines = [line.strip() for line in f if line.strip() and not line.startswith('#')]
            except Exception as e:
                self._log(f"Ошибка чтения {chats_file}: {e}")
                return
            self._log(f"🚀 Начинаем рассылку по списку из файла {chats_file} ({len(lines)} ссылок)")
            for link in lines:
                if self.stop_event.is_set():
                    break
                if await self.join_chat(link):
                    entity = await self.client.get_entity(link)
                    targets.append((entity, link))
                else:
                    self._log(f"⚠️ Не удалось вступить в {link}, пропускаем")

        delay_min, delay_max = parse_delay_range(str(self.settings.get("delay_range", "30-60")))
        use_human = self.settings.get("use_human_delays", False)

        for target, link in targets:
            if self.stop_event.is_set():
                self._log("⏹ Рассылка прервана пользователем")
                break
            if not self.running:
                break
            await self.send_message_to_chat(target, link)
            if use_human:
                await human_delay(delay_min, delay_max)
            else:
                await asyncio.sleep(random.uniform(delay_min, delay_max))

        if self.notifier:
            await self.notifier.send_notification(f"Рассылка завершена. Отправлено {self.sent_count} сообщений.")
        self._log(f"✅ Рассылка завершена. Отправлено {self.sent_count} сообщений.")
        self.running = False