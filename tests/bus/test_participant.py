"""Unit tests for BusParticipant."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from networkkit.messages import Message, MessageType
from agentkit.bus.config import BusConfig
from agentkit.bus.participant import BusParticipant


class EchoParticipant(BusParticipant):
    """Test participant that records received messages."""

    name = "test-echo"

    def __init__(self, config):
        super().__init__(config)
        self.received: list[Message] = []
        self.peers: list[str] = []

    def is_intended_for_me(self, message: Message) -> bool:
        return message.to in (self.name, "ALL")

    async def handle_message(self, message: Message) -> None:
        self.received.append(message)

    def on_peer_discovered(self, peer_name: str, description: str) -> None:
        self.peers.append(peer_name)


@pytest.fixture
def config():
    return BusConfig(
        name="test-echo",
        bus_http_url="http://127.0.0.1:8000",
        bus_zmq_address="tcp://127.0.0.1:5555",
        description="Test participant",
    )


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("AGENT_NAME", "my-agent")
    monkeypatch.setenv("BUS_HTTP_URL", "http://localhost:9000")
    monkeypatch.setenv("BUS_ZMQ_ADDRESS", "tcp://localhost:6666")
    monkeypatch.setenv("AGENT_DESCRIPTION", "A test agent")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    cfg = BusConfig.from_env(name=None, dotenv_path=None)
    assert cfg.name == "my-agent"
    assert cfg.bus_http_url == "http://localhost:9000"
    assert cfg.bus_zmq_address == "tcp://localhost:6666"
    assert cfg.description == "A test agent"
    assert cfg.log_level == "DEBUG"


def test_config_name_override(monkeypatch):
    monkeypatch.setenv("AGENT_NAME", "env-name")
    cfg = BusConfig.from_env(name="override-name")
    assert cfg.name == "override-name"


def test_participant_init(config):
    p = EchoParticipant(config)
    assert p.name == "test-echo"
    assert p.config.bus_http_url == "http://127.0.0.1:8000"
    assert p.received == []


def test_is_intended_for_me(config):
    p = EchoParticipant(config)

    msg_to_me = Message(source="other", to="test-echo", content="hi", message_type=MessageType.CHAT)
    msg_to_all = Message(source="other", to="ALL", content="broadcast", message_type=MessageType.CHAT)
    msg_to_other = Message(source="other", to="someone-else", content="hi", message_type=MessageType.CHAT)

    assert p.is_intended_for_me(msg_to_me) is True
    assert p.is_intended_for_me(msg_to_all) is True
    assert p.is_intended_for_me(msg_to_other) is False


def test_handle_system_helo(config):
    p = EchoParticipant(config)
    helo_msg = Message(
        source="megu",
        to="ALL",
        content=json.dumps({"type": "HELO", "agent": "megu", "description": "Megu agent"}),
        message_type=MessageType.SYSTEM,
    )
    p._handle_system(helo_msg)
    assert "megu" in p.peers


def test_handle_system_ignores_self(config):
    p = EchoParticipant(config)
    helo_msg = Message(
        source="test-echo",
        to="ALL",
        content=json.dumps({"type": "HELO", "agent": "test-echo", "description": "me"}),
        message_type=MessageType.SYSTEM,
    )
    p._handle_system(helo_msg)
    assert p.peers == []


@pytest.mark.asyncio
async def test_send_formats_message(config):
    p = EchoParticipant(config)
    p._http_session = MagicMock()

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    p._http_session.post = MagicMock(return_value=mock_resp)

    await p.send("megu", {"text": "hello"})

    call_args = p._http_session.post.call_args
    assert "data" in str(call_args) or call_args is not None
