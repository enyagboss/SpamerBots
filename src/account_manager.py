import os
import json
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from utils.logger import get_logger

logger = get_logger(__name__)
ACCOUNTS_DIR = "accounts"
os.makedirs(ACCOUNTS_DIR, exist_ok=True)

class AccountManager:
    def __init__(self, config_path="config.json", gui_callback=None):
        self.config_path = config_path
        self.gui_callback = gui_callback  # async function(type, phone) -> str
        self.accounts = []
        self.active_clients = {}
        self.load_accounts()

    def load_accounts(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.accounts = data.get("accounts", [])
        else:
            self.accounts = []

    def save_accounts(self):
        with open(self.config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data["accounts"] = self.accounts
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)

    def add_account(self, api_id: int, api_hash: str, phone: str):
        session_name = os.path.join(ACCOUNTS_DIR, f"user_{phone.replace('+', '')}")
        self.accounts.append({
            "api_id": api_id,
            "api_hash": api_hash,
            "phone": phone,
            "session_name": session_name
        })
        self.save_accounts()
        return session_name

    def remove_account(self, index: int):
        if 0 <= index < len(self.accounts):
            removed = self.accounts.pop(index)
            session_file = removed["session_name"] + ".session"
            if os.path.exists(session_file):
                os.remove(session_file)
            self.save_accounts()

    async def get_client(self, account_index: int):
        if account_index in self.active_clients:
            return self.active_clients[account_index]
        acc = self.accounts[account_index]
        client = TelegramClient(acc["session_name"], acc["api_id"], acc["api_hash"])
        await client.connect()
        if not await client.is_user_authorized():
            await client.send_code_request(acc["phone"])
            if self.gui_callback:
                code = await self.gui_callback("code", acc["phone"])
            else:
                # fallback to console input
                try:
                    code = input(f"Enter code for {acc['phone']}: ")
                except EOFError:
                    raise Exception("No console input available. Provide gui_callback or run interactively.")
            try:
                await client.sign_in(acc["phone"], code)
            except SessionPasswordNeededError:
                if self.gui_callback:
                    pwd = await self.gui_callback("password", acc["phone"])
                else:
                    try:
                        pwd = input(f"2FA password for {acc['phone']}: ")
                    except EOFError:
                        raise Exception("No console input available.")
                await client.sign_in(password=pwd)
        self.active_clients[account_index] = client
        return client

    async def close_client(self, account_index: int):
        if account_index in self.active_clients:
            client = self.active_clients.pop(account_index)
            try:
                await client.disconnect()
            except Exception as e:
                logger.error(f"Ошибка при отключении клиента: {e}")
