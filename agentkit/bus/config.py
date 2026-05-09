"""Bus participant configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class BusConfig:
    """Configuration for a bus participant."""

    name: str
    bus_http_url: str = "http://127.0.0.1:8000"
    bus_zmq_address: str = "tcp://127.0.0.1:5555"
    description: str = ""
    pid_dir: Path = field(default_factory=lambda: Path.home() / ".local" / "share" / "agentkit" / "pids")
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, name: str | None = None, dotenv_path: str | None = None) -> BusConfig:
        if dotenv_path:
            load_dotenv(dotenv_path)
        else:
            load_dotenv()

        return cls(
            name=name or os.environ.get("AGENT_NAME", "unnamed"),
            bus_http_url=os.environ.get("BUS_HTTP_URL", "http://127.0.0.1:8000"),
            bus_zmq_address=os.environ.get("BUS_ZMQ_ADDRESS", "tcp://127.0.0.1:5555"),
            description=os.environ.get("AGENT_DESCRIPTION", ""),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )
