"""Tests for processor daemon module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from session_siphon.config import Config, ServerConfig, TypesenseConfig
from session_siphon.processor.daemon import (
    detect_source_from_path,
    discover_inbox_files,
    extract_machine_id_from_path,
    is_file_stable,
    is_shutdown_requested,
    process_file,
    request_shutdown,
    reset_shutdown,
    run_processor,
    run_processor_cycle,
)
from session_siphon.processor.state import ProcessorState


@pytest.fixture
def tmp_state(tmp_path: Path) -> ProcessorState:
    """Create a temporary ProcessorState for testing."""
    db_path = tmp_path / "state" / "test.db"
    return ProcessorState(db_path)


@pytest.fixture
def tmp_inbox(tmp_path: Path) -> Path:
    """Create a temporary inbox directory."""
    inbox = tmp_path / "inbox"
    inbox.mkdir(parents=True)
    return inbox


@pytest.fixture
def tmp_archive(tmp_path: Path) -> Path:
    """Create a temporary archive directory."""
    archive = tmp_path / "archive"
    archive.mkdir(parents=True)
    return archive


@pytest.fixture
def test_config(tmp_path: Path) -> Config:
    """Create a test configuration."""
    return Config(
        server=ServerConfig(
            inbox_path=tmp_path / "inbox",
            archive_path=tmp_path / "archive",
            state_db=tmp_path / "state" / "processor.db",
        ),
        typesense=TypesenseConfig(
            host="localhost",
            port=8108,
            api_key="test-key",
        ),
    )


@pytest.fixture
def mock_indexer() -> MagicMock:
    """Create a mock indexer that succeeds."""
    indexer = MagicMock()
    indexer.upsert_messages.return_value = {"success": 1, "failed": 0}
    return indexer


class TestShutdownFlags:
    """Tests for shutdown flag management."""

    def test_initial_state_not_shutdown(self) -> None:
        """Should start with shutdown not requested."""
        reset_shutdown()
        assert is_shutdown_requested() is False

    def test_request_shutdown_sets_flag(self) -> None:
        """Should set shutdown flag when requested."""
        reset_shutdown()
        request_shutdown()
        assert is_shutdown_requested() is True

    def test_reset_shutdown_clears_flag(self) -> None:
        """Should clear shutdown flag when reset."""
        request_shutdown()
        reset_shutdown()
        assert is_shutdown_requested() is False


class TestDetectSourceFromPath:
    """Tests for detect_source_from_path function."""

    def test_detects_source_from_standard_path(self, tmp_inbox: Path) -> None:
        """Should extract source from inbox/<machine_id>/<source>/... path."""
        file_path = tmp_inbox / "laptop-01" / "claude_code" / "projects" / "conv.jsonl"
        file_path.parent.mkdir(parents=True)
        file_path.touch()

        source = detect_source_from_path(file_path, tmp_inbox)
        assert source == "claude_code"

    def test_returns_none_for_shallow_path(self, tmp_inbox: Path) -> None:
        """Should return None if path doesn't have enough components."""
        file_path = tmp_inbox / "conv.jsonl"
        file_path.touch()

        source = detect_source_from_path(file_path, tmp_inbox)
        assert source is None

    def test_returns_none_for_path_outside_inbox(self, tmp_inbox: Path) -> None:
        """Should return None if path is not under inbox."""
        file_path = Path("/tmp/other/file.jsonl")

        source = detect_source_from_path(file_path, tmp_inbox)
        assert source is None

    def test_handles_vscode_copilot_source(self, tmp_inbox: Path) -> None:
        """Should handle vscode_copilot source correctly."""
        file_path = tmp_inbox / "workstation" / "vscode_copilot" / "sessions" / "chat.json"
        file_path.parent.mkdir(parents=True)
        file_path.touch()

        source = detect_source_from_path(file_path, tmp_inbox)
        assert source == "vscode_copilot"


class TestExtractMachineIdFromPath:
    """Tests for extract_machine_id_from_path function."""

    def test_extracts_machine_id(self, tmp_inbox: Path) -> None:
        """Should extract machine ID from path."""
        file_path = tmp_inbox / "laptop-01" / "claude_code" / "conv.jsonl"

        machine_id = extract_machine_id_from_path(file_path, tmp_inbox)
        assert machine_id == "laptop-01"

    def test_returns_unknown_for_path_outside_inbox(self, tmp_inbox: Path) -> None:
        """Should return 'unknown' for paths outside inbox."""
        file_path = Path("/tmp/other/file.jsonl")

        machine_id = extract_machine_id_from_path(file_path, tmp_inbox)
        assert machine_id == "unknown"


