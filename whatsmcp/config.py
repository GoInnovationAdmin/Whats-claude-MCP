"""Configuration settings for WhatsMCP."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from dotenv import load_dotenv


@dataclass
class Settings:
    """Application settings loaded from environment variables."""

    # TextMeBot
    textmebot_api_key: str = ""

    # Webhook server
    webhook_port: int = 8090

    # Claude Code
    anthropic_api_key: str = ""
    approved_directory: Path = Path.home() / "projects"
    claude_timeout_seconds: int = 300
    claude_max_turns: int = 25
    claude_cli_path: str = ""

    # Security
    allowed_numbers: List[str] = field(default_factory=list)

    # Bot
    bot_name: str = "WhatsMCP"
    verbose_level: int = 1
    debug: bool = False

    def is_number_allowed(self, number: str) -> bool:
        """Check if a WhatsApp number is allowed to use the bot."""
        if not self.allowed_numbers:
            return False
        clean = number.lstrip("+").strip()
        return any(clean.endswith(n) or n.endswith(clean) for n in self.allowed_numbers)


def load_config() -> Settings:
    """Load configuration from .env file and environment variables."""
    load_dotenv()

    allowed_raw = os.getenv("ALLOWED_NUMBERS", "")
    allowed_numbers = [n.strip() for n in allowed_raw.split(",") if n.strip()]

    return Settings(
        textmebot_api_key=os.getenv("TEXTMEBOT_API_KEY", ""),
        webhook_port=int(os.getenv("WEBHOOK_PORT", "8090")),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        approved_directory=Path(os.getenv("APPROVED_DIRECTORY", str(Path.home() / "projects"))),
        claude_timeout_seconds=int(os.getenv("CLAUDE_TIMEOUT_SECONDS", "300")),
        claude_max_turns=int(os.getenv("CLAUDE_MAX_TURNS", "25")),
        claude_cli_path=os.getenv("CLAUDE_CLI_PATH", ""),
        allowed_numbers=allowed_numbers,
        bot_name=os.getenv("BOT_NAME", "WhatsMCP"),
        verbose_level=int(os.getenv("VERBOSE_LEVEL", "1")),
        debug=os.getenv("DEBUG", "false").lower() == "true",
    )
