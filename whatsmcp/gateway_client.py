"""TextMeBot API client for sending WhatsApp messages directly."""

import asyncio
import urllib.parse
from dataclasses import dataclass
from typing import Optional

import httpx
import structlog

logger = structlog.get_logger()

TEXTMEBOT_API_URL = "http://api.textmebot.com/send.php"


@dataclass
class WhatsAppMessage:
    """Represents an incoming WhatsApp message from TextMeBot webhook."""

    type: str
    from_number: str
    from_name: str
    to_number: str
    message: str
    file_url: Optional[str] = None


class TextMeBotClient:
    """HTTP client for sending messages directly via TextMeBot API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def send_message(self, recipient: str, message: str) -> bool:
        """Send a WhatsApp message via TextMeBot API."""
        try:
            params = {
                "recipient": recipient,
                "apikey": self.api_key,
                "text": message,
                "json": "yes",
            }
            resp = await self._client.get(TEXTMEBOT_API_URL, params=params)
            data = resp.json()
            success = data.get("status") == "success"

            if success:
                logger.info("Message sent", recipient=recipient, length=len(message))
            else:
                logger.warning(
                    "Message send failed",
                    recipient=recipient,
                    response=data,
                )

            return success

        except Exception as e:
            logger.error(
                "Failed to send message",
                recipient=recipient,
                error=str(e),
            )
            return False

    async def health_check(self) -> bool:
        """Basic connectivity check to TextMeBot API."""
        try:
            resp = await self._client.get(
                TEXTMEBOT_API_URL,
                params={"apikey": self.api_key, "json": "yes"},
                timeout=10.0,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error("TextMeBot health check failed", error=str(e))
            return False
