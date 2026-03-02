"""Claude Code SDK integration for WhatsMCP."""

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ClaudeSDKError,
    CLIConnectionError,
    CLIJSONDecodeError,
    CLINotFoundError,
    Message,
    PermissionResultAllow,
    ProcessError,
    ResultMessage,
    ToolUseBlock,
    UserMessage,
)
from claude_agent_sdk._errors import MessageParseError
from claude_agent_sdk._internal.message_parser import parse_message

from .config import Settings

logger = structlog.get_logger()


@dataclass
class ClaudeResponse:
    """Response from Claude Code SDK."""

    content: str
    session_id: str
    cost: float
    duration_ms: int
    num_turns: int
    is_error: bool = False
    error_message: Optional[str] = None
    tools_used: List[Dict[str, Any]] = field(default_factory=list)


class ClaudeCodeIntegration:
    """Simplified Claude Code SDK integration for WhatsApp bot."""

    def __init__(self, config: Settings):
        self.config = config
        self._sessions: Dict[str, str] = {}

        if config.anthropic_api_key:
            os.environ["ANTHROPIC_API_KEY"] = config.anthropic_api_key
            logger.info("Using provided API key for Claude SDK")
        else:
            logger.info("No API key provided, using existing Claude CLI auth")

    def get_session_id(self, user_number: str) -> Optional[str]:
        """Get existing session ID for a user."""
        return self._sessions.get(user_number)

    def set_session_id(self, user_number: str, session_id: str) -> None:
        """Store session ID for a user."""
        self._sessions[user_number] = session_id

    def clear_session(self, user_number: str) -> None:
        """Clear session for a user (start fresh conversation)."""
        self._sessions.pop(user_number, None)
        logger.info("Session cleared", user=user_number)

    async def execute(
        self,
        prompt: str,
        user_number: str,
        working_directory: Optional[Path] = None,
    ) -> ClaudeResponse:
        """Execute a Claude Code command for a user."""
        start_time = asyncio.get_event_loop().time()
        work_dir = working_directory or self.config.approved_directory

        session_id = self.get_session_id(user_number)
        continue_session = session_id is not None

        logger.info(
            "Executing Claude command",
            user=user_number,
            working_directory=str(work_dir),
            session_id=session_id,
            continue_session=continue_session,
        )

        try:
            stderr_lines: List[str] = []

            def _stderr_callback(line: str) -> None:
                stderr_lines.append(line)

            system_prompt = (
                f"All file operations must stay within {work_dir}. "
                "Use relative paths."
            )
            claude_md_path = Path(work_dir) / "CLAUDE.md"
            if claude_md_path.exists():
                system_prompt += "\n\n" + claude_md_path.read_text(encoding="utf-8")

            options = ClaudeAgentOptions(
                max_turns=self.config.claude_max_turns,
                cwd=str(work_dir),
                cli_path=self.config.claude_cli_path or None,
                system_prompt=system_prompt,
                stderr=_stderr_callback,
            )

            if session_id and continue_session:
                options.resume = session_id

            messages: List[Message] = []

            async def _run_client() -> None:
                client = ClaudeSDKClient(options)
                try:
                    await client.connect()
                    await client.query(prompt)

                    async for raw_data in client._query.receive_messages():
                        try:
                            message = parse_message(raw_data)
                        except MessageParseError:
                            continue

                        messages.append(message)

                        if isinstance(message, ResultMessage):
                            break
                finally:
                    await client.disconnect()

            await asyncio.wait_for(
                _run_client(),
                timeout=self.config.claude_timeout_seconds,
            )

            # Extract results
            cost = 0.0
            tools_used: List[Dict[str, Any]] = []
            claude_session_id = None
            result_content = None

            for message in messages:
                if isinstance(message, ResultMessage):
                    cost = getattr(message, "total_cost_usd", 0.0) or 0.0
                    claude_session_id = getattr(message, "session_id", None)
                    result_content = getattr(message, "result", None)

                    for msg in messages:
                        if isinstance(msg, AssistantMessage):
                            msg_content = getattr(msg, "content", [])
                            if msg_content and isinstance(msg_content, list):
                                for block in msg_content:
                                    if isinstance(block, ToolUseBlock):
                                        tools_used.append({
                                            "name": getattr(block, "name", "unknown"),
                                        })
                    break

            # Fallback session ID
            if not claude_session_id:
                for message in messages:
                    msg_session_id = getattr(message, "session_id", None)
                    if msg_session_id:
                        claude_session_id = msg_session_id
                        break

            final_session_id = claude_session_id or session_id or ""

            # Store session for continuity
            if final_session_id:
                self.set_session_id(user_number, final_session_id)

            # Extract content
            if result_content is not None:
                content = result_content
            else:
                content_parts = []
                for msg in messages:
                    if isinstance(msg, AssistantMessage):
                        msg_content = getattr(msg, "content", [])
                        if msg_content and isinstance(msg_content, list):
                            for block in msg_content:
                                if hasattr(block, "text"):
                                    content_parts.append(block.text)
                        elif msg_content:
                            content_parts.append(str(msg_content))
                content = "\n".join(content_parts)

            duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)

            return ClaudeResponse(
                content=content,
                session_id=final_session_id,
                cost=cost,
                duration_ms=duration_ms,
                num_turns=len([
                    m for m in messages
                    if isinstance(m, (UserMessage, AssistantMessage))
                ]),
                tools_used=tools_used,
            )

        except asyncio.TimeoutError:
            logger.error("Claude timed out", timeout=self.config.claude_timeout_seconds)
            return ClaudeResponse(
                content="⏱️ Claude timed out. Try a simpler request.",
                session_id=session_id or "",
                cost=0.0,
                duration_ms=int((asyncio.get_event_loop().time() - start_time) * 1000),
                num_turns=0,
                is_error=True,
                error_message="timeout",
            )

        except CLINotFoundError:
            logger.error("Claude CLI not found")
            return ClaudeResponse(
                content="❌ Claude Code CLI not found. Install with: npm install -g @anthropic-ai/claude-code",
                session_id="",
                cost=0.0,
                duration_ms=0,
                num_turns=0,
                is_error=True,
                error_message="cli_not_found",
            )

        except (ProcessError, CLIConnectionError, CLIJSONDecodeError, ClaudeSDKError) as e:
            logger.error("Claude SDK error", error=str(e), error_type=type(e).__name__)
            return ClaudeResponse(
                content=f"❌ Claude error: {str(e)[:200]}",
                session_id=session_id or "",
                cost=0.0,
                duration_ms=int((asyncio.get_event_loop().time() - start_time) * 1000),
                num_turns=0,
                is_error=True,
                error_message=str(e),
            )

        except Exception as e:
            logger.error("Unexpected error", error=str(e), error_type=type(e).__name__)
            return ClaudeResponse(
                content=f"❌ Unexpected error: {str(e)[:200]}",
                session_id=session_id or "",
                cost=0.0,
                duration_ms=int((asyncio.get_event_loop().time() - start_time) * 1000),
                num_turns=0,
                is_error=True,
                error_message=str(e),
            )
