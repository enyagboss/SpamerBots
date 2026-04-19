from flask import Flask, jsonify
import threading
import asyncio
import json
from src.account_manager import AccountManager
from src.broadcaster import BroadcastManager
from src.notifier import Notifier

app = Flask(__name__)

with open("config.json", 'r') as f:
    config = json.load(f)

def run_broadcast_async():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    acc_mgr = AccountManager()
    notifier = Notifier(config["notification_bot"]["token"], config["notification_bot"]["chat_id"])
    async def broadcast_all():
        for idx, acc in enumerate(acc_mgr.accounts):
            client = await acc_mgr.get_client(idx)
            with open("config.json", 'r') as f:
                settings = json.load(f)["broadcast_settings"]
            broadcaster = BroadcastManager(client, settings, notifier)
            await broadcaster.broadcast_to_all_chats()
            await client.disconnect()
    loop.run_until_complete(broadcast_all())

@app.route('/')
def index():
    return "Telegram Broadcaster Web Interface"

@app.route('/start_broadcast')
def start_broadcast():
    threading.Thread(target=run_broadcast_async).start()
    return jsonify({"status": "broadcast started"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