class TestIsFileStable:
    """Tests for is_file_stable function."""

    def test_new_file_is_not_stable(self, tmp_path: Path) -> None:
        """Should return False for newly created files."""
        file_path = tmp_path / "recent.jsonl"
        file_path.write_bytes(b'{"test": true}\n')

        assert is_file_stable(file_path, stability_seconds=60) is False

    def test_nonexistent_file_is_not_stable(self, tmp_path: Path) -> None:
        """Should return False for nonexistent files."""
        file_path = tmp_path / "missing.jsonl"

        assert is_file_stable(file_path) is False

    def test_old_file_is_stable(self, tmp_path: Path) -> None:
        """Should return True for files with zero stability requirement."""
        file_path = tmp_path / "old.jsonl"
        file_path.write_bytes(b'{"test": true}\n')

        # With 0 second stability, any file is stable
        assert is_file_stable(file_path, stability_seconds=0) is True


class TestDiscoverInboxFiles:
    """Tests for discover_inbox_files function."""

    def test_discovers_jsonl_files(self, tmp_inbox: Path) -> None:
        """Should find all .jsonl files in inbox."""
        (tmp_inbox / "machine1" / "claude_code").mkdir(parents=True)
        (tmp_inbox / "machine1" / "claude_code" / "conv.jsonl").touch()

        files = discover_inbox_files(tmp_inbox)
        assert len(files) == 1
        assert files[0].suffix == ".jsonl"

    def test_discovers_json_files(self, tmp_inbox: Path) -> None:
        """Should find all .json files in inbox."""
        (tmp_inbox / "machine1" / "vscode_copilot").mkdir(parents=True)
        (tmp_inbox / "machine1" / "vscode_copilot" / "session.json").touch()

        files = discover_inbox_files(tmp_inbox)
        assert len(files) == 1
        assert files[0].suffix == ".json"

    def test_discovers_nested_files(self, tmp_inbox: Path) -> None:
        """Should find files in nested directories."""
        (tmp_inbox / "m1" / "claude_code" / "projects" / "p1").mkdir(parents=True)
        (tmp_inbox / "m1" / "claude_code" / "projects" / "p1" / "conv.jsonl").touch()

        files = discover_inbox_files(tmp_inbox)
        assert len(files) == 1

    def test_returns_empty_for_missing_inbox(self, tmp_path: Path) -> None:
        """Should return empty list if inbox doesn't exist."""
        inbox = tmp_path / "nonexistent"

        files = discover_inbox_files(inbox)
        assert files == []

    def test_returns_sorted_files(self, tmp_inbox: Path) -> None:
        """Should return files in sorted order."""
        (tmp_inbox / "machine1" / "claude_code").mkdir(parents=True)
        (tmp_inbox / "machine1" / "claude_code" / "b.jsonl").touch()
        (tmp_inbox / "machine1" / "claude_code" / "a.jsonl").touch()

        files = discover_inbox_files(tmp_inbox)
        assert len(files) == 2
        assert files[0].name == "a.jsonl"
        assert files[1].name == "b.jsonl"


