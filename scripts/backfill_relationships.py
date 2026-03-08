"""Backfill relationship metadata for existing Claude Code conversations.

Scans archive and inbox JSONL files, extracts fork/continuation/subagent
relationships, and updates the existing Typesense conversation documents.

Usage (inside processor container):
    python3 /scripts/backfill_relationships.py

Or from host:
    docker exec session-siphon-processor-1 python3 /app/scripts/backfill_relationships.py
"""

import json
import os
import re
import sys
from pathlib import Path

# Pattern to detect subagent files: <parent-uuid>/subagents/<agent-id>.jsonl
SUBAGENT_PATH_RE = re.compile(
    r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/subagents/"
)


def extract_relationships(path: Path) -> dict:
    """Extract session relationship metadata from a JSONL file."""
    session_id = path.stem
    parent_session_id = None
    relationship_type = None
    compaction_count = 0

    # Detect subagent from path structure
    match = SUBAGENT_PATH_RE.search(str(path))
    if match:
        return {
            "parent_session_id": match.group(1),
            "relationship_type": "subagent",
            "compaction_count": 0,
        }

    with open(path, "rb") as f:
        for line in f:
            try:
                line_text = line.decode("utf-8").strip()
            except UnicodeDecodeError:
                continue
            if not line_text:
                continue
            try:
                entry = json.loads(line_text)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type")

            # Detect fork
            if not parent_session_id and "forkedFrom" in entry:
                forked_from = entry["forkedFrom"]
                if isinstance(forked_from, dict):
                    parent_sid = forked_from.get("sessionId")
                    if parent_sid and parent_sid != session_id:
                        parent_session_id = parent_sid
                        relationship_type = "fork"

            # Detect continuation
            if entry_type == "system" and entry.get("subtype") == "compact_boundary":
                compaction_count += 1
                entry_sid = entry.get("sessionId")
                if not parent_session_id and entry_sid and entry_sid != session_id:
                    parent_session_id = entry_sid
                    relationship_type = "continuation"

    return {
        "parent_session_id": parent_session_id,
        "relationship_type": relationship_type,
        "compaction_count": compaction_count,
    }


def main():
    import typesense

    host = os.environ.get("TYPESENSE_HOST", "typesense")
    port = os.environ.get("TYPESENSE_PORT", "8108")
    api_key = os.environ.get("TYPESENSE_API_KEY", "session-siphon-prod-key-2026")

    client = typesense.Client({
        "nodes": [{"host": host, "port": port, "protocol": "http"}],
        "api_key": api_key,
        "connection_timeout_seconds": 10,
    })

    data_base = Path(os.environ.get("DATA_PATH", "/data/session-siphon"))

    # Find all Claude Code JSONL files
    search_dirs = [data_base / "archive", data_base / "inbox"]
    jsonl_files = []
    for search_dir in search_dirs:
        if search_dir.exists():
            for f in search_dir.glob("**/claude_code/**/*.jsonl"):
                jsonl_files.append(f)

    print(f"Found {len(jsonl_files)} Claude Code JSONL files to scan")

    updated = 0
    with_relationships = 0
    errors = 0

    for i, path in enumerate(jsonl_files):
        if (i + 1) % 500 == 0:
            print(f"  Progress: {i + 1}/{len(jsonl_files)} scanned, {with_relationships} relationships found")

        try:
            rel = extract_relationships(path)
        except Exception as e:
            errors += 1
            continue

        if not rel["parent_session_id"] and rel["compaction_count"] == 0:
            continue

        with_relationships += 1
        session_id = path.stem

        # Find the conversation document by conversation_id
        try:
            results = client.collections["conversations"].documents.search({
                "q": "*",
                "query_by": "title",
                "filter_by": f"conversation_id:={session_id}",
                "per_page": 1,
            })

            if results["found"] == 0:
                continue

            doc = results["hits"][0]["document"]
            doc_id = doc["id"]

            # Update with relationship data
            update = {}
            if rel["parent_session_id"]:
                update["parent_conversation_id"] = rel["parent_session_id"]
            if rel["relationship_type"]:
                update["relationship_type"] = rel["relationship_type"]
            if rel["compaction_count"] > 0:
                update["compaction_count"] = rel["compaction_count"]

            if update:
                client.collections["conversations"].documents[doc_id].update(update)
                updated += 1

        except Exception as e:
            errors += 1

    print(f"Done. Scanned: {len(jsonl_files)}, Relationships found: {with_relationships}, Updated: {updated}, Errors: {errors}")


if __name__ == "__main__":
    main()
