"""Processor daemon main loop for parsing, indexing, and archiving transcripts."""

import time
from pathlib import Path

from session_siphon.config import Config
from session_siphon.logging import get_logger, setup_logging
from session_siphon.models import Conversation
from session_siphon.processor.archiver import archive_file
from session_siphon.processor.indexer import TypesenseIndexer
from session_siphon.processor.parsers import ParserRegistry
from session_siphon.processor.state import ProcessorState

logger = get_logger("processor")

# Global flag for graceful shutdown
_shutdown_requested = False

# Minimum time since last modification before archiving (seconds)
FILE_STABILITY_SECONDS = 60


def request_shutdown() -> None:
    """Request graceful shutdown of the processor daemon."""
    global _shutdown_requested
    _shutdown_requested = True


def is_shutdown_requested() -> bool:
    """Check if shutdown has been requested."""
    return _shutdown_requested


def reset_shutdown() -> None:
    """Reset shutdown flag (useful for testing)."""
    global _shutdown_requested
    _shutdown_requested = False


def detect_source_from_path(file_path: Path, inbox_path: Path) -> str | None:
    """Detect the source type from a file's path structure.

    The inbox structure is: inbox/<machine_id>/<source>/...
    So the source is the second component of the relative path.

    Args:
        file_path: Path to the file
        inbox_path: Base inbox directory path

    Returns:
        Source name if detected, None otherwise
    """
    try:
        relative = file_path.relative_to(inbox_path)
        parts = relative.parts
        # Structure: <machine_id>/<source>/...
        if len(parts) >= 2:
            return parts[1]
    except ValueError:
        pass
    return None


def extract_machine_id_from_path(file_path: Path, inbox_path: Path) -> str:
    """Extract the machine ID from a file's path structure.

    The inbox structure is: inbox/<machine_id>/<source>/...

    Args:
        file_path: Path to the file
        inbox_path: Base inbox directory path

    Returns:
        Machine ID, or 'unknown' if not extractable
    """
    try:
        relative = file_path.relative_to(inbox_path)
        parts = relative.parts
        if len(parts) >= 1:
            return parts[0]
    except ValueError:
        pass
    return "unknown"


def is_file_stable(file_path: Path, stability_seconds: int = FILE_STABILITY_SECONDS) -> bool:
    """Check if a file hasn't been modified recently.

    Used to avoid archiving files that are actively being written to.

    Args:
        file_path: Path to check
        stability_seconds: Minimum seconds since last modification

    Returns:
        True if file is stable (not recently modified)
    """
    try:
        mtime = file_path.stat().st_mtime
        age = time.time() - mtime
        return age >= stability_seconds
    except OSError:
        return False


def _update_conversation_from_messages(
    indexer: "TypesenseIndexer",
    messages: list,
) -> None:
    """Update conversation metadata based on indexed messages.

    Groups messages by conversation_id and updates each conversation
    document with aggregated metadata.

    Args:
        indexer: TypesenseIndexer instance
        messages: List of CanonicalMessage objects
    """
    from collections import defaultdict

    # Group messages by conversation
    conversations: dict[str, list] = defaultdict(list)
    for msg in messages:
        conversations[msg.conversation_id].append(msg)

    for conv_id, conv_messages in conversations.items():
        if not conv_messages:
            continue

        # Get metadata from first message (all share source/machine/project)
        first_msg = conv_messages[0]

        # Calculate conversation stats
        timestamps = [m.ts for m in conv_messages]
        first_ts = min(timestamps)
        last_ts = max(timestamps)
        message_count = len(conv_messages)

        # Generate title from first user message, or first message
        title = ""
        for msg in sorted(conv_messages, key=lambda m: m.ts):
            if msg.role == "user":
                title = msg.content[:100].strip()
                if len(msg.content) > 100:
                    title += "..."
                break
        if not title:
            title = conv_messages[0].content[:100].strip()
            if len(conv_messages[0].content) > 100:
                title += "..."

        # Preview is the last message content
        last_msg = max(conv_messages, key=lambda m: m.ts)
        preview = last_msg.content[:200].strip()
        if len(last_msg.content) > 200:
            preview += "..."

        conversation = Conversation(
            source=first_msg.source,
            machine_id=first_msg.machine_id,
            project=first_msg.project,
            conversation_id=conv_id,
            first_ts=first_ts,
            last_ts=last_ts,
            message_count=message_count,
            title=title,
            preview=preview,
        )

        try:
            indexer.update_conversation(conversation)
        except Exception:
            logger.exception("Failed to update conversation: id=%s", conv_id)


