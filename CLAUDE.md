# Session Siphon

Centralized logging and search system for AI coding assistant conversations (Claude Code, Codex, Gemini CLI, etc.) across multiple machines.

## Architecture

Three components:

1. **Collector** (Python, runs on each dev machine) — watches `~/.claude/projects/`, `~/.codex/sessions/`, etc. for new conversation files, copies them incrementally to an outbox, and rsync syncs them to the server's inbox.
2. **Processor** (Python, runs on server in Docker) — reads files from the inbox, parses them into canonical messages, indexes into Typesense, and archives processed files.
3. **UI** (Next.js, runs on server in Docker) — web interface for browsing and searching conversations.

### Key paths

- **Source code**: `src/session_siphon/` (collector, processor, models, config)
- **Parsers**: `src/session_siphon/processor/parsers/` — one per source (claude_code, codex, gemini, opencode, etc.)
- **UI**: `ui/src/app/` — Next.js app with server components for conversation detail and client components for list/search
- **Typesense lib**: `ui/src/lib/typesense.ts` (server-side), `ui/src/lib/api.ts` (client-side)
- **Tests**: `tests/` — pytest, run with `python3 -m pytest`
- **Scripts**: `scripts/` — deployment, backfill, and schema migration utilities

### Data flow

```
Dev machine: ~/.claude/projects/**/*.jsonl
  → Collector copies to outbox
  → rsync to server inbox (/data/session-siphon/inbox/<machine_id>/claude_code/...)
  → Processor parses, indexes to Typesense, archives to /data/session-siphon/archive/
```

### Conversation relationships

Sessions can have relationships:
- **fork**: created via `claude --fork`; has `forkedFrom.sessionId` in the JSONL
- **continuation**: session that ran out of context and was continued; detected by `compact_boundary` entries with a different sessionId
- **subagent**: task delegated by a parent session; stored at `<parent-uuid>/subagents/<agent-id>.jsonl`

Relationships are stored as `parent_conversation_id` and `relationship_type` on the conversation document in Typesense.

## Deployment

### Deploy script

```bash
bash scripts/deploy.sh all      # Deploy to server + all clients
bash scripts/deploy.sh server   # Server only (rebuilds Docker containers)
bash scripts/deploy.sh clients  # All client machines only
bash scripts/deploy.sh status   # Check status everywhere
```

The deploy script auto-detects if a client machine is the local host and deploys locally (pip install + systemctl restart) instead of via SSH.

**Server** (`ubuntu@nathan-server`): rsync source → `docker compose build && docker compose up -d`
**Clients** (`nathan@office-desktop`, `nathan@p16`): rsync source → pip install → restart `siphon-collector.service`

### After deploying

If parser/indexer changes affect how data is stored, you may need to:

1. **Backfill relationships** (updates conversation metadata without reprocessing):
   ```bash
   cat scripts/backfill_relationships.py | ssh ubuntu@nathan-server \
     "docker exec -i -e TYPESENSE_HOST=typesense -e TYPESENSE_PORT=8108 \
      -e DATA_PATH=/data/session-siphon session-siphon-processor-1 python3 -"
   ```

2. **Full reindex** (nuclear option — reprocesses everything):
   ```bash
   # Delete processor state DB so it re-reads all files from offset 0
   ssh ubuntu@nathan-server "rm ~/docker/session-siphon/data/session-siphon/state/processor.db"
   # Move archived files back to inbox
   ssh ubuntu@nathan-server "cd ~/docker/session-siphon/data/session-siphon && cp -r archive/*/* inbox/"
   # Restart processor
   ssh ubuntu@nathan-server "cd ~/docker/session-siphon && docker compose restart processor"
   ```

3. **Schema changes** (add new fields to Typesense collections):
   ```bash
   cat scripts/update_schema.py | ssh ubuntu@nathan-server \
     "docker exec -i -e TYPESENSE_HOST=typesense session-siphon-processor-1 python3 -"
   ```

## Development

```bash
# Run tests
python3 -m pytest

# Run a specific test file
python3 -m pytest tests/test_processor_parsers_claude_code.py -x

# Dev UI (requires Typesense running)
cd ui && npm install && npm run dev
```

### Adding a new parser

1. Create `src/session_siphon/processor/parsers/<source>.py` implementing the `Parser` base class
2. Register it in `src/session_siphon/processor/parsers/__init__.py`
3. Add source discovery in `src/session_siphon/collector/sources.py`
4. Add tests in `tests/test_processor_parsers_<source>.py`

### Key types

- `CanonicalMessage` (`models.py`): normalized message with source, machine_id, project, conversation_id, ts, role, content
- `Conversation` (`models.py`): aggregated metadata (title from first user message, preview from last message, timestamps, message count, relationships)
- Message/Conversation IDs in Typesense: `source:machine_id:conversation_id[:timestamp:content_hash]`

## Gotchas

- Claude Code subagent files use the **parent's sessionId** internally but have a different filename (e.g., `agent-a77d39e91537bc64f`). The `conversation_id` comes from the filename stem, not the sessionId field.
- The collector glob `**/*.jsonl` matches subagent files too — this is intentional so they get indexed as separate conversations.
- `scripts/deploy.sh` is gitignored (contains machine-specific config). If it's missing, copy from another machine or recreate from the template in this file.
- The processor container doesn't have `pip` packages pre-installed for scripts. Pipe scripts via `docker exec -i ... python3 -` or install typesense first with `docker exec ... pip install typesense`.
