"""Main entry point for WhatsMCP - WhatsApp bot powered by Claude Code."""

import asyncio
import logging
import signal
import sys
from typing import Optional

import structlog
import uvicorn

from . import __version__
from .claude_integration import ClaudeCodeIntegration
from .config import Settings, load_config
from .gateway_client import TextMeBotClient, WhatsAppMessage
from .webhook_server import create_webhook_app, message_queue

# Max WhatsApp message length (TextMeBot limit)
MAX_MESSAGE_LENGTH = 4000


def setup_logging(debug: bool = False) -> None:
    """Configure structured logging."""
    level = logging.DEBUG if debug else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(message)s",
        stream=sys.stdout,
    )

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            (
                structlog.processors.JSONRenderer()
                if not debug
                else structlog.dev.ConsoleRenderer()
            ),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def split_message(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Split a long message into chunks that fit WhatsApp limits."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break

        # Find last newline before limit
        split_pos = text.rfind("\n", 0, max_length)
        if split_pos == -1:
            split_pos = text.rfind(" ", 0, max_length)
        if split_pos == -1:
            split_pos = max_length

        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip()

    return chunks


class WhatsMCPBot:
    """WhatsApp bot that connects to Claude Code via TextMeBot + webhook."""

    def __init__(
        self,
        config: Settings,
        client: TextMeBotClient,
        claude: ClaudeCodeIntegration,
    ):
        self.config = config
        self.client = client
        self.claude = claude
        self._running = False
        self._processing: set[str] = set()
        self.logger = structlog.get_logger()

    async def start(self) -> None:
        """Start the bot message consumer loop."""
        self.logger.info(
            "Starting WhatsMCP bot",
            version=__version__,
            webhook_port=self.config.webhook_port,
            allowed_numbers=self.config.allowed_numbers,
            working_directory=str(self.config.approved_directory),
        )

        self._running = True
        self.logger.info("Bot is running. Waiting for WhatsApp messages via webhook...")

        while self._running:
            try:
                # Wait for messages from the webhook queue
                msg = await asyncio.wait_for(message_queue.get(), timeout=1.0)
                asyncio.create_task(self._handle_message(msg))
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self.logger.error("Message consumer error", error=str(e))

    async def stop(self) -> None:
        """Stop the bot."""
        self._running = False
        await self.client.close()
        self.logger.info("Bot stopped")

    async def _handle_message(self, msg: WhatsAppMessage) -> None:
        """Handle a single incoming WhatsApp message."""
        sender = msg.from_number
        text = msg.message.strip()

        self.logger.info(
            "Incoming message",
            from_number=sender,
            from_name=msg.from_name,
            message_preview=text[:80],
        )

        # Security: check if number is allowed
        if not self.config.is_number_allowed(sender):
            self.logger.warning("Unauthorized number", number=sender)
            return

        # Prevent concurrent processing for same user
        if sender in self._processing:
            self.logger.info("User already has a request in progress", user=sender)
            await self.client.send_message(
                f"+{sender}",
                "⏳ Ainda estou processando sua mensagem anterior. Aguarde...",
            )
            return

        # Handle commands
        if text.startswith("/"):
            await self._handle_command(sender, text)
            return

        # Process with Claude
        self._processing.add(sender)
        try:
            # Send "thinking" indicator
            await self.client.send_message(f"+{sender}", "🤔 Processando...")

            response = await self.claude.execute(
                prompt=text,
                user_number=sender,
            )

            # Format response
            reply = response.content
            if not reply:
                reply = "⚠️ Claude não retornou uma resposta."

            # Add cost info if verbose
            if self.config.verbose_level >= 1 and response.cost > 0:
                reply += f"\n\n💰 ${response.cost:.4f} | ⏱️ {response.duration_ms / 1000:.1f}s"

            if self.config.verbose_level >= 2 and response.tools_used:
                tools_str = ", ".join(t["name"] for t in response.tools_used)
                reply += f"\n🔧 {tools_str}"

            # Split long messages and send
            chunks = split_message(reply)
            for i, chunk in enumerate(chunks):
                await self.client.send_message(f"+{sender}", chunk)
                if i < len(chunks) - 1:
                    await asyncio.sleep(2)

        except Exception as e:
            self.logger.error("Error processing message", user=sender, error=str(e))
            await self.client.send_message(
                f"+{sender}",
                f"❌ Erro ao processar: {str(e)[:200]}",
            )
        finally:
            self._processing.discard(sender)

    async def _handle_command(self, sender: str, text: str) -> None:
        """Handle bot commands."""
        cmd = text.split()[0].lower()

        if cmd == "/new":
            self.claude.clear_session(sender)
            await self.client.send_message(
                f"+{sender}",
                "🆕 Sessão reiniciada. Nova conversa iniciada.",
            )

        elif cmd == "/status":
            session_id = self.claude.get_session_id(sender)
            status = (
                f"📊 *WhatsMCP Status*\n"
                f"Sessão ativa: {'✅ ' + session_id[:8] if session_id else '❌ Nenhuma'}\n"
                f"Diretório: {self.config.approved_directory}\n"
                f"Timeout: {self.config.claude_timeout_seconds}s"
            )
            await self.client.send_message(f"+{sender}", status)

        elif cmd == "/help":
            help_text = (
                "🤖 *WhatsMCP - Comandos*\n\n"
                "/new — Inicia nova sessão (limpa contexto)\n"
                "/status — Mostra status da sessão atual\n"
                "/help — Mostra esta ajuda\n\n"
                "Envie qualquer mensagem para interagir com o Claude Code."
            )
            await self.client.send_message(f"+{sender}", help_text)

        else:
            await self.client.send_message(
                f"+{sender}",
                f"❓ Comando desconhecido: {cmd}\nDigite /help para ver os comandos.",
            )


async def main() -> None:
    """Main application entry point."""
    config = load_config()
    setup_logging(debug=config.debug)

    logger = structlog.get_logger()
    logger.info("Starting WhatsMCP", version=__version__)

    # Validate config
    if not config.textmebot_api_key:
        logger.error("TEXTMEBOT_API_KEY is required")
        sys.exit(1)

    if not config.allowed_numbers:
        logger.error("ALLOWED_NUMBERS is required (comma-separated WhatsApp numbers)")
        sys.exit(1)

    # Create components
    client = TextMeBotClient(config.textmebot_api_key)
    claude = ClaudeCodeIntegration(config)
    bot = WhatsMCPBot(config, client, claude)

    # Create webhook FastAPI app
    webhook_app = create_webhook_app(config.textmebot_api_key)

    # Graceful shutdown
    shutdown_event = asyncio.Event()

    def signal_handler(signum: int, frame) -> None:
        logger.info("Shutdown signal received", signal=signum)
        shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start uvicorn webhook server
    uvicorn_config = uvicorn.Config(
        webhook_app,
        host="0.0.0.0",
        port=config.webhook_port,
        log_level="warning",
    )
    server = uvicorn.Server(uvicorn_config)

    # Run webhook server + bot consumer concurrently
    server_task = asyncio.create_task(server.serve())
    bot_task = asyncio.create_task(bot.start())
    shutdown_task = asyncio.create_task(shutdown_event.wait())

    logger.info(
        "WhatsMCP running",
        webhook_port=config.webhook_port,
        webhook_url=f"http://0.0.0.0:{config.webhook_port}/webhook/incoming",
    )

    done, pending = await asyncio.wait(
        [server_task, bot_task, shutdown_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    # Cleanup
    server.should_exit = True
    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    await bot.stop()
    logger.info("WhatsMCP shutdown complete")


def run() -> None:
    """Synchronous entry point."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown requested by user")
        sys.exit(0)


if __name__ == "__main__":
    run()