def discover_inbox_files(inbox_path: Path) -> list[Path]:
    """Discover all transcript files in the inbox.

    Searches for .jsonl and .json files in the inbox directory.

    Args:
        inbox_path: Base inbox directory path

    Returns:
        List of file paths found
    """
    if not inbox_path.exists():
        return []

    files = []
    files.extend(inbox_path.glob("**/*.jsonl"))
    files.extend(inbox_path.glob("**/*.json"))
    return sorted(files)


def process_file(
    file_path: Path,
    inbox_path: Path,
    archive_path: Path,
    state: ProcessorState,
    indexer: TypesenseIndexer | None,
    stability_seconds: int = FILE_STABILITY_SECONDS,
) -> dict[str, int]:
    """Process a single file: parse, index, and optionally archive.

    Args:
        file_path: Path to the file to process
        inbox_path: Base inbox directory path
        archive_path: Base archive directory path
        state: ProcessorState database
        indexer: TypesenseIndexer instance (or None to skip indexing)
        stability_seconds: Minimum seconds since last modification for archiving

    Returns:
        Dict with counts: {"messages": N, "indexed": M, "archived": 0 or 1}
    """
    result = {"messages": 0, "indexed": 0, "archived": 0}

    # Detect source type and machine ID
    source = detect_source_from_path(file_path, inbox_path)
    if source is None:
        logger.warning("Cannot detect source for file: path=%s", file_path)
        return result

    machine_id = extract_machine_id_from_path(file_path, inbox_path)

    # Get parser for this source
    parser = ParserRegistry.get(source)
    if parser is None:
        logger.warning("No parser for source: source=%s path=%s", source, file_path)
        return result

    # Get last processed offset
    file_key = str(file_path)
    last_offset = state.get_last_offset(file_key)
    try:
        current_size = file_path.stat().st_size
    except FileNotFoundError:
        logger.debug("File disappeared before processing: path=%s", file_path)
        return result
    except OSError:
        logger.exception("Cannot stat file: path=%s", file_path)
        return result

    # JSONL inbox files can be replaced with smaller snapshots (e.g. after rotation/sync).
    # If stored offset is beyond current EOF, restart from 0 to avoid missing new data.
    if current_size < last_offset:
        logger.info(
            "Detected file reset, rewinding offset: path=%s old_offset=%d new_size=%d",
            file_path,
            last_offset,
            current_size,
        )
        last_offset = 0

    # Parse file
    try:
        messages, new_offset = parser.parse(file_path, machine_id, from_offset=last_offset)
    except Exception:
        logger.exception("Error parsing file: source=%s path=%s", source, file_path)
        return result

    # If parser reports an offset beyond current EOF (race with truncation), clamp it.
    try:
        post_parse_size = file_path.stat().st_size
        if new_offset > post_parse_size:
            logger.warning(
                "Parser returned offset past EOF, clamping: path=%s offset=%d size=%d",
                file_path,
                new_offset,
                post_parse_size,
            )
            new_offset = post_parse_size
    except OSError:
        logger.debug("Could not stat file after parse: path=%s", file_path)

    result["messages"] = len(messages)

    # Index messages
    indexed_ok = not messages  # No messages means nothing to index — OK to advance
    if indexer is not None and messages:
        try:
            index_result = indexer.upsert_messages(messages)
            result["indexed"] = index_result.get("success", 0)
            failed = index_result.get("failed", 0)
            if failed > 0:
                logger.error(
                    "Failed to index messages: failed=%d path=%s", failed, file_path
                )
            else:
                indexed_ok = True

            # Update conversation metadata
            _update_conversation_from_messages(indexer, messages)
        except Exception:
            logger.exception("Error indexing messages: path=%s", file_path)
    elif messages and indexer is None:
        logger.warning(
            "Skipping %d messages (no indexer): path=%s", len(messages), file_path
        )

    if not indexed_ok:
        return result

    # Update state with new offset
    current_time = int(time.time())
    state.update_file_state(
        file_key,
        last_offset=new_offset,
        last_processed=current_time,
    )

    # Archive if file is stable
    if is_file_stable(file_path, stability_seconds):
        try:
            archive_file(file_path, inbox_path, archive_path)
            result["archived"] = 1
            # Remove from state since file is archived
            # (future syncs will have a new path)
        except Exception:
            logger.exception("Error archiving file: path=%s", file_path)

    return result


