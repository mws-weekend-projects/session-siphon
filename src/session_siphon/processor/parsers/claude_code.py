"""Parser for Claude Code conversation transcripts.

Claude Code stores conversations as JSONL files at:
    ~/.claude/projects/<encoded-project-path>/<session-id>.jsonl

Each line is a JSON object with:
- type: "user", "assistant", or "queue-operation"
- message.role: "user" or "assistant"
- message.content: string or array of content blocks
- timestamp: ISO 8601 timestamp
- sessionId: UUID session identifier
- cwd: Working directory (project path)

Relationship detection:
- Forks: entries with forkedFrom.sessionId indicate this is a fork
- Continuations: compact_boundary with a different sessionId than filename
- Compaction: compact_boundary entries count compaction events
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from session_siphon.processor.git_utils import get_git_repo_info
from session_siphon.processor.parsers.base import CanonicalMessage, Parser


@dataclass
class SessionRelationship:
    """Metadata about how this session relates to others."""

    parent_session_id: str | None = None
    relationship_type: str | None = None  # "fork", "continuation"
    compaction_count: int = 0


class ClaudeCodeParser(Parser):
    """Parser for Claude Code JSONL transcript files."""

    source_name = "claude_code"

    def parse(
        self,
        path: Path,
        machine_id: str,
        from_offset: int = 0,
    ) -> tuple[list[CanonicalMessage], int]:
        """Parse a Claude Code JSONL file into canonical messages.

        Args:
            path: Path to the JSONL file
            machine_id: Machine identifier
            from_offset: Byte offset to start parsing from

        Returns:
            Tuple of (list of messages, new offset for next parse)
        """
        messages: list[CanonicalMessage] = []

        # Extract session_id from filename (e.g., "980dc406-0dbf-49b5-86fa-675e1e6e1998.jsonl")
        session_id = path.stem

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

                # Only process user and assistant messages
                entry_type = entry.get("type")
                if entry_type not in ("user", "assistant"):
                    continue

                message = entry.get("message", {})
                role = message.get("role")
                if not role:
                    continue

                # Extract content
                content = self._extract_content(message.get("content"))
                if not content:
                    continue

                # Parse timestamp
                timestamp_str = entry.get("timestamp")
                ts = self._parse_timestamp(timestamp_str)

                # Extract project from cwd field
                project = entry.get("cwd", "")

                # Extract git repository info
                git_repo = get_git_repo_info(project) if project else None

                messages.append(
                    CanonicalMessage(
                        source=self.source_name,
                        machine_id=machine_id,
                        project=project,
                        conversation_id=session_id,
                        ts=ts,
                        role=role,
                        content=content,
                        raw_path=str(path),
                        raw_offset=line_offset,
                        git_repo=git_repo,
                    )
                )

            # Return current file position as the new offset
            new_offset = f.tell()

        return messages, new_offset

    def extract_relationships(self, path: Path) -> SessionRelationship:
        """Extract session relationship metadata from a JSONL file.

        Scans the file for fork markers and compaction boundaries to determine
        parent/child relationships between sessions. Also detects subagent
        relationships from the file path structure.

        Args:
            path: Path to the JSONL file

        Returns:
            SessionRelationship with parent info and compaction count
        """
        session_id = path.stem
        parent_session_id: str | None = None
        relationship_type: str | None = None
        compaction_count = 0

        # Detect subagent: path contains /<parent-uuid>/subagents/<agent-id>.jsonl
        if "/subagents/" in str(path):
            import re

            match = re.search(
                r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/subagents/",
                str(path),
            )
            if match:
                return SessionRelationship(
                    parent_session_id=match.group(1),
                    relationship_type="subagent",
                    compaction_count=0,
                )

        with open(path, "rb") as f:
            for line in f:
                line_text = line.decode("utf-8").strip()
                if not line_text:
                    continue

                try:
                    entry = json.loads(line_text)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type")

                # Detect fork: entries with forkedFrom field
                if not parent_session_id and "forkedFrom" in entry:
                    forked_from = entry["forkedFrom"]
                    if isinstance(forked_from, dict):
                        parent_sid = forked_from.get("sessionId")
                        if parent_sid and parent_sid != session_id:
                            parent_session_id = parent_sid
                            relationship_type = "fork"

                # Detect continuation: compact_boundary with different sessionId
                if entry_type == "system" and entry.get("subtype") == "compact_boundary":
                    compaction_count += 1
                    entry_sid = entry.get("sessionId")
                    if (
                        not parent_session_id
                        and entry_sid
                        and entry_sid != session_id
                    ):
                        parent_session_id = entry_sid
                        relationship_type = "continuation"

        return SessionRelationship(
            parent_session_id=parent_session_id,
            relationship_type=relationship_type,
            compaction_count=compaction_count,
        )

    def _extract_content(self, content: str | list | None) -> str:
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
                    if block_type == "text":
                        text_parts.append(block.get("text", ""))
                    elif block_type == "tool_use":
                        # Include tool use as descriptive text
                        tool_name = block.get("name", "unknown")
                        text_parts.append(f"[Tool: {tool_name}]")
                    elif block_type == "tool_result":
                        # Include tool result content if present
                        result_content = block.get("content", "")
                        if result_content:
                            text_parts.append(f"[Tool Result: {result_content[:200]}...]")
                elif isinstance(block, str):
                    text_parts.append(block)
            return "\n".join(text_parts)

        return ""

    def _parse_timestamp(self, timestamp_str: str | None) -> int:
        """Parse ISO 8601 timestamp to Unix timestamp.

        Args:
            timestamp_str: ISO 8601 timestamp string (e.g., "2026-01-26T00:38:34.590Z")

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
