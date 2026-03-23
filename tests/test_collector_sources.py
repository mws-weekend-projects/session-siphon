"""Tests for source discovery module."""

import platform
from pathlib import Path
from unittest.mock import patch

import pytest

from session_siphon.collector.sources import (
    discover_all_sources,
    get_antigravity_paths,
    get_claude_code_paths,
    get_codex_paths,
    get_gemini_cli_paths,
    get_opencode_paths,
    get_vscode_copilot_paths,
)


class TestGetClaudeCodePaths:
    """Tests for get_claude_code_paths function."""

    def test_returns_empty_list_when_directory_missing(self, tmp_path: Path) -> None:
        """Should return empty list when .claude directory doesn't exist."""
        with patch.object(Path, "home", return_value=tmp_path):
            result = get_claude_code_paths()
            assert result == []

    def test_discovers_jsonl_files(self, tmp_path: Path) -> None:
        """Should discover .jsonl files in projects subdirectories."""
        # Create test structure
        projects_dir = tmp_path / ".claude" / "projects"
        project1 = projects_dir / "project1"
        project2 = projects_dir / "project2" / "subdir"
        project1.mkdir(parents=True)
        project2.mkdir(parents=True)

        # Create test files
        file1 = project1 / "conversation.jsonl"
        file2 = project2 / "session.jsonl"
        file3 = project1 / "other.txt"  # Should be ignored
        file1.touch()
        file2.touch()
        file3.touch()

        with patch.object(Path, "home", return_value=tmp_path):
            result = get_claude_code_paths()

        assert len(result) == 2
        assert file1 in result
        assert file2 in result
        assert file3 not in result

    def test_returns_sorted_paths(self, tmp_path: Path) -> None:
        """Should return paths in sorted order."""
        projects_dir = tmp_path / ".claude" / "projects"
        projects_dir.mkdir(parents=True)

        (projects_dir / "z_file.jsonl").touch()
        (projects_dir / "a_file.jsonl").touch()

        with patch.object(Path, "home", return_value=tmp_path):
            result = get_claude_code_paths()

        assert len(result) == 2
        assert result[0].name == "a_file.jsonl"
        assert result[1].name == "z_file.jsonl"


class TestGetCodexPaths:
    """Tests for get_codex_paths function."""

    def test_returns_empty_list_when_directory_missing(self, tmp_path: Path) -> None:
        """Should return empty list when .codex directory doesn't exist."""
        with patch.object(Path, "home", return_value=tmp_path):
            result = get_codex_paths()
            assert result == []

    def test_discovers_rollout_jsonl_files(self, tmp_path: Path) -> None:
        """Should discover rollout-*.jsonl files in the correct directory structure."""
        # Create test structure: ~/.codex/sessions/*/*/*/rollout-*.jsonl (3 wildcard levels)
        sessions_dir = tmp_path / ".codex" / "sessions"
        deep_path = sessions_dir / "2024" / "01" / "15"  # 3 levels after sessions/
        deep_path.mkdir(parents=True)

        # Create matching and non-matching files
        rollout1 = deep_path / "rollout-1.jsonl"
        rollout2 = deep_path / "rollout-2.jsonl"
        other = deep_path / "other.jsonl"  # Should be ignored (doesn't match pattern)
        rollout1.touch()
        rollout2.touch()
        other.touch()

        with patch.object(Path, "home", return_value=tmp_path):
            result = get_codex_paths()

        assert len(result) == 2
        assert rollout1 in result
        assert rollout2 in result
        assert other not in result

    def test_discovers_archived_sessions(self, tmp_path: Path) -> None:
        """Should discover rollout-*.jsonl files in archived_sessions."""
        # Create test structure: ~/.codex/archived_sessions/rollout-*.jsonl
        archived_dir = tmp_path / ".codex" / "archived_sessions"
        archived_dir.mkdir(parents=True)

        rollout_archived = archived_dir / "rollout-archived.jsonl"
        rollout_archived.touch()

        with patch.object(Path, "home", return_value=tmp_path):
            result = get_codex_paths()

        assert rollout_archived in result

    def test_wrong_depth_not_matched(self, tmp_path: Path) -> None:
        """Files at wrong directory depth should not be matched."""
        sessions_dir = tmp_path / ".codex" / "sessions"
        shallow_path = sessions_dir / "level1"
        shallow_path.mkdir(parents=True)

        (shallow_path / "rollout-1.jsonl").touch()

        with patch.object(Path, "home", return_value=tmp_path):
            result = get_codex_paths()
            assert result == []