def run_processor_cycle(
    inbox_path: Path,
    archive_path: Path,
    state: ProcessorState,
    indexer: TypesenseIndexer | None,
    stability_seconds: int = FILE_STABILITY_SECONDS,
) -> dict[str, int]:
    """Run one processing cycle.

    Args:
        inbox_path: Base inbox directory path
        archive_path: Base archive directory path
        state: ProcessorState database
        indexer: TypesenseIndexer instance (or None to skip indexing)
        stability_seconds: Minimum seconds since last modification for archiving

    Returns:
        Dict with aggregate counts: {"files": N, "messages": M, "indexed": X, "archived": Y}
    """
    totals = {"files": 0, "messages": 0, "indexed": 0, "archived": 0}

    files = discover_inbox_files(inbox_path)

    for file_path in files:
        if is_shutdown_requested():
            break

        totals["files"] += 1
        result = process_file(
            file_path,
            inbox_path,
            archive_path,
            state,
            indexer,
            stability_seconds,
        )
        totals["messages"] += result["messages"]
        totals["indexed"] += result["indexed"]
        totals["archived"] += result["archived"]

    return totals


def run_processor(config: Config, interval_seconds: int = 30) -> None:
    """Run the processor daemon main loop.

    Discovers files in inbox, parses them, indexes messages to Typesense,
    and archives stable files. Repeats on configured interval until
    shutdown is requested.

    Args:
        config: Application configuration
        interval_seconds: Seconds between processing cycles
    """
    reset_shutdown()

    # Set up logging for processor
    setup_logging("processor")

    inbox_path = config.server.inbox_path
    archive_path = config.server.archive_path
    state_db = config.server.state_db

    logger.info(
        "Starting processor daemon: inbox=%s archive=%s state_db=%s interval=%ds",
        inbox_path,
        archive_path,
        state_db,
        interval_seconds,
    )

    # Initialize indexer with retry
    indexer: TypesenseIndexer | None = None
    for attempt in range(10):
        try:
            indexer = TypesenseIndexer(config.typesense)
            indexer.ensure_collections()
            logger.info(
                "Connected to Typesense: host=%s port=%d",
                config.typesense.host,
                config.typesense.port,
            )
            break
        except Exception:
            if attempt < 9:
                logger.warning(
                    "Could not connect to Typesense (attempt %d/10), retrying in 5s...",
                    attempt + 1,
                )
                time.sleep(5)
            else:
                logger.warning("Could not connect to Typesense after 10 attempts, indexing disabled", exc_info=True)
                indexer = None

    with ProcessorState(state_db) as state:
        while not is_shutdown_requested():
            totals = run_processor_cycle(
                inbox_path,
                archive_path,
                state,
                indexer,
            )

            if totals["files"] > 0:
                logger.info(
                    "Cycle complete: files=%d messages=%d indexed=%d archived=%d",
                    totals["files"],
                    totals["messages"],
                    totals["indexed"],
                    totals["archived"],
                )
            else:
                logger.debug("Cycle complete: no files in inbox")

            if is_shutdown_requested():
                break

            logger.debug("Waiting %ds until next cycle", interval_seconds)

            # Sleep in small increments to allow graceful shutdown
            sleep_remaining = interval_seconds
            while sleep_remaining > 0 and not is_shutdown_requested():
                sleep_time = min(1.0, sleep_remaining)
                time.sleep(sleep_time)
                sleep_remaining -= sleep_time

    logger.info("Processor daemon stopped")
