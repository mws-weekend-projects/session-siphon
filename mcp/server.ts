import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const BASE_URL = process.env.SESSION_SIPHON_URL;
if (!BASE_URL) {
  throw new Error(
    "SESSION_SIPHON_URL environment variable is required (e.g. http://your-server:3001)"
  );
}

interface Conversation {
  id: string;
  source: string;
  machine_id: string;
  project: string;
  conversation_id: string;
  first_ts: number;
  last_ts: number;
  message_count: number;
  title: string;
  preview: string;
  git_repo?: string;
  parent_conversation_id?: string;
  relationship_type?: string;
}

interface Message {
  id: string;
  source: string;
  machine_id: string;
  project: string;
  conversation_id: string;
  ts: number;
  role: string;
  content: string;
}

interface SearchHit<T> {
  document: T;
  highlights: Array<{
    field: string;
    snippet: string;
    matchedTokens: string[];
  }>;
}

interface SearchResults<T> {
  hits: SearchHit<T>[];
  found: number;
  page: number;
  perPage: number;
  totalPages: number;
  facetCounts?: Record<string, Array<{ value: string; count: number }>>;
}

async function apiPost<T>(
  path: string,
  body: Record<string, unknown>
): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

function formatTs(ts: number): string {
  return new Date(ts * 1000).toISOString().replace("T", " ").replace(/\.\d+Z/, "Z");
}

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return s.slice(0, max) + "...";
}

// --- Server setup ---

const server = new McpServer({
  name: "session-siphon",
  version: "1.0.0",
});

// --- Tool: search_conversations ---

server.tool(
  "siphon_search_conversations",
  "Search past AI coding assistant conversations (Claude Code, Codex, Gemini, etc.) by keyword. Returns matching conversations with title, project, timestamps, and preview. Use this to find sessions where specific topics were discussed or decisions were made.",
  {
    query: z
      .string()
      .describe(
        'Search query to match against conversation titles and previews. Use "*" to match all.'
      ),
    project: z
      .string()
      .optional()
      .describe(
        "Filter by project path (e.g. '-home-nathan-projects-myapp')"
      ),
    source: z
      .string()
      .optional()
      .describe(
        "Filter by source tool: claude_code, codex, gemini, opencode"
      ),
    machine_id: z
      .string()
      .optional()
      .describe("Filter by machine hostname"),
    start_date: z
      .string()
      .optional()
      .describe("Only conversations active after this date (ISO 8601, e.g. 2026-03-01)"),
    end_date: z
      .string()
      .optional()
      .describe("Only conversations active before this date (ISO 8601, e.g. 2026-03-15)"),
    page: z.number().optional().describe("Page number (default 1)"),
    per_page: z.number().optional().describe("Results per page (default 10, max 50)"),
  },
  async ({ query, project, source, machine_id, start_date, end_date, page, per_page }) => {
    const filters: Record<string, unknown> = {};
    if (project) filters.project = project;
    if (source) filters.source = source;
    if (machine_id) filters.machineId = machine_id;
    if (start_date) filters.startTs = Math.floor(new Date(start_date).getTime() / 1000);
    if (end_date) filters.endTs = Math.floor(new Date(end_date).getTime() / 1000);

    const perPage = Math.min(per_page ?? 10, 50);

    const results = await apiPost<SearchResults<Conversation>>(
      "/api/search/conversations",
      {
        query,
        filters,
        pagination: { page: page ?? 1, perPage },
      }
    );

    const lines: string[] = [
      `Found ${results.found} conversations (page ${results.page}/${results.totalPages})`,
      "",
    ];

    for (const hit of results.hits) {
      const c = hit.document;
      const highlight =
        hit.highlights.length > 0
          ? `  Match: ${hit.highlights[0].snippet}`
          : "";
      lines.push(
        `## ${c.title}`,
        `  conversation_id: ${c.conversation_id}`,
        `  project: ${c.project}`,
        `  source: ${c.source} | machine: ${c.machine_id}`,
        `  time: ${formatTs(c.first_ts)} — ${formatTs(c.last_ts)}`,
        `  messages: ${c.message_count}${c.git_repo ? ` | repo: ${c.git_repo}` : ""}`,
        c.relationship_type
          ? `  relationship: ${c.relationship_type} (parent: ${c.parent_conversation_id})`
          : "",
        `  preview: ${truncate(c.preview, 200)}`,
        highlight,
        ""
      );
    }

    if (results.facetCounts && Object.keys(results.facetCounts).length > 0) {
      lines.push("---", "Facets:");
      for (const [field, counts] of Object.entries(results.facetCounts)) {
        const top = counts.slice(0, 10).map((c) => `${c.value} (${c.count})`);
        lines.push(`  ${field}: ${top.join(", ")}`);
      }
    }

    return {
      content: [{ type: "text", text: lines.filter(Boolean).join("\n") }],
    };
  }
);

