"""Tests for Claude Code parser."""

import json
from pathlib import Path

import pytest

from session_siphon.processor.parsers import ClaudeCodeParser, ParserRegistry
from session_siphon.processor.parsers.base import CanonicalMessage


@pytest.fixture
def parser() -> ClaudeCodeParser:
    """Create a fresh parser instance."""
    return ClaudeCodeParser()


@pytest.fixture
def sample_jsonl_file(tmp_path: Path) -> Path:
    """Create a sample Claude Code JSONL file."""
    file_path = tmp_path / "980dc406-0dbf-49b5-86fa-675e1e6e1998.jsonl"

    lines = [
        # Queue operation (should be skipped)
        {
            "type": "queue-operation",
            "operation": "dequeue",
            "timestamp": "2026-01-26T00:38:34.590Z",
            "sessionId": "980dc406-0dbf-49b5-86fa-675e1e6e1998",
        },
        # User message with string content
        {
            "type": "user",
            "cwd": "/home/user/project",
            "sessionId": "980dc406-0dbf-49b5-86fa-675e1e6e1998",
            "timestamp": "2026-01-26T00:38:34.754Z",
            "message": {
                "role": "user",
                "content": "Hello, please help me with my code.",
            },
        },
        # Assistant message with array content (text)
        {
            "type": "assistant",
            "cwd": "/home/user/project",
            "sessionId": "980dc406-0dbf-49b5-86fa-675e1e6e1998",
            "timestamp": "2026-01-26T00:38:38.771Z",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "I'll help you with your code."}],
            },
        },
        # Assistant message with tool_use content
        {
            "type": "assistant",
            "cwd": "/home/user/project",
            "sessionId": "980dc406-0dbf-49b5-86fa-675e1e6e1998",
            "timestamp": "2026-01-26T00:38:40.993Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me read the file."},
                    {
                        "type": "tool_use",
                        "id": "toolu_123",
                        "name": "Read",
                        "input": {"file_path": "/path/to/file"},
                    },
                ],
            },
        },
        # User message with tool_result content
        {
            "type": "user",
            "cwd": "/home/user/project",
            "sessionId": "980dc406-0dbf-49b5-86fa-675e1e6e1998",
            "timestamp": "2026-01-26T00:38:42.290Z",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_123",
                        "content": "File contents here...",
                    },
                ],
            },
        },
    ]

    with open(file_path, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")

    return file_path


class TestClaudeCodeParserBasics:
    """Tests for basic parser functionality."""

    def test_source_name(self, parser: ClaudeCodeParser) -> None:
        """Parser should have correct source name."""
        assert parser.source_name == "claude_code"

    def test_registered_in_registry(self) -> None:
        """Parser should be registered in ParserRegistry."""
        # Re-register since other tests may clear the registry
        ParserRegistry.register(ClaudeCodeParser())
        retrieved = ParserRegistry.get("claude_code")
        assert retrieved is not None
        assert isinstance(retrieved, ClaudeCodeParser)


class TestClaudeCodeParserParse:
    """Tests for parse method."""

    def test_parses_user_and_assistant_messages(
        self, parser: ClaudeCodeParser, sample_jsonl_file: Path
    ) -> None:
        """Should parse user and assistant messages from JSONL."""
        messages, offset = parser.parse(sample_jsonl_file, "machine-001")

        # Should have 4 messages (excludes queue-operation)
        assert len(messages) == 4

        # Check roles
        roles = [m.role for m in messages]
        assert roles == ["user", "assistant", "assistant", "user"]

    def test_extracts_session_id_from_filename(
        self, parser: ClaudeCodeParser, sample_jsonl_file: Path
    ) -> None:
        """Should extract session_id from filename as conversation_id."""
        messages, _ = parser.parse(sample_jsonl_file, "machine-001")

        for msg in messages:
            assert msg.conversation_id == "980dc406-0dbf-49b5-86fa-675e1e6e1998"

    def test_extracts_project_from_cwd(
        self, parser: ClaudeCodeParser, sample_jsonl_file: Path
    ) -> None:
        """Should extract project from cwd field."""
        messages, _ = parser.parse(sample_jsonl_file, "machine-001")

        for msg in messages:
            assert msg.project == "/home/user/project"

    def test_sets_machine_id(
        self, parser: ClaudeCodeParser, sample_jsonl_file: Path
    ) -> None:
        """Should set machine_id from argument."""
        messages, _ = parser.parse(sample_jsonl_file, "my-laptop")

        for msg in messages:
            assert msg.machine_id == "my-laptop"

    def test_parses_timestamp(
        self, parser: ClaudeCodeParser, sample_jsonl_file: Path
    ) -> None:
        """Should parse ISO 8601 timestamp to Unix timestamp."""
        messages, _ = parser.parse(sample_jsonl_file, "machine-001")

        # First user message timestamp: 2026-01-26T00:38:34.754Z
        # This should be approximately 1769392714 (give or take for timezone)
        assert messages[0].ts > 0
        assert isinstance(messages[0].ts, int)

    def test_extracts_string_content(
        self, parser: ClaudeCodeParser, sample_jsonl_file: Path
    ) -> None:
        """Should extract string content directly."""
        messages, _ = parser.parse(sample_jsonl_file, "machine-001")

        assert messages[0].content == "Hello, please help me with my code."

    def test_extracts_text_from_array_content(
        self, parser: ClaudeCodeParser, sample_jsonl_file: Path
    ) -> None:
        """Should extract text from array content blocks."""
        messages, _ = parser.parse(sample_jsonl_file, "machine-001")

        assert messages[1].content == "I'll help you with your code."

    def test_handles_tool_use_content(
        self, parser: ClaudeCodeParser, sample_jsonl_file: Path
    ) -> None:
        """Should include tool use as descriptive text."""
        messages, _ = parser.parse(sample_jsonl_file, "machine-001")

        assert "Let me read the file." in messages[2].content
        assert "[Tool: Read]" in messages[2].content

    def test_handles_tool_result_content(
        self, parser: ClaudeCodeParser, sample_jsonl_file: Path
    ) -> None:
        """Should include tool result content."""
        messages, _ = parser.parse(sample_jsonl_file, "machine-001")

        assert "[Tool Result:" in messages[3].content
        assert "File contents" in messages[3].content

    def test_sets_raw_path(
        self, parser: ClaudeCodeParser, sample_jsonl_file: Path
    ) -> None:
        """Should set raw_path to file path."""
        messages, _ = parser.parse(sample_jsonl_file, "machine-001")

        for msg in messages:
            assert msg.raw_path == str(sample_jsonl_file)

    def test_sets_raw_offset(
        self, parser: ClaudeCodeParser, sample_jsonl_file: Path
    ) -> None:
        """Should set raw_offset for each message."""
        messages, _ = parser.parse(sample_jsonl_file, "machine-001")

        # Each message should have a unique offset
        offsets = [msg.raw_offset for msg in messages]
        assert all(offset is not None for offset in offsets)
        assert len(set(offsets)) == len(offsets)  # All unique

    def test_returns_source_as_claude_code(
        self, parser: ClaudeCodeParser, sample_jsonl_file: Path
    ) -> None:
        """Should set source to 'claude_code'."""
        messages, _ = parser.parse(sample_jsonl_file, "machine-001")

        for msg in messages:
            assert msg.source == "claude_code"


class TestClaudeCodeParserIncremental:
    """Tests for incremental parsing."""

    def test_returns_new_offset(
        self, parser: ClaudeCodeParser, sample_jsonl_file: Path
    ) -> None:
        """Should return new offset at end of file."""
        _, offset = parser.parse(sample_jsonl_file, "machine-001")

        # Offset should be at end of file
        file_size = sample_jsonl_file.stat().st_size
        assert offset == file_size

    def test_parses_from_offset(
        self, parser: ClaudeCodeParser, sample_jsonl_file: Path
    ) -> None:
        """Should parse from given offset."""
        # First parse all messages
        all_messages, first_offset = parser.parse(sample_jsonl_file, "machine-001")

        # Parse again from offset - should get no new messages
        new_messages, second_offset = parser.parse(
            sample_jsonl_file, "machine-001", from_offset=first_offset
        )

        assert len(new_messages) == 0
        assert second_offset == first_offset

    def test_incremental_parse_with_new_content(
        self, parser: ClaudeCodeParser, tmp_path: Path
    ) -> None:
        """Should parse only new content when file is appended."""
        file_path = tmp_path / "test-session.jsonl"

        # Write initial content
        initial_line = {
            "type": "user",
            "cwd": "/project",
            "sessionId": "test-session",
            "timestamp": "2026-01-26T00:00:00.000Z",
            "message": {"role": "user", "content": "First message"},
        }
        with open(file_path, "w") as f:
            f.write(json.dumps(initial_line) + "\n")

        # First parse
        messages1, offset1 = parser.parse(file_path, "machine")
        assert len(messages1) == 1
        assert messages1[0].content == "First message"

        # Append new content
        new_line = {
            "type": "assistant",
            "cwd": "/project",
            "sessionId": "test-session",
            "timestamp": "2026-01-26T00:01:00.000Z",
            "message": {"role": "assistant", "content": "Second message"},
        }
        with open(file_path, "a") as f:
            f.write(json.dumps(new_line) + "\n")

        # Parse from previous offset
        messages2, offset2 = parser.parse(file_path, "machine", from_offset=offset1)
        assert len(messages2) == 1
        assert messages2[0].content == "Second message"
        assert offset2 > offset1


class TestClaudeCodeParserEdgeCases:
    """Tests for edge cases and error handling."""

    def test_handles_empty_file(self, parser: ClaudeCodeParser, tmp_path: Path) -> None:
        """Should handle empty file gracefully."""
        file_path = tmp_path / "empty.jsonl"
        file_path.touch()

        messages, offset = parser.parse(file_path, "machine")

        assert messages == []
        assert offset == 0

    def test_skips_malformed_json(
        self, parser: ClaudeCodeParser, tmp_path: Path
    ) -> None:
        """Should skip lines with invalid JSON."""
        file_path = tmp_path / "malformed.jsonl"

        with open(file_path, "w") as f:
            f.write("not valid json\n")
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "cwd": "/project",
                        "sessionId": "sess",
                        "timestamp": "2026-01-26T00:00:00Z",
                        "message": {"role": "user", "content": "Valid message"},
                    }
                )
                + "\n"
            )
            f.write("{broken json\n")

        messages, _ = parser.parse(file_path, "machine")

        # Should only get the valid message
        assert len(messages) == 1
        assert messages[0].content == "Valid message"

    def test_skips_empty_lines(self, parser: ClaudeCodeParser, tmp_path: Path) -> None:
        """Should skip empty lines."""
        file_path = tmp_path / "with-blanks.jsonl"

        with open(file_path, "w") as f:
            f.write("\n")
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "cwd": "/project",
                        "sessionId": "sess",
                        "timestamp": "2026-01-26T00:00:00Z",
                        "message": {"role": "user", "content": "Message"},
                    }
                )
                + "\n"
            )
            f.write("   \n")

        messages, _ = parser.parse(file_path, "machine")

        assert len(messages) == 1

    def test_skips_entries_without_role(
        self, parser: ClaudeCodeParser, tmp_path: Path
    ) -> None:
        """Should skip entries without message role."""
        file_path = tmp_path / "no-role.jsonl"

        with open(file_path, "w") as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "cwd": "/project",
                        "sessionId": "sess",
                        "timestamp": "2026-01-26T00:00:00Z",
                        "message": {"content": "No role here"},
                    }
                )
                + "\n"
            )

        messages, _ = parser.parse(file_path, "machine")

        assert len(messages) == 0

    def test_handles_missing_cwd(self, parser: ClaudeCodeParser, tmp_path: Path) -> None:
        """Should handle entries without cwd field."""
        file_path = tmp_path / "no-cwd.jsonl"

        with open(file_path, "w") as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": "sess",
                        "timestamp": "2026-01-26T00:00:00Z",
                        "message": {"role": "user", "content": "Message"},
                    }
                )
                + "\n"
            )

        messages, _ = parser.parse(file_path, "machine")

        assert len(messages) == 1
        assert messages[0].project == ""

    def test_handles_missing_timestamp(
        self, parser: ClaudeCodeParser, tmp_path: Path
    ) -> None:
        """Should handle entries without timestamp."""
        file_path = tmp_path / "no-timestamp.jsonl"

        with open(file_path, "w") as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "cwd": "/project",
                        "sessionId": "sess",
                        "message": {"role": "user", "content": "Message"},
                    }
                )
                + "\n"
            )

        messages, _ = parser.parse(file_path, "machine")

        assert len(messages) == 1
        assert messages[0].ts == 0

    def test_handles_empty_content(
        self, parser: ClaudeCodeParser, tmp_path: Path
    ) -> None:
        """Should skip entries with empty content."""
        file_path = tmp_path / "empty-content.jsonl"

        with open(file_path, "w") as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "cwd": "/project",
                        "sessionId": "sess",
                        "timestamp": "2026-01-26T00:00:00Z",
                        "message": {"role": "user", "content": ""},
                    }
                )
                + "\n"
            )
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "cwd": "/project",
                        "sessionId": "sess",
                        "timestamp": "2026-01-26T00:00:01Z",
                        "message": {"role": "user", "content": []},
                    }
                )
                + "\n"
            )

        messages, _ = parser.parse(file_path, "machine")

        assert len(messages) == 0

    def test_returns_canonical_message_instances(
        self, parser: ClaudeCodeParser, sample_jsonl_file: Path
    ) -> None:
        """Should return CanonicalMessage instances."""
        messages, _ = parser.parse(sample_jsonl_file, "machine-001")

        for msg in messages:
            assert isinstance(msg, CanonicalMessage)


