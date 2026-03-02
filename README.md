# WhatsMCP

WhatsApp bot powered by Claude Code SDK. Chat with Claude Code from your phone — ask it to analyze, edit, or explain code in natural language.

## Architecture

```
WhatsApp ←→ TextMeBot API ←→ WhatsMCP (FastAPI webhook + Claude Code SDK)
```

- **Receive**: TextMeBot POSTs incoming messages to `/webhook/incoming`
- **Send**: WhatsMCP calls the TextMeBot API directly
- **Process**: Claude Code SDK executes commands in the project directory
- **Standalone** — no cloud dependencies, runs as a single service

## Prerequisites

- Python 3.11+ (or Docker)
- Claude Code CLI (`npm install -g @anthropic-ai/claude-code`)
- TextMeBot **paid** account with API key ([textmebot.com](https://textmebot.com))
- VPS with public IP (to receive TextMeBot webhook)

## Docker Setup (recommended)

### 1. Configure

```bash
cd WhatsMCP
cp .env.example .env
# Edit .env with your settings
```

### 2. Run

```bash
docker compose up -d
```

### 3. Set webhook in TextMeBot

In the TextMeBot dashboard, set the webhook URL:

```
http://YOUR_IP:8090/webhook/incoming
```

## Local Setup (without Docker)

### 1. Install

```bash
cd WhatsMCP
pip install -e .
```

### 2. Configure

```bash
cp .env.example .env
```

### 3. Run

```bash
whatsmcp
```

## Commands

| Command | Description |
|---------|-------------|
| `/new` | Start a new session (clears context) |
| `/status` | Show current session status |
| `/help` | Show help |
| _(free text)_ | Send to Claude Code |

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TEXTMEBOT_API_KEY` | **Yes** | - | TextMeBot API key |
| `WEBHOOK_PORT` | No | `8090` | Webhook server port |
| `ANTHROPIC_API_KEY` | No* | - | Anthropic API key (*optional if Claude CLI is authenticated) |
| `APPROVED_DIRECTORY` | No | `~/projects` | Base directory for file operations |
| `CLAUDE_TIMEOUT_SECONDS` | No | `300` | Claude timeout |
| `CLAUDE_MAX_TURNS` | No | `25` | Max turns per request |
| `CLAUDE_CLI_PATH` | No | - | Path to Claude CLI binary |
| `ALLOWED_NUMBERS` | **Yes** | - | Authorized numbers (no +, comma-separated) |
| `VERBOSE_LEVEL` | No | `1` | 0=quiet, 1=cost, 2=tools |
| `DEBUG` | No | `false` | Verbose logging |

## WhatsApp vs Telegram

Unlike Telegram bots, this bot **can initiate conversations** — you don't need to message it first. It can proactively send messages to any valid WhatsApp number. Requirements:

- The recipient must have an **active WhatsApp account**
- A **paid TextMeBot subscription** is required for sending and receiving messages

## Security

- Only numbers in `ALLOWED_NUMBERS` can interact with the bot
- File operations restricted to `APPROVED_DIRECTORY`
- Sessions isolated per WhatsApp number
- API keys via environment variables (never hardcoded)