// --- Tool: search_messages ---

server.tool(
  "siphon_search_messages",
  "Search the content of individual messages across all AI assistant conversations. Use this for finding specific code, commands, error messages, or detailed discussions. Returns matching messages with surrounding context.",
  {
    query: z
      .string()
      .describe("Search query to match against message content"),
    project: z.string().optional().describe("Filter by project path"),
    source: z.string().optional().describe("Filter by source tool"),
    machine_id: z.string().optional().describe("Filter by machine"),
    conversation_id: z
      .string()
      .optional()
      .describe("Filter to a specific conversation"),
    role: z
      .string()
      .optional()
      .describe("Filter by role: human, assistant, tool_result, system"),
    start_date: z.string().optional().describe("Messages after this date (ISO 8601)"),
    end_date: z.string().optional().describe("Messages before this date (ISO 8601)"),
    page: z.number().optional().describe("Page number (default 1)"),
    per_page: z.number().optional().describe("Results per page (default 10, max 50)"),
  },
  async ({
    query,
    project,
    source,
    machine_id,
    conversation_id,
    role,
    start_date,
    end_date,
    page,
    per_page,
  }) => {
    const filters: Record<string, unknown> = {};
    if (project) filters.project = project;
    if (source) filters.source = source;
    if (machine_id) filters.machineId = machine_id;
    if (conversation_id) filters.conversationId = conversation_id;
    if (role) filters.role = role;
    if (start_date) filters.startTs = Math.floor(new Date(start_date).getTime() / 1000);
    if (end_date) filters.endTs = Math.floor(new Date(end_date).getTime() / 1000);

    const perPage = Math.min(per_page ?? 10, 50);

    const results = await apiPost<SearchResults<Message>>(
      "/api/search/messages",
      {
        query,
        filters,
        pagination: { page: page ?? 1, perPage },
      }
    );

    const lines: string[] = [
      `Found ${results.found} messages (page ${results.page}/${results.totalPages})`,
      "",
    ];

    for (const hit of results.hits) {
      const m = hit.document;
      const snippet =
        hit.highlights.length > 0
          ? hit.highlights[0].snippet
          : truncate(m.content, 500);
      lines.push(
        `### [${m.role}] ${formatTs(m.ts)}`,
        `  conversation: ${m.conversation_id} | project: ${m.project}`,
        `  source: ${m.source} | machine: ${m.machine_id}`,
        `  ${snippet}`,
        ""
      );
    }

    return {
      content: [{ type: "text", text: lines.join("\n") }],
    };
  }
);

// --- Tool: read_conversation ---

server.tool(
  "siphon_read_conversation",
  "Read the full message history of a specific conversation. Use this after finding a conversation via search to read the complete discussion, decisions, and code changes.",
  {
    conversation_id: z
      .string()
      .describe("The conversation_id from search results"),
    max_messages: z
      .number()
      .optional()
      .describe("Maximum messages to return (default 100). Use smaller values for long conversations."),
    role: z
      .string()
      .optional()
      .describe("Only return messages from this role (human, assistant, etc.)"),
  },
  async ({ conversation_id, max_messages, role }) => {
    const limit = Math.min(max_messages ?? 100, 500);
    const allMessages: Message[] = [];
    let page = 1;
    const perPage = 50;

    while (allMessages.length < limit) {
      const filters: Record<string, unknown> = {
        conversationId: conversation_id,
      };
      if (role) filters.role = role;

      const results = await apiPost<SearchResults<Message>>(
        "/api/search/messages",
        {
          query: "*",
          filters,
          pagination: { page, perPage },
        }
      );

      for (const hit of results.hits) {
        allMessages.push(hit.document);
      }

      if (page >= results.totalPages) break;
      page++;
    }

    // Sort by timestamp ascending (API returns desc for search, but we want chronological)
    allMessages.sort((a, b) => a.ts - b.ts);

    const trimmed = allMessages.slice(0, limit);

    const lines: string[] = [
      `Conversation: ${conversation_id}`,
      `Messages: ${trimmed.length}${allMessages.length > limit ? ` (truncated from ${allMessages.length})` : ""}`,
      "",
    ];

    for (const m of trimmed) {
      const header = `--- [${m.role}] ${formatTs(m.ts)} ---`;
      lines.push(header, m.content, "");
    }

    return {
      content: [{ type: "text", text: lines.join("\n") }],
    };
  }
);

// --- Start ---

const transport = new StdioServerTransport();
await server.connect(transport);
