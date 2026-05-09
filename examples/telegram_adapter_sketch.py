"""Sketch: Telegram adapter rewritten with agentkit BusParticipant.

This is NOT runnable yet — it shows the target API shape for validation.
The actual migration will replace networkkit-telegram-adapter-*/adapter.py.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from networkkit.messages import Message

from agentkit import BusParticipant, BusConfig


log = logging.getLogger(__name__)


class TelegramAdapter(BusParticipant):
    """Bridges Telegram <-> NetworkKit bus for a single agent."""

    name = "telegram-adapter"

    def __init__(self, config: BusConfig, agent_name: str, bot_token: str, allowed_chats: set[int]):
        super().__init__(config)
        self.agent_name = agent_name
        self.bot_token = bot_token
        self.allowed_chats = allowed_chats
        self.bot = None  # initialized in on_start

    def is_intended_for_me(self, message: Message) -> bool:
        src = message.source.lower().removeprefix("bridge:")
        agent = self.agent_name.lower()
        if not (src == agent or src.startswith(f"{agent}:")):
            return False
        # Must be addressed to a telegram chat
        return message.to.startswith("telegram:")

    async def handle_message(self, message: Message) -> None:
        """Outbound: agent response -> Telegram."""
        chat_id = int(message.to.split(":")[1])
        if chat_id not in self.allowed_chats:
            return

        try:
            content = json.loads(message.content)
        except (json.JSONDecodeError, TypeError):
            content = {"text": str(message.content)}

        text = content.get("text", "")
        file_path = content.get("file_path", "")

        if file_path and Path(file_path).is_file():
            with open(file_path, "rb") as f:
                await self.bot.send_document(chat_id=chat_id, document=f)
        elif text:
            for i in range(0, len(text), 4096):
                await self.bot.send_message(chat_id=chat_id, text=text[i:i + 4096])

    async def on_start(self) -> None:
        """Start Telegram bot polling in background."""
        from telegram import Bot
        self.bot = Bot(token=self.bot_token)
        await self.bot.initialize()
        # Would start inbound polling here (telegram.ext.Application)
        log.info("Telegram bot initialized for agent=%s", self.agent_name)

    async def on_stop(self) -> None:
        """Shutdown telegram bot."""
        if self.bot:
            await self.bot.shutdown()


# Usage:
# config = BusConfig.from_env(name="telegram-megu")
# adapter = TelegramAdapter(config, agent_name="megu", bot_token="...", allowed_chats={123456})
# adapter.run()
