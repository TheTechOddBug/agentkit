"""VoiceService — BusParticipant for the voice WebSocket ↔ NetworkKit bridge.

Runs a FastAPI server (TTS/STT/WebSocket) with bus integration.
Incoming speech → STT → bus message. Bus reply → TTS → WebSocket audio.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from networkkit.messages import Message, MessageType

from agentkit.bus.config import BusConfig
from agentkit.bus.participant import BusParticipant

log = logging.getLogger("agentkit.voice")


class VoiceService(BusParticipant):
    """Voice app as a BusParticipant.

    Manages pending WebSocket clients waiting for agent replies.
    When a message arrives addressed to 'voice-app', routes it to
    the waiting WebSocket client.
    """

    name = "voice-app"

    def __init__(self, config: BusConfig, fastapi_app: Any = None,
                 host: str = "0.0.0.0", port: int = 8801,
                 ssl_keyfile: str | None = None, ssl_certfile: str | None = None):
        super().__init__(config)
        self.fastapi_app = fastapi_app
        self.host = host
        self.port = port
        self.ssl_keyfile = ssl_keyfile
        self.ssl_certfile = ssl_certfile
        # Pending reply futures keyed by source filter
        self._pending_replies: dict[str, asyncio.Future] = {}

    def is_intended_for_me(self, message: Message) -> bool:
        to = message.to.lower()
        return to in ("voice-app", self.name)

    async def handle_message(self, message: Message) -> None:
        """Route bus reply to the waiting WebSocket client."""
        content = message.content
        if content.strip().startswith("{"):
            try:
                parsed = json.loads(content)
                content = parsed.get("text", content)
            except json.JSONDecodeError:
                pass

        # Deliver to any pending future
        to_deliver = list(self._pending_replies.keys())
        for key in to_deliver:
            fut = self._pending_replies.get(key)
            if fut and not fut.done():
                fut.set_result(content)
                del self._pending_replies[key]
                log.info("Delivered reply to pending client key=%s chars=%d", key, len(content))
                break

    async def wait_for_reply(self, request_id: str, timeout: float = 180) -> str | None:
        """Wait for a bus reply matching this request. Used by WebSocket handler."""
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending_replies[request_id] = fut
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_replies.pop(request_id, None)
            return None

    async def send_to_agent(self, agent: str, text: str, source: str = "voice-app") -> None:
        """Send a message to an agent via the bus."""
        from networkkit.messages import Message as _Msg, MessageType as _MT
        msg = _Msg(
            source=source,
            to=agent,
            content=json.dumps({"text": text}, ensure_ascii=False),
            message_type=_MT.CHAT,
        )
        await self._http_send(msg)

    async def on_start(self) -> None:
        """Start the FastAPI/uvicorn server as a background task."""
        if self.fastapi_app is None:
            log.warning("No FastAPI app provided, running bus-only")
            return

        import uvicorn

        uvi_config = uvicorn.Config(
            self.fastapi_app,
            host=self.host,
            port=self.port,
            ssl_keyfile=self.ssl_keyfile,
            ssl_certfile=self.ssl_certfile,
            log_level="info",
        )
        self._server = uvicorn.Server(uvi_config)
        # Run uvicorn in background — it yields control back via serve()
        asyncio.create_task(self._server.serve())
        log.info("FastAPI server starting on %s:%d", self.host, self.port)

    async def on_stop(self) -> None:
        """Shutdown uvicorn."""
        if hasattr(self, "_server"):
            self._server.should_exit = True