class TestProcessFile:
    """Tests for process_file function."""

    def test_returns_zero_counts_for_unknown_source(
        self, tmp_path: Path, tmp_inbox: Path, tmp_archive: Path, tmp_state: ProcessorState
    ) -> None:
        """Should return zeros when source cannot be detected."""
        file_path = tmp_inbox / "orphan.jsonl"
        file_path.write_bytes(b'{"test": true}\n')

        result = process_file(
            file_path,
            tmp_inbox,
            tmp_archive,
            tmp_state,
            indexer=None,
        )

        assert result["messages"] == 0
        assert result["indexed"] == 0
        assert result["archived"] == 0

    def test_returns_zero_counts_for_unknown_parser(
        self, tmp_inbox: Path, tmp_archive: Path, tmp_state: ProcessorState
    ) -> None:
        """Should return zeros when no parser exists for source."""
        # Create a file with an unknown source type
        (tmp_inbox / "machine1" / "unknown_source").mkdir(parents=True)
        file_path = tmp_inbox / "machine1" / "unknown_source" / "conv.jsonl"
        file_path.write_bytes(b'{"test": true}\n')

        result = process_file(
            file_path,
            tmp_inbox,
            tmp_archive,
            tmp_state,
            indexer=None,
        )

        assert result["messages"] == 0

    def test_parses_claude_code_file(
        self, tmp_inbox: Path, tmp_archive: Path, tmp_state: ProcessorState,
        mock_indexer: MagicMock,
    ) -> None:
        """Should parse claude_code files successfully."""
        # Create a claude_code file in the proper structure
        (tmp_inbox / "machine1" / "claude_code").mkdir(parents=True)
        file_path = tmp_inbox / "machine1" / "claude_code" / "conv.jsonl"

        # Write a valid claude code message
        file_path.write_bytes(
            b'{"type":"user","message":{"role":"user","content":"hello"},"timestamp":"2024-01-01T00:00:00Z","uuid":"abc123"}\n'
        )

        result = process_file(
            file_path,
            tmp_inbox,
            tmp_archive,
            tmp_state,
            indexer=mock_indexer,
            stability_seconds=0,  # Archive immediately
        )

        assert result["messages"] >= 1
        assert result["archived"] == 1  # Should be archived since stability_seconds=0

    def test_updates_state_after_processing(
        self, tmp_inbox: Path, tmp_archive: Path, tmp_state: ProcessorState,
        mock_indexer: MagicMock,
    ) -> None:
        """Should update processor state after processing."""
        (tmp_inbox / "machine1" / "claude_code").mkdir(parents=True)
        file_path = tmp_inbox / "machine1" / "claude_code" / "conv.jsonl"
        content = (
            b'{"type":"user","message":{"role":"user","content":"test"},'
            b'"timestamp":"2024-01-01T00:00:00Z","uuid":"abc"}\n'
        )
        file_path.write_bytes(content)

        # Process without archiving
        process_file(
            file_path,
            tmp_inbox,
            tmp_archive,
            tmp_state,
            indexer=mock_indexer,
            stability_seconds=999999,  # Don't archive
        )

        # Check state was updated
        state = tmp_state.get_file_state(str(file_path))
        assert state is not None
        assert state.last_offset > 0
        assert state.last_processed is not None

    def test_does_not_archive_active_file(
        self, tmp_inbox: Path, tmp_archive: Path, tmp_state: ProcessorState,
        mock_indexer: MagicMock,
    ) -> None:
        """Should not archive files that are still active."""
        (tmp_inbox / "machine1" / "claude_code").mkdir(parents=True)
        file_path = tmp_inbox / "machine1" / "claude_code" / "conv.jsonl"
        file_path.write_bytes(
            b'{"type":"user","message":{"role":"user","content":"test"},"timestamp":"2024-01-01T00:00:00Z","uuid":"abc"}\n'
        )

        result = process_file(
            file_path,
            tmp_inbox,
            tmp_archive,
            tmp_state,
            indexer=mock_indexer,
            stability_seconds=999999,  # File won't be stable
        )

        assert result["archived"] == 0
        assert file_path.exists()  # File should still be in inbox

    def test_rewinds_offset_when_file_shrinks(
        self, tmp_inbox: Path, tmp_archive: Path, tmp_state: ProcessorState,
        mock_indexer: MagicMock,
    ) -> None:
        """Should reset parse offset when file is replaced with smaller content."""
        (tmp_inbox / "machine1" / "claude_code").mkdir(parents=True)
        file_path = tmp_inbox / "machine1" / "claude_code" / "conv.jsonl"

        first_line = (
            b'{"type":"user","message":{"role":"user","content":"'
            + (b"x" * 200)
            + b'"},"timestamp":"2024-01-01T00:00:00Z","uuid":"first"}\n'
        )
        second_line = (
            b'{"type":"user","message":{"role":"user","content":"new"},'
            b'"timestamp":"2024-01-01T00:00:01Z","uuid":"second"}\n'
        )
        assert len(second_line) < len(first_line)

        file_path.write_bytes(first_line)
        process_file(
            file_path,
            tmp_inbox,
            tmp_archive,
            tmp_state,
            indexer=mock_indexer,
            stability_seconds=999999,
        )
        first_state = tmp_state.get_file_state(str(file_path))
        assert first_state is not None
        assert first_state.last_offset == len(first_line)

        # Simulate rotation/reset: same path, smaller file with new message content.
        file_path.write_bytes(second_line)
        result = process_file(
            file_path,
            tmp_inbox,
            tmp_archive,
            tmp_state,
            indexer=mock_indexer,
            stability_seconds=999999,
        )

        assert result["messages"] >= 1
        second_state = tmp_state.get_file_state(str(file_path))
        assert second_state is not None
        assert second_state.last_offset == len(second_line)
        assert second_state.last_offset < first_state.last_offset

    def test_skips_state_update_when_no_indexer(
        self, tmp_inbox: Path, tmp_archive: Path, tmp_state: ProcessorState,
    ) -> None:
        """Should not advance state offset when indexer is unavailable."""
        (tmp_inbox / "machine1" / "claude_code").mkdir(parents=True)
        file_path = tmp_inbox / "machine1" / "claude_code" / "conv.jsonl"
        file_path.write_bytes(
            b'{"type":"user","message":{"role":"user","content":"test"},"timestamp":"2024-01-01T00:00:00Z","uuid":"abc"}\n'
        )

        result = process_file(
            file_path,
            tmp_inbox,
            tmp_archive,
            tmp_state,
            indexer=None,
            stability_seconds=0,
        )

        assert result["messages"] >= 1
        assert result["indexed"] == 0
        assert result["archived"] == 0  # Should NOT archive without indexing
        assert file_path.exists()  # File should remain in inbox
        # State should not be updated
        state = tmp_state.get_file_state(str(file_path))
        assert state is None

    def test_skips_archive_when_indexing_fails(
        self, tmp_inbox: Path, tmp_archive: Path, tmp_state: ProcessorState,
    ) -> None:
        """Should not archive or advance state when indexing raises an error."""
        (tmp_inbox / "machine1" / "claude_code").mkdir(parents=True)
        file_path = tmp_inbox / "machine1" / "claude_code" / "conv.jsonl"
        file_path.write_bytes(
            b'{"type":"user","message":{"role":"user","content":"test"},"timestamp":"2024-01-01T00:00:00Z","uuid":"abc"}\n'
        )

        failing_indexer = MagicMock()
        failing_indexer.upsert_messages.side_effect = Exception("Typesense down")

        result = process_file(
            file_path,
            tmp_inbox,
            tmp_archive,
            tmp_state,
            indexer=failing_indexer,
            stability_seconds=0,
        )

        assert result["messages"] >= 1
        assert result["indexed"] == 0
        assert result["archived"] == 0
        assert file_path.exists()
        state = tmp_state.get_file_state(str(file_path))
        assert state is None


