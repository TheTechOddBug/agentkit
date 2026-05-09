# agentkit

SDK for building [networkkit](https://github.com/japanvik/networkkit) bus participants.

Any process that connects to the networkkit message bus — adapters, bridges, services — uses agentkit as its foundation. It handles the boilerplate: bus connection, HELO/ACK peer discovery, message routing, reconnection, signal handling, and graceful shutdown.

## Install

```bash
pip install agentkit
```

Requires `networkkit >= 0.0.2`.

## Quick Start

```python
from agentkit import BusParticipant, BusConfig
from networkkit.messages import Message

class MyService(BusParticipant):
    name = "my-service"

    def is_intended_for_me(self, message: Message) -> bool:
        return message.to == self.name

    async def handle_message(self, message: Message) -> None:
        print(f"Got: {message.content} from {message.source}")
        await self.send(message.source, {"text": "ack"})

config = BusConfig.from_env(name="my-service")
service = MyService(config)
service.run()
```

## What it does

- **Connects** to networkkit bus (HTTP sender + ZMQ subscriber)
- **Sends HELO** on startup, responds to peer HELO with ACK
- **Routes messages** through `is_intended_for_me()` filter
- **Reconnects** ZMQ with exponential backoff on failure
- **Handles signals** (SIGTERM/SIGINT) for graceful shutdown
- **Lifecycle hooks** (`on_start`, `on_stop`) for custom setup/teardown

## Configuration

`BusConfig.from_env()` reads from environment variables (or `.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_NAME` | `unnamed` | Participant name on the bus |
| `BUS_HTTP_URL` | `http://127.0.0.1:8000` | Bus HTTP API endpoint |
| `BUS_ZMQ_ADDRESS` | `tcp://127.0.0.1:5555` | Bus ZMQ PUB address |
| `AGENT_DESCRIPTION` | `""` | Description broadcast in HELO |
| `LOG_LEVEL` | `INFO` | Logging level |

## Architecture

```
networkkit (bus layer)     agentkit (client SDK)
┌─────────────────────┐    ┌─────────────────────────┐
│ HTTP API + ZMQ PUB  │◄───│ BusParticipant          │
│ Routing table       │    │  ├── connect()           │
│ HELO/ACK protocol   │    │  ├── send_helo()         │
│ Schedules           │    │  ├── message_loop()      │
│ Peer discovery      │    │  ├── reconnect()         │
└─────────────────────┘    │  └── shutdown()          │
                           └─────────────────────────┘
```

## Telegram Adapter

Built-in `TelegramAdapter` bridges Telegram chats to the networkkit bus:

```python
# adapter.py
from agentkit.bus.telegram import TelegramAdapter, TelegramConfig

config = TelegramConfig.from_env(dotenv_path=".env")
adapter = TelegramAdapter(config)
adapter.run()
```

`.env`:
```
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_ALLOWED_CHAT_IDS=123456789
MEGU_AGENT_NAME=megu
BUS_HTTP_URL=http://127.0.0.1:8000
BUS_ZMQ_ADDRESS=tcp://127.0.0.1:5555
```

Handles: text, photos, documents, video, voice (with STT), reactions, TTS replies, commands.

## Process Management (ctl)

`ProcessCtl` manages participant lifecycle — start, stop, restart, status, log:

```python
# ctl
#!/usr/bin/env python3
from agentkit.bus.ctl import run_ctl
run_ctl(name="adapter", script="./adapter.py")
```

```bash
./ctl start    # daemonize, write PID file
./ctl stop     # graceful SIGTERM, fallback SIGKILL
./ctl restart  # stop + start
./ctl status   # check if running
./ctl log      # tail last 20 lines
./ctl log -f   # follow log
```

Features:
- Auto-discovers `.venv/bin/python3` in the script's directory
- PID file management with stale PID cleanup
- Graceful shutdown (5s SIGTERM timeout before SIGKILL)

## Deployment Pattern

Each deployment directory is minimal — just config and thin wrappers:

```
my-adapter/
  .env          # secrets + config
  adapter.py    # 5 lines: import and call main()
  ctl           # 3 lines: import and call run_ctl()
```

All logic lives in agentkit. Updates are `pip install --upgrade agentkit`.

## Examples

See `examples/` for migration sketches showing how existing adapters and bridges map to the BusParticipant API.

## License

MIT