class TestClaudeCodeParserContentExtraction:
    """Tests for content extraction edge cases."""

    def test_handles_mixed_content_blocks(
        self, parser: ClaudeCodeParser, tmp_path: Path
    ) -> None:
        """Should handle mixed content blocks."""
        file_path = tmp_path / "mixed.jsonl"

        with open(file_path, "w") as f:
            f.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "cwd": "/project",
                        "sessionId": "sess",
                        "timestamp": "2026-01-26T00:00:00Z",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": "First part."},
                                {"type": "tool_use", "name": "Bash", "id": "t1", "input": {}},
                                {"type": "text", "text": "Second part."},
                            ],
                        },
                    }
                )
                + "\n"
            )

        messages, _ = parser.parse(file_path, "machine")

        assert "First part." in messages[0].content
        assert "[Tool: Bash]" in messages[0].content
        assert "Second part." in messages[0].content

    def test_truncates_long_tool_results(
        self, parser: ClaudeCodeParser, tmp_path: Path
    ) -> None:
        """Should truncate long tool result content."""
        file_path = tmp_path / "long-result.jsonl"

        long_content = "x" * 500

        with open(file_path, "w") as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "cwd": "/project",
                        "sessionId": "sess",
                        "timestamp": "2026-01-26T00:00:00Z",
                        "message": {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "t1",
                                    "content": long_content,
                                },
                            ],
                        },
                    }
                )
                + "\n"
            )

        messages, _ = parser.parse(file_path, "machine")

        # Should be truncated (200 chars + "...")
        assert len(messages[0].content) < len(long_content)
        assert "..." in messages[0].content