class TestRunProcessorCycle:
    """Tests for run_processor_cycle function."""

    def test_processes_files_in_inbox(
        self, tmp_inbox: Path, tmp_archive: Path, tmp_state: ProcessorState,
        mock_indexer: MagicMock,
    ) -> None:
        """Should process all files in inbox."""
        # Create test files
        (tmp_inbox / "m1" / "claude_code").mkdir(parents=True)
        (tmp_inbox / "m1" / "claude_code" / "conv.jsonl").write_bytes(
            b'{"type":"user","message":{"role":"user","content":"test"},"timestamp":"2024-01-01T00:00:00Z","uuid":"abc"}\n'
        )

        totals = run_processor_cycle(
            tmp_inbox,
            tmp_archive,
            tmp_state,
            indexer=mock_indexer,
            stability_seconds=999999,
        )

        assert totals["files"] == 1
        assert totals["messages"] >= 1

    def test_returns_zeros_for_empty_inbox(
        self, tmp_inbox: Path, tmp_archive: Path, tmp_state: ProcessorState
    ) -> None:
        """Should return zero counts when inbox is empty."""
        totals = run_processor_cycle(
            tmp_inbox,
            tmp_archive,
            tmp_state,
            indexer=None,
        )

        assert totals["files"] == 0
        assert totals["messages"] == 0
        assert totals["indexed"] == 0
        assert totals["archived"] == 0

    def test_respects_shutdown_flag(
        self, tmp_inbox: Path, tmp_archive: Path, tmp_state: ProcessorState
    ) -> None:
        """Should stop early when shutdown is requested."""
        reset_shutdown()

        # Create multiple files
        for i in range(5):
            (tmp_inbox / f"m{i}" / "claude_code").mkdir(parents=True)
            (tmp_inbox / f"m{i}" / "claude_code" / "conv.jsonl").write_bytes(
                b'{"type":"user","message":{"role":"user","content":"test"},"timestamp":"2024-01-01T00:00:00Z","uuid":"abc"}\n'
            )

        # Request shutdown after first file
        original_process = process_file

        def mock_process(*args, **kwargs):
            request_shutdown()
            return original_process(*args, **kwargs)

        with patch(
            "session_siphon.processor.daemon.process_file",
            side_effect=mock_process,
        ):
            totals = run_processor_cycle(
                tmp_inbox,
                tmp_archive,
                tmp_state,
                indexer=None,
            )

        # Should have stopped after first file
        assert totals["files"] < 5
        reset_shutdown()


