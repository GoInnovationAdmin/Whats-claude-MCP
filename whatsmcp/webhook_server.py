"""FastAPI webhook server for receiving TextMeBot incoming messages."""

import asyncio
from typing import Optional

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .gateway_client import WhatsAppMessage

logger = structlog.get_logger()


class TextMeBotPayload(BaseModel):
    """TextMeBot webhook POST payload."""

    type: str = "text"
    from_field: str = ""
    from_name: str = ""
    to: str = ""
    file: str = "null"
    message: str = ""

    class Config:
        populate_by_name = True


# Async queue for incoming messages
message_queue: asyncio.Queue[WhatsAppMessage] = asyncio.Queue()


def create_webhook_app(textmebot_api_key: str) -> FastAPI:
    """Create the FastAPI webhook application."""
    app = FastAPI(title="WhatsMCP Webhook", docs_url=None, redoc_url=None)

    @app.post("/webhook/incoming")
    async def webhook_incoming(request: Request) -> JSONResponse:
        """Receive incoming WhatsApp messages from TextMeBot."""
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"error": "Invalid JSON"},
                status_code=400,
            )

        from_number = body.get("from", "")
        from_name = body.get("from_name", "")
        to_number = body.get("to", "")
        msg_type = body.get("type", "text")
        message_text = body.get("message", "")
        file_url = body.get("file", "null")

        if not from_number or not message_text:
            return JSONResponse(
                {"error": "Missing required fields"},
                status_code=400,
            )

        msg = WhatsAppMessage(
            type=msg_type,
            from_number=from_number.lstrip("+").strip(),
            from_name=from_name,
            to_number=to_number.lstrip("+").strip(),
            message=message_text,
            file_url=file_url if file_url != "null" else None,
        )

        await message_queue.put(msg)

        logger.info(
            "Webhook received",
            from_number=msg.from_number,
            from_name=msg.from_name,
            message_preview=msg.message[:80],
        )

        return JSONResponse({"success": True})

    @app.get("/health")
    async def health() -> JSONResponse:
        """Health check endpoint."""
        return JSONResponse({"status": "ok", "service": "whatsmcp"})

    return app