class TestClaudeCodeParserSubagentRelationships:
    """Tests for subagent relationship detection."""

    def test_detects_subagent_from_path(
        self, parser: ClaudeCodeParser, tmp_path: Path
    ) -> None:
        """Should detect subagent relationship from path structure."""
        parent_uuid = "1b373cff-7ca9-41f5-bed0-eb6d831ee5f0"
        subagent_dir = tmp_path / parent_uuid / "subagents"
        subagent_dir.mkdir(parents=True)
        file_path = subagent_dir / "agent-a77d39e91537bc64f.jsonl"

        with open(file_path, "w") as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "cwd": "/project",
                        "sessionId": parent_uuid,
                        "timestamp": "2026-01-26T00:00:00Z",
                        "message": {"role": "user", "content": "Do research"},
                    }
                )
                + "\n"
            )

        rel = parser.extract_relationships(file_path)

        assert rel.parent_session_id == parent_uuid
        assert rel.relationship_type == "subagent"
        assert rel.compaction_count == 0

    def test_non_subagent_not_detected(
        self, parser: ClaudeCodeParser, tmp_path: Path
    ) -> None:
        """Should not detect subagent for regular session files."""
        file_path = tmp_path / "1b373cff-7ca9-41f5-bed0-eb6d831ee5f0.jsonl"

        with open(file_path, "w") as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "cwd": "/project",
                        "sessionId": "1b373cff-7ca9-41f5-bed0-eb6d831ee5f0",
                        "timestamp": "2026-01-26T00:00:00Z",
                        "message": {"role": "user", "content": "Hello"},
                    }
                )
                + "\n"
            )

        rel = parser.extract_relationships(file_path)

        assert rel.parent_session_id is None
        assert rel.relationship_type is None


class TestClaudeCodeParserWithRealFiles:
    """Tests using real Claude Code files (if available)."""

    @pytest.fixture
    def real_claude_code_file(self) -> Path | None:
        """Find a real Claude Code JSONL file for testing."""
        claude_dir = Path.home() / ".claude" / "projects"
        if not claude_dir.exists():
            return None

        files = list(claude_dir.glob("**/*.jsonl"))
        return files[0] if files else None

    def test_parses_real_file_if_available(
        self, parser: ClaudeCodeParser, real_claude_code_file: Path | None
    ) -> None:
        """Should successfully parse a real Claude Code file."""
        if real_claude_code_file is None:
            pytest.skip("No real Claude Code files found")

        messages, offset = parser.parse(real_claude_code_file, "test-machine")

        # Should parse without errors
        assert isinstance(messages, list)
        assert isinstance(offset, int)
        assert offset > 0

        # If there are messages, they should be valid
        if messages:
            for msg in messages:
                assert msg.source == "claude_code"
                assert msg.machine_id == "test-machine"
                assert msg.role in ("user", "assistant")
                assert msg.content  # Should have content
