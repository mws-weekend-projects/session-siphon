"""Source discovery for AI coding assistant conversation files."""

import platform
from pathlib import Path

from session_siphon.logging import get_logger

logger = get_logger("sources")


def get_claude_code_paths() -> list[Path]:
    """Discover Claude Code conversation files.

    Location: ~/.claude/projects/**/*.jsonl
    """
    base_path = Path.home() / ".claude" / "projects"
    if not base_path.exists():
        return []

    return sorted(base_path.glob("**/*.jsonl"))


def get_codex_paths() -> list[Path]:
    """Discover Codex conversation files.

    Location:
    - ~/.codex/sessions/*/*/*/rollout-*.jsonl
    - ~/.codex/archived_sessions/rollout-*.jsonl
    """
    paths: list[Path] = []

    # Check sessions (nested structure)
    sessions_path = Path.home() / ".codex" / "sessions"
    if sessions_path.exists():
        paths.extend(sessions_path.glob("*/*/*/rollout-*.jsonl"))

    # Check archived sessions
    archived_path = Path.home() / ".codex" / "archived_sessions"
    if archived_path.exists():
        paths.extend(archived_path.glob("rollout-*.jsonl"))

    return sorted(paths)


def get_vscode_copilot_paths() -> list[Path]:
    """Discover VS Code Copilot conversation files.

    Locations vary by platform:
    - Linux Desktop: ~/.config/Code/User/workspaceStorage/*/chatSessions/*.json
    - Linux WSL/Remote: ~/.vscode-server/data/User/workspaceStorage/*/chatSessions/*.json
    - macOS: ~/Library/Application Support/Code/User/workspaceStorage/*/chatSessions/*.json

    Also scans Code - Insiders variant.
    """
    system = platform.system()
    paths: list[Path] = []

    if system == "Linux":
        base_paths = [
            Path.home() / ".config" / "Code" / "User" / "workspaceStorage",
            Path.home() / ".config" / "Code - Insiders" / "User" / "workspaceStorage",
            # WSL / VS Code Remote (Open Remote window)
            Path.home() / ".vscode-server" / "data" / "User" / "workspaceStorage",
            Path.home() / ".vscode-server-insiders" / "data" / "User" / "workspaceStorage",
        ]
    elif system == "Darwin":  # macOS
        base_paths = [
            Path.home() / "Library" / "Application Support" / "Code" / "User" / "workspaceStorage",
            Path.home()
            / "Library"
            / "Application Support"
            / "Code - Insiders"
            / "User"
            / "workspaceStorage",
        ]
    else:
        # Windows or other platforms not supported yet
        return []

    for base_path in base_paths:
        if base_path.exists():
            paths.extend(base_path.glob("*/chatSessions/*.json"))
            paths.extend(base_path.glob("*/workspace.json"))

    return sorted(paths)


def get_gemini_cli_paths() -> list[Path]:
    """Discover Gemini CLI conversation files.

    Location: ~/.gemini/tmp/*/chats/session-*.json
    """
    base_path = Path.home() / ".gemini" / "tmp"
    if not base_path.exists():
        return []

    return sorted(base_path.glob("*/chats/session-*.json"))


def get_opencode_paths() -> list[Path]:
    """Discover OpenCode (SST) conversation session files.

    Location: ~/.local/share/opencode/storage/session/*/ses_*.json

    OpenCode stores sessions in a hierarchical structure under its storage root:
    - storage/session/<projectHash>/ses_<sessionID>.json
    - storage/message/<sessionID>/msg_<messageID>.json (loaded by parser)
    - storage/part/<messageID>/prt_<partID>.json (loaded by parser)
    """
    base_path = Path.home() / ".local" / "share" / "opencode" / "storage" / "session"
    if not base_path.exists():
        return []

    return sorted(base_path.glob("*/ses_*.json"))


def get_antigravity_paths() -> list[Path]:
    """Discover Google Antigravity conversation files.

    NOTE: Antigravity stores main conversations as .pb (protobuf) files which
    cannot be parsed without the schema. This function collects:
    - Brain metadata JSON files (task.md.metadata.json, etc.)

    To get full conversation history, use Antigravity's /export command:
        /export  - exports current conversation to markdown
        Or use: opencode export (from CLI) for JSON export

    Google Antigravity is Google's agentic IDE using Gemini 3 models.
    """
    base_path = Path.home() / ".gemini" / "antigravity"
    if not base_path.exists():
        return []

    paths: list[Path] = []

    # Brain metadata JSON files (these are parseable)
    brain_dir = base_path / "brain"
    if brain_dir.exists():
        # Collect metadata.json files which contain task context
        paths.extend(brain_dir.glob("*/*.metadata.json"))

    # Note: conversations/*.pb files are protobuf and cannot be parsed
    # without the schema definition

    return sorted(set(paths))  # Remove duplicates


def discover_all_sources() -> dict[str, list[Path]]:
    """Discover all AI conversation source files.

    Returns a dictionary mapping source names to lists of discovered file paths.
    All functions handle missing directories gracefully by returning empty lists.
    """
    sources = {
        "claude_code": get_claude_code_paths(),
        "codex": get_codex_paths(),
        "vscode_copilot": get_vscode_copilot_paths(),
        "gemini_cli": get_gemini_cli_paths(),
        "opencode": get_opencode_paths(),
        "antigravity": get_antigravity_paths(),
    }

    total_files = sum(len(paths) for paths in sources.values())
    logger.debug(
        "Discovered sources: claude_code=%d codex=%d vscode_copilot=%d gemini_cli=%d opencode=%d antigravity=%d total=%d",
        len(sources["claude_code"]),
        len(sources["codex"]),
        len(sources["vscode_copilot"]),
        len(sources["gemini_cli"]),
        len(sources["opencode"]),
        len(sources["antigravity"]),
        total_files,
    )

    return sources
