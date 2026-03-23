"""Parser for Codex (OpenAI) conversation transcripts.

Codex stores conversations as JSONL files at:
    ~/.codex/sessions/<year>/<month>/<day>/rollout-*.jsonl

Each line is a JSON object with a type field:
- session_meta: Session metadata (id, cwd, timestamp)
- response_item: Contains messages with role and content
- event_msg: Event notifications including user_message and agent_message
- turn_context: Turn-level context information

Key events for message extraction:
- response_item with payload.type == "message": Full message with role and content
- event_msg with payload.type in ("user_message", "agent_message"): Simplified messages
"""

import json
from datetime import datetime
from pathlib import Path

from session_siphon.processor.git_utils import get_git_repo_info
from session_siphon.processor.parsers.base import CanonicalMessage, Parser


class CodexParser(Parser):
    """Parser for Codex JSONL transcript files."""

    source_name = "codex"

    def parse(
        self,
        path: Path,
        machine_id: str,
        from_offset: int = 0,
    ) -> tuple[list[CanonicalMessage], int]:
        """Parse a Codex JSONL file into canonical messages.

        Args:
            path: Path to the JSONL file
            machine_id: Machine identifier
            from_offset: Byte offset to start parsing from

        Returns:
            Tuple of (list of messages, new offset for next parse)
        """
        messages: list[CanonicalMessage] = []

        # Extract session_id from filename
        # Format: rollout-2026-01-22T10-52-33-019be668-4c23-7792-8b9c-7995e5bfdeee.jsonl
        session_id = self._extract_session_id(path.stem)

        # Track metadata from session_meta event
        project = ""
        git_repo = None

        with open(path, "rb") as f:
            # Seek to the starting offset for incremental parsing
            f.seek(from_offset)

            for line in f:
                line_offset = f.tell() - len(line)  # Offset of this line
                line_text = line.decode("utf-8").strip()

                if not line_text:
                    continue

                try:
                    entry = json.loads(line_text)
                except json.JSONDecodeError:
                    # Skip malformed lines
                    continue

                event_type = entry.get("type")
                timestamp_str = entry.get("timestamp")
                ts = self._parse_timestamp(timestamp_str)

                # Extract project from session_meta
                if event_type == "session_meta":
                    payload = entry.get("payload", {})
                    project = payload.get("cwd", "")
                    git_repo = get_git_repo_info(project) if project else None
                    # Use session id from payload if available
                    if payload.get("id"):
                        session_id = payload["id"]
                    continue

                # Extract messages from response_item events
                if event_type == "response_item":
                    payload = entry.get("payload", {})
                    if payload.get("type") == "message":
                        msg = self._extract_response_item_message(
                            payload=payload,
                            ts=ts,
                            machine_id=machine_id,
                            project=project,
                            session_id=session_id,
                            path=path,
                            line_offset=line_offset,
                            git_repo=git_repo,
                        )
                        if msg:
                            messages.append(msg)

                # Extract messages from event_msg events
                elif event_type == "event_msg":
                    payload = entry.get("payload", {})
                    msg_type = payload.get("type")

                    if msg_type == "user_message":
                        content = payload.get("message", "")
                        if content:
                            messages.append(
                                CanonicalMessage(
                                    source=self.source_name,
                                    machine_id=machine_id,
                                    project=project,
                                    conversation_id=session_id,
                                    ts=ts,
                                    role="user",
                                    content=content,
                                    raw_path=str(path),
                                    raw_offset=line_offset,
                                    git_repo=git_repo,
                                )
                            )
                    elif msg_type == "agent_message":
                        content = payload.get("message", "")
                        if content:
                            messages.append(
                                CanonicalMessage(
                                    source=self.source_name,
                                    machine_id=machine_id,
                                    project=project,
                                    conversation_id=session_id,
                                    ts=ts,
                                    role="assistant",
                                    content=content,
                                    raw_path=str(path),
                                    raw_offset=line_offset,
                                    git_repo=git_repo,
                                )
                            )

            # Return current file position as the new offset
            new_offset = f.tell()

        return messages, new_offset

    def _extract_session_id(self, filename: str) -> str:
        """Extract session ID from filename.

        Args:
            filename: The filename stem (without .jsonl extension)
                     Format: rollout-2026-01-22T10-52-33-019be668-4c23-7792-8b9c-7995e5bfdeee

        Returns:
            Session ID extracted from the filename
        """
        # Try to extract UUID portion after the timestamp
        # rollout-YYYY-MM-DDTHH-MM-SS-<uuid>
        if filename.startswith("rollout-"):
            # Remove "rollout-" prefix
            rest = filename[8:]
            # Find the UUID part (after the timestamp portion)
            # Format: YYYY-MM-DDTHH-MM-SS followed by UUID
            parts = rest.split("-")
            if len(parts) >= 7:
                # Skip YYYY, MM, DDTHH, MM, SS and take the rest as UUID
                uuid_parts = parts[5:]
                return "-".join(uuid_parts)
        return filename

    def _extract_response_item_message(
        self,
        payload: dict,
        ts: int,
        machine_id: str,
        project: str,
        session_id: str,
        path: Path,
        line_offset: int,
        git_repo: str | None,
    ) -> CanonicalMessage | None:
        """Extract a message from a response_item payload.

        Args:
            payload: The response_item payload
            ts: Unix timestamp
            machine_id: Machine identifier
            project: Project/cwd path
            session_id: Session identifier
            path: Path to the source file
            line_offset: Byte offset in the file
            git_repo: Git repository identifier

        Returns:
            CanonicalMessage or None if no valid content
        """
        role = payload.get("role")
        if not role:
            return None

        # Map Codex roles to canonical roles
        canonical_role = self._map_role(role)
        if not canonical_role:
            return None

        content = self._extract_content(payload.get("content"))
        if not content:
            return None

        return CanonicalMessage(
            source=self.source_name,
            machine_id=machine_id,
            project=project,
            conversation_id=session_id,
            ts=ts,
            role=canonical_role,
            content=content,
            git_repo=git_repo,
            raw_path=str(path),
            raw_offset=line_offset,
        )

    def _map_role(self, role: str) -> str | None:
        """Map Codex role to canonical role.

        Args:
            role: Codex role (user, assistant, developer, system)

        Returns:
            Canonical role or None if role should be skipped
        """
        role_mapping = {
            "user": "user",
            "assistant": "assistant",
            "developer": "system",
            "system": "system",
        }
        return role_mapping.get(role)

    def _extract_content(self, content: list | str | None) -> str:
        """Extract text content from message content field.

        Args:
            content: Either a string or array of content blocks

        Returns:
            Extracted text content as a string
        """
        if content is None:
            return ""

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            text_parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get("type")
                    if block_type == "input_text":
                        text_parts.append(block.get("text", ""))
                    elif block_type == "output_text":
                        text_parts.append(block.get("text", ""))
                    elif block_type == "text":
                        text_parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    text_parts.append(block)
            return "\n".join(text_parts)

        return ""

    def _parse_timestamp(self, timestamp_str: str | None) -> int:
        """Parse ISO 8601 timestamp to Unix timestamp.

        Args:
            timestamp_str: ISO 8601 timestamp string (e.g., "2026-01-22T15:52:33.575Z")

        Returns:
            Unix timestamp in seconds
        """
        if not timestamp_str:
            return 0

        try:
            # Handle ISO 8601 with optional microseconds and Z suffix
            if timestamp_str.endswith("Z"):
                timestamp_str = timestamp_str[:-1] + "+00:00"
            dt = datetime.fromisoformat(timestamp_str)
            return int(dt.timestamp())
        except (ValueError, AttributeError):
            return 0