class TestRunProcessor:
    """Tests for run_processor main loop."""

    def test_runs_until_shutdown(self, test_config: Config, caplog) -> None:
        """Should run cycles until shutdown is requested."""
        reset_shutdown()
        cycle_count = 0

        def mock_cycle(*args, **kwargs):
            nonlocal cycle_count
            cycle_count += 1
            if cycle_count >= 2:
                request_shutdown()
            return {"files": 0, "messages": 0, "indexed": 0, "archived": 0}

        with patch(
            "session_siphon.processor.daemon.run_processor_cycle",
            side_effect=mock_cycle,
        ), patch(
            "session_siphon.processor.daemon.TypesenseIndexer",
        ):
            run_processor(test_config, interval_seconds=1)

        assert cycle_count >= 2

        assert "Starting processor daemon" in caplog.text
        assert "Processor daemon stopped" in caplog.text

    def test_handles_typesense_connection_failure(self, test_config: Config, caplog) -> None:
        """Should continue without indexing if Typesense connection fails."""
        reset_shutdown()

        def mock_cycle(*args, **kwargs):
            request_shutdown()
            return {"files": 0, "messages": 0, "indexed": 0, "archived": 0}

        with patch(
            "session_siphon.processor.daemon.run_processor_cycle",
            side_effect=mock_cycle,
        ), patch(
            "session_siphon.processor.daemon.TypesenseIndexer",
            side_effect=Exception("Connection refused"),
        ):
            run_processor(test_config, interval_seconds=1)

        assert "Could not connect to Typesense" in caplog.text

    def test_logs_cycle_results(self, test_config: Config, caplog) -> None:
        """Should log results after each cycle."""
        reset_shutdown()

        def mock_cycle(*args, **kwargs):
            request_shutdown()
            return {"files": 3, "messages": 10, "indexed": 10, "archived": 2}

        with patch(
            "session_siphon.processor.daemon.run_processor_cycle",
            side_effect=mock_cycle,
        ), patch(
            "session_siphon.processor.daemon.TypesenseIndexer",
        ):
            run_processor(test_config, interval_seconds=1)

        assert "files=3" in caplog.text
        assert "messages=10" in caplog.text


class TestMainModule:
    """Tests for __main__ module."""

    def test_main_loads_config_and_runs(self) -> None:
        """Should load config and run processor."""
        mock_config = MagicMock()

        with patch(
            "session_siphon.processor.__main__.load_config",
            return_value=mock_config,
        ) as mock_load, patch(
            "session_siphon.processor.__main__.run_processor"
        ) as mock_run, patch(
            "session_siphon.processor.__main__.sys.exit"
        ):
            from session_siphon.processor.__main__ import main

            main()

        mock_load.assert_called_once()
        mock_run.assert_called_once_with(mock_config)

    def test_signal_handler_requests_shutdown(self) -> None:
        """Signal handler should request shutdown."""
        import signal as sig

        from session_siphon.processor.__main__ import signal_handler

        reset_shutdown()
        signal_handler(sig.SIGINT, None)

        assert is_shutdown_requested() is True
        reset_shutdown()


class TestIntegration:
    """Integration tests for the processor daemon."""

    def test_full_process_cycle(self, tmp_path: Path, mock_indexer: MagicMock) -> None:
        """Should perform full processing cycle with real files."""
        # Setup
        inbox = tmp_path / "inbox"
        archive = tmp_path / "archive"
        state_db = tmp_path / "state" / "test.db"

        # Create inbox structure
        (inbox / "laptop-01" / "claude_code").mkdir(parents=True)
        jsonl_file = inbox / "laptop-01" / "claude_code" / "conversation.jsonl"
        jsonl_file.write_bytes(
            b'{"type":"user","message":{"role":"user","content":"Hello!"},'
            b'"timestamp":"2024-01-01T00:00:00Z","uuid":"abc123"}\n'
            b'{"type":"assistant","message":{"role":"assistant","content":"Hi!"},'
            b'"timestamp":"2024-01-01T00:00:01Z","uuid":"def456"}\n'
        )

        reset_shutdown()

        with ProcessorState(state_db) as state:
            totals = run_processor_cycle(
                inbox,
                archive,
                state,
                indexer=mock_indexer,
                stability_seconds=0,  # Archive immediately
            )

        # Verify processing
        assert totals["files"] == 1
        assert totals["messages"] >= 2  # At least user and assistant messages
        assert totals["archived"] == 1

        # Verify file was archived
        assert not jsonl_file.exists()
        archived_files = list(archive.glob("**/*.jsonl"))
        assert len(archived_files) == 1