class TestGetVscodeCopilotPaths:
    """Tests for get_vscode_copilot_paths function."""

    def test_returns_empty_list_when_directory_missing(self, tmp_path: Path) -> None:
        """Should return empty list when VS Code directory doesn't exist."""
        with patch.object(Path, "home", return_value=tmp_path):
            result = get_vscode_copilot_paths()
            assert result == []

    def test_discovers_chat_session_files_linux(self, tmp_path: Path) -> None:
        """Should discover chatSessions/*.json files on Linux."""
        # Create Linux test structure
        workspace_storage = tmp_path / ".config" / "Code" / "User" / "workspaceStorage"
        workspace1 = workspace_storage / "abc123" / "chatSessions"
        workspace2 = workspace_storage / "def456" / "chatSessions"
        workspace1.mkdir(parents=True)
        workspace2.mkdir(parents=True)

        file1 = workspace1 / "session1.json"
        file2 = workspace2 / "session2.json"
        file1.touch()
        file2.touch()

        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.object(platform, "system", return_value="Linux"),
        ):
            result = get_vscode_copilot_paths()

        assert len(result) == 2
        assert file1 in result
        assert file2 in result

    def test_discovers_insiders_files_linux(self, tmp_path: Path) -> None:
        """Should also scan Code - Insiders on Linux."""
        # Create Insiders test structure
        workspace_storage = (
            tmp_path / ".config" / "Code - Insiders" / "User" / "workspaceStorage"
        )
        workspace1 = workspace_storage / "abc123" / "chatSessions"
        workspace1.mkdir(parents=True)

        file1 = workspace1 / "session.json"
        file1.touch()

        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.object(platform, "system", return_value="Linux"),
        ):
            result = get_vscode_copilot_paths()

        assert len(result) == 1
        assert file1 in result

    def test_discovers_vscode_server_files_linux(self, tmp_path: Path) -> None:
        """Should discover chatSessions in ~/.vscode-server on Linux/WSL."""
        workspace_storage = (
            tmp_path / ".vscode-server" / "data" / "User" / "workspaceStorage"
        )
        workspace = workspace_storage / "abc123" / "chatSessions"
        workspace.mkdir(parents=True)

        file1 = workspace / "session.json"
        file1.touch()

        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.object(platform, "system", return_value="Linux"),
        ):
            result = get_vscode_copilot_paths()

        assert len(result) == 1
        assert file1 in result

    def test_discovers_vscode_server_insiders_files_linux(self, tmp_path: Path) -> None:
        """Should discover chatSessions in ~/.vscode-server-insiders on Linux/WSL."""
        workspace_storage = (
            tmp_path / ".vscode-server-insiders" / "data" / "User" / "workspaceStorage"
        )
        workspace = workspace_storage / "def456" / "chatSessions"
        workspace.mkdir(parents=True)

        file1 = workspace / "session.json"
        file1.touch()

        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.object(platform, "system", return_value="Linux"),
        ):
            result = get_vscode_copilot_paths()

        assert len(result) == 1
        assert file1 in result

    def test_discovers_chat_session_files_macos(self, tmp_path: Path) -> None:
        """Should discover chatSessions/*.json files on macOS."""
        # Create macOS test structure
        workspace_storage = (
            tmp_path / "Library" / "Application Support" / "Code" / "User" / "workspaceStorage"
        )
        workspace1 = workspace_storage / "abc123" / "chatSessions"
        workspace1.mkdir(parents=True)

        file1 = workspace1 / "session.json"
        file1.touch()

        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.object(platform, "system", return_value="Darwin"),
        ):
            result = get_vscode_copilot_paths()

        assert len(result) == 1
        assert file1 in result

    def test_returns_empty_list_on_windows(self, tmp_path: Path) -> None:
        """Should return empty list on unsupported platforms."""
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.object(platform, "system", return_value="Windows"),
        ):
            result = get_vscode_copilot_paths()
            assert result == []


