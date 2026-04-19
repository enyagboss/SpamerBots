import random
import asyncio
import os
from typing import Tuple

async def human_delay(min_sec: float = 5, max_sec: float = 15):
    delay = random.expovariate(1.0 / ((min_sec + max_sec) / 2))
    delay = max(min_sec, min(delay, max_sec))
    await asyncio.sleep(delay)

async def emulate_typing(client, chat_id, duration: float = None):
    if duration is None:
        duration = random.uniform(2, 6)
    try:
        async with client.action(chat_id, 'typing'):
            await asyncio.sleep(duration)
    except Exception:
        pass

def parse_delay_range(delay_str: str) -> Tuple[float, float]:
    if '-' in delay_str:
        parts = delay_str.split('-')
        return float(parts[0]), float(parts[1])
    else:
        val = float(delay_str)
        return val, val
