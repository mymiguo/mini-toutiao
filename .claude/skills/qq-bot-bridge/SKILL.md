---
name: qq-bot-bridge
description: Set up QQ official bot as remote control for Claude Code. Use when user wants to interact with Claude Code via QQ messages, set up remote access, or bridge QQ to Claude CLI.
---

# QQ Bot Bridge — Remote Control Claude Code via QQ

Set up a QQ official bot to forward messages to Claude Code and return responses. The user sends messages on QQ, Claude Code processes them in the project directory, and results come back to QQ.

## Architecture

```
User QQ → QQ Server → WebSocket → qq_bridge.py → claude -c -p → Reply QQ
```

**No public domain or HTTPS needed** — uses QQ official WebSocket mode.

## Prerequisites

1. Register a QQ official bot at https://bot.q.qq.com
2. Get AppID and AppSecret from the bot management panel
3. Enable **C2C private chat** permission in the bot settings
4. Install Python dependency: `pip install qq-botpy`

## Setup

1. Create `qq_bridge_config.json` with bot credentials:

```json
{
    "appid": "your-appid",
    "appsecret": "your-appsecret",
    "claude_path": "C:\\Users\\...\\AppData\\Roaming\\npm\\claude.cmd",
    "project_dir": "C:\\Users\\...\\Desktop\\claude01",
    "session_ttl": 1800
}
```

2. Copy `qq_bridge.py` and `start_qq_bridge.bat` to the project directory.

3. Run `start_qq_bridge.bat` to start the bridge.

## Usage Commands (via QQ)

- Any text message → forwarded to Claude Code
- `/reset` → start a fresh conversation
- `/status` → check session status

## Conversation Continuity

Messages within 30 minutes automatically continue the same conversation via `claude -c -p`. After 30 minutes of inactivity, a new session starts.

## Rate Limits

QQ official bot limits personal developers to 5 passive replies per minute. Long responses are auto-split into chunks.

## Important Notes

- Bot QQ account should only be friended by the authorized user
- Keep `qq_bridge_config.json` out of version control (contains AppSecret)
- Claude Code must be installed and available on the machine
- The bridge must remain running for QQ messages to be processed