class TestGetGeminiCliPaths:
    """Tests for get_gemini_cli_paths function."""

    def test_returns_empty_list_when_directory_missing(self, tmp_path: Path) -> None:
        """Should return empty list when .gemini directory doesn't exist."""
        with patch.object(Path, "home", return_value=tmp_path):
            result = get_gemini_cli_paths()
            assert result == []

    def test_discovers_session_json_files(self, tmp_path: Path) -> None:
        """Should discover session-*.json files in the correct structure."""
        # Create test structure: ~/.gemini/tmp/*/chats/session-*.json
        tmp_dir = tmp_path / ".gemini" / "tmp"
        chats1 = tmp_dir / "workspace1" / "chats"
        chats2 = tmp_dir / "workspace2" / "chats"
        chats1.mkdir(parents=True)
        chats2.mkdir(parents=True)

        session1 = chats1 / "session-001.json"
        session2 = chats2 / "session-002.json"
        other = chats1 / "other.json"  # Should be ignored
        session1.touch()
        session2.touch()
        other.touch()

        with patch.object(Path, "home", return_value=tmp_path):
            result = get_gemini_cli_paths()

        assert len(result) == 2
        assert session1 in result
        assert session2 in result
        assert other not in result


class TestGetOpencodePaths:
    """Tests for get_opencode_paths function."""

    def test_returns_empty_list_when_directory_missing(self, tmp_path: Path) -> None:
        """Should return empty list when opencode storage directory doesn't exist."""
        with patch.object(Path, "home", return_value=tmp_path):
            result = get_opencode_paths()
            assert result == []

    def test_discovers_session_json_files(self, tmp_path: Path) -> None:
        """Should discover session JSON files in the correct structure."""
        # Create test structure: ~/.local/share/opencode/storage/session/*/ses_*.json
        storage_dir = tmp_path / ".local" / "share" / "opencode" / "storage" / "session"
        project1 = storage_dir / "hash123"
        project2 = storage_dir / "hash456"
        project1.mkdir(parents=True)
        project2.mkdir(parents=True)

        file1 = project1 / "ses_001.json"
        file2 = project2 / "ses_002.json"
        other = project1 / "other.json"  # Should be ignored (doesn't match ses_* pattern)
        file1.touch()
        file2.touch()
        other.touch()

        with patch.object(Path, "home", return_value=tmp_path):
            result = get_opencode_paths()

        assert len(result) == 2
        assert file1 in result
        assert file2 in result
        assert other not in result

    def test_returns_sorted_paths(self, tmp_path: Path) -> None:
        """Should return paths in sorted order."""
        storage_dir = tmp_path / ".local" / "share" / "opencode" / "storage" / "session" / "hash123"
        storage_dir.mkdir(parents=True)

        (storage_dir / "ses_z_session.json").touch()
        (storage_dir / "ses_a_session.json").touch()

        with patch.object(Path, "home", return_value=tmp_path):
            result = get_opencode_paths()

        assert len(result) == 2
        assert result[0].name == "ses_a_session.json"
        assert result[1].name == "ses_z_session.json"


class TestGetAntigravityPaths:
    """Tests for get_antigravity_paths function.

    Note: Antigravity stores main conversations as .pb (protobuf) files which
    cannot be parsed without the schema. The collector only discovers:
    - Brain metadata JSON files (*.metadata.json)
    """

    def test_returns_empty_list_when_directory_missing(self, tmp_path: Path) -> None:
        """Should return empty list when .gemini/antigravity directory doesn't exist."""
        with patch.object(Path, "home", return_value=tmp_path):
            result = get_antigravity_paths()
            assert result == []

    def test_discovers_brain_metadata_files(self, tmp_path: Path) -> None:
        """Should discover brain metadata JSON files."""
        brain_dir = tmp_path / ".gemini" / "antigravity" / "brain"
        session1 = brain_dir / "session-abc"
        session2 = brain_dir / "session-def"
        session1.mkdir(parents=True)
        session2.mkdir(parents=True)

        # Only .metadata.json files are collected (not .pb files or regular .json)
        file1 = session1 / "task.md.metadata.json"
        file2 = session2 / "context.metadata.json"
        pb_file = session1 / "conversation.pb"  # Should be ignored
        json_file = session2 / "session.json"  # Should be ignored (not metadata)
        file1.touch()
        file2.touch()
        pb_file.touch()
        json_file.touch()

        with patch.object(Path, "home", return_value=tmp_path):
            result = get_antigravity_paths()

        assert len(result) == 2
        assert file1 in result
        assert file2 in result
        assert pb_file not in result
        assert json_file not in result

    def test_returns_sorted_unique_paths(self, tmp_path: Path) -> None:
        """Should return unique paths in sorted order."""
        brain_dir = tmp_path / ".gemini" / "antigravity" / "brain" / "session-abc"
        brain_dir.mkdir(parents=True)

        (brain_dir / "z.metadata.json").touch()
        (brain_dir / "a.metadata.json").touch()

        with patch.object(Path, "home", return_value=tmp_path):
            result = get_antigravity_paths()

        assert len(result) == 2
        assert result[0].name == "a.metadata.json"
        assert result[1].name == "z.metadata.json"


class TestDiscoverAllSources:
    """Tests for discover_all_sources function."""

    def test_returns_dict_with_all_sources(self, tmp_path: Path) -> None:
        """Should return dict with all 6 source keys."""
        with patch.object(Path, "home", return_value=tmp_path):
            result = discover_all_sources()

        assert isinstance(result, dict)
        assert "claude_code" in result
        assert "codex" in result
        assert "vscode_copilot" in result
        assert "gemini_cli" in result
        assert "opencode" in result
        assert "antigravity" in result

    def test_all_values_are_lists(self, tmp_path: Path) -> None:
        """All values should be lists (even if empty)."""
        with patch.object(Path, "home", return_value=tmp_path):
            result = discover_all_sources()

        for key, value in result.items():
            assert isinstance(value, list), f"{key} should be a list"

    def test_handles_missing_directories_gracefully(self, tmp_path: Path) -> None:
        """Should handle missing directories without errors."""
        # Empty tmp_path simulates no AI tool directories existing
        with patch.object(Path, "home", return_value=tmp_path):
            result = discover_all_sources()

        # All should be empty lists, no exceptions raised
        assert result["claude_code"] == []
        assert result["codex"] == []
        assert result["vscode_copilot"] == []
        assert result["gemini_cli"] == []
        assert result["opencode"] == []
        assert result["antigravity"] == []

    def test_discovers_from_all_sources(self, tmp_path: Path) -> None:
        """Should discover files from all sources when they exist."""
        # Create Claude Code file
        claude_dir = tmp_path / ".claude" / "projects" / "proj1"
        claude_dir.mkdir(parents=True)
        (claude_dir / "conv.jsonl").touch()

        # Create Codex file
        codex_dir = tmp_path / ".codex" / "sessions" / "a" / "b" / "c"
        codex_dir.mkdir(parents=True)
        (codex_dir / "rollout-1.jsonl").touch()

        # Create Gemini file
        gemini_dir = tmp_path / ".gemini" / "tmp" / "ws1" / "chats"
        gemini_dir.mkdir(parents=True)
        (gemini_dir / "session-1.json").touch()

        # Create OpenCode file
        opencode_dir = tmp_path / ".local" / "share" / "opencode" / "storage" / "session" / "hash123"
        opencode_dir.mkdir(parents=True)
        (opencode_dir / "ses_001.json").touch()

        # Create Antigravity file (only metadata.json files are collected)
        antigravity_dir = tmp_path / ".gemini" / "antigravity" / "brain" / "session-123"
        antigravity_dir.mkdir(parents=True)
        (antigravity_dir / "task.metadata.json").touch()

        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.object(platform, "system", return_value="Linux"),
        ):
            result = discover_all_sources()

        assert len(result["claude_code"]) == 1
        assert len(result["codex"]) == 1
        assert len(result["gemini_cli"]) == 1
        assert len(result["opencode"]) == 1
        assert len(result["antigravity"]) == 1


class TestLocalMachineDiscovery:
    """Integration tests that run on the actual local machine."""

    def test_discover_all_sources_runs_without_error(self) -> None:
        """discover_all_sources should run without error on local machine."""
        # This test verifies the functions work with real filesystem
        # No mocking - uses actual home directory
        result = discover_all_sources()

        assert isinstance(result, dict)
        assert len(result) == 6

        # All values should be lists of Path objects
        for source, paths in result.items():
            assert isinstance(paths, list), f"{source} should return a list"
            for path in paths:
                assert isinstance(path, Path), f"Items in {source} should be Path objects"
                # If a file is found, verify it exists
                assert path.exists(), f"Discovered path {path} should exist"

    def test_individual_functions_run_without_error(self) -> None:
        """Each individual discovery function should run without error."""
        # Test each function individually to ensure they handle real filesystem
        funcs = [
            get_claude_code_paths,
            get_codex_paths,
            get_vscode_copilot_paths,
            get_gemini_cli_paths,
            get_opencode_paths,
            get_antigravity_paths,
        ]

        for func in funcs:
            result = func()
            assert isinstance(result, list), f"{func.__name__} should return a list"
