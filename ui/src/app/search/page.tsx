"use client";

import { useState, useCallback, useEffect, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  searchMessages,
  fetchConversationsByIds,
  type Message,
  type Conversation,
  type SearchHit,
  type MessageFilters,
} from "@/lib/api";

interface SearchState {
  query: string;
  messageHits: SearchHit<Message>[];
  total: number;
  page: number;
  totalPages: number;
  loading: boolean;
  error: string | null;
}

interface Filters {
  source: string;
  project: string;
  role: string;
  machineId: string;
}

/** A conversation with its matched message hits. */
interface ConversationGroup {
  conversation: Conversation | null;
  compositeId: string;
  conversationId: string;
  hits: SearchHit<Message>[];
}

type ConversationGroupHit = {
  document: Conversation;
  group: ConversationGroup;
};

const SOURCES = ["", "claude_code", "codex", "vscode_copilot", "gemini_cli"];
const ROLES = ["", "user", "assistant", "tool", "system"];

function formatTimestamp(ts: number): string {
  return new Date(ts * 1000).toLocaleString();
}

function formatRelativeTime(ts: number): string {
  const date = new Date(ts * 1000);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays === 0) {
    return date.toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
    });
  } else if (diffDays === 1) {
    return "Yesterday";
  } else if (diffDays < 7) {
    return date.toLocaleDateString(undefined, { weekday: "long" });
  } else {
    return date.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: date.getFullYear() !== now.getFullYear() ? "numeric" : undefined,
    });
  }
}

function formatSourceName(source: string): string {
  const sourceNames: Record<string, string> = {
    claude_code: "Claude Code",
    codex: "Codex",
    vscode_copilot: "VS Code Copilot",
    gemini_cli: "Gemini CLI",
  };
  return sourceNames[source] || source;
}

function getSourceColor(source: string): string {
  const colors: Record<string, string> = {
    claude_code:
      "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300",
    codex: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
    vscode_copilot:
      "bg-sky-100 text-sky-800 dark:bg-sky-900/30 dark:text-sky-300",
    gemini_cli:
      "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/30 dark:text-indigo-300",
  };
  return (
    colors[source] ||
    "bg-zinc-100 text-zinc-800 dark:bg-zinc-800 dark:text-zinc-300"
  );
}

function HighlightedSnippet({ snippet }: { snippet: string }) {
  return (
    <span
      className="text-sm text-zinc-600 dark:text-zinc-400"
      dangerouslySetInnerHTML={{ __html: snippet }}
    />
  );
}

function truncateContent(content: string, maxLength: number = 200): string {
  if (content.length <= maxLength) return content;
  return content.slice(0, maxLength) + "...";
}

function RelationshipIndicator({ type }: { type?: string }) {
  if (!type) return null;
  if (type === "fork") {
    return (
      <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300">
        Fork
      </span>
    );
  }
  if (type === "continuation") {
    return (
      <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">
        Continuation
      </span>
    );
  }
  if (type === "subagent") {
    return (
      <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300">
        Subagent
      </span>
    );
  }
  return null;
}

/** Group message hits by conversation_id. */
function groupByConversation(
  hits: SearchHit<Message>[]
): Map<string, SearchHit<Message>[]> {
  const groups = new Map<string, SearchHit<Message>[]>();
  for (const hit of hits) {
    const key = hit.document.conversation_id;
    const existing = groups.get(key);
    if (existing) {
      existing.push(hit);
    } else {
      groups.set(key, [hit]);
    }
  }
  return groups;
}

/** Nest subagent conversation groups under their parent. */
function nestSubagentGroups(groups: ConversationGroupHit[]): {
  topLevel: ConversationGroupHit[];
  childrenByParent: Record<string, ConversationGroupHit[]>;
  missingParentIds: string[];
} {
  const subagents: ConversationGroupHit[] = [];
  const topLevel: ConversationGroupHit[] = [];
  const childrenByParent: Record<string, ConversationGroupHit[]> = {};

  for (const g of groups) {
    if (
      g.document.relationship_type === "subagent" &&
      g.document.parent_conversation_id
    ) {
      subagents.push(g);
    } else {
      topLevel.push(g);
    }
  }

  const topLevelIds = new Set(topLevel.map((g) => g.document.conversation_id));
  const missingParentIdSet = new Set<string>();

  for (const sub of subagents) {
    const parentId = sub.document.parent_conversation_id!;
    if (!childrenByParent[parentId]) childrenByParent[parentId] = [];
    childrenByParent[parentId].push(sub);
    if (!topLevelIds.has(parentId)) {
      missingParentIdSet.add(parentId);
    }
  }

  for (const children of Object.values(childrenByParent)) {
    children.sort(
      (a, b) => a.document.first_ts - b.document.first_ts
    );
  }

  return {
    topLevel,
    childrenByParent,
    missingParentIds: [...missingParentIdSet],
  };
}

function MatchedMessageSnippet({ hit }: { hit: SearchHit<Message> }) {
  return (
    <div className="flex gap-3 py-2 px-3 rounded-md bg-zinc-50 dark:bg-zinc-800/50">
      <span className="shrink-0 rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 dark:bg-blue-900/50 dark:text-blue-300 h-fit">
        {hit.document.role}
      </span>
      <div className="min-w-0 flex-1">
        {hit.highlights.length > 0 && hit.highlights[0].snippet ? (
          <HighlightedSnippet snippet={hit.highlights[0].snippet} />
        ) : (
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            {truncateContent(hit.document.content)}
          </p>
        )}
        <div className="mt-1 text-[10px] text-zinc-400 dark:text-zinc-500">
          {formatTimestamp(hit.document.ts)}
        </div>
      </div>
    </div>
  );
}

function ConversationGroupCard({
  group,
  indented = false,
}: {
  group: ConversationGroup;
  indented?: boolean;
}) {
  const conv = group.conversation;
  const firstHit = group.hits[0];
  const title = conv?.title || "Untitled Conversation";
  const source = conv?.source || firstHit.document.source;
  const machineId = conv?.machine_id || firstHit.document.machine_id;
  const lastTs = conv?.last_ts || firstHit.document.ts;
  const messageCount = conv?.message_count;

  return (
    <div
      className={`border-b border-zinc-200 dark:border-zinc-800 ${indented ? "pl-6" : ""}`}
    >
      <div className="p-4">
        <div className="flex justify-between items-start gap-4 mb-2">
          <div className="flex items-center gap-2 min-w-0">
            {conv?.relationship_type && (
              <RelationshipIndicator type={conv.relationship_type} />
            )}
            <Link
              href={`/conversation/${encodeURIComponent(group.compositeId)}`}
              className="text-base font-semibold text-zinc-900 dark:text-zinc-100 hover:text-blue-600 dark:hover:text-blue-400 transition-colors line-clamp-1"
            >
              {title}
            </Link>
          </div>
          <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400 whitespace-nowrap">
            {formatRelativeTime(lastTs)}
          </span>
        </div>

        <div className="flex items-center gap-3 text-xs mb-3">
          <span
            className={`px-2 py-0.5 rounded-full font-medium ${getSourceColor(source)}`}
          >
            {formatSourceName(source)}
          </span>
          <span className="text-zinc-500 dark:text-zinc-400 font-mono">
            {machineId}
          </span>
          {messageCount && (
            <>
              <span className="text-zinc-400 dark:text-zinc-500">•</span>
              <span className="text-zinc-500 dark:text-zinc-400 font-medium">
                {messageCount} messages
              </span>
            </>
          )}
          <span className="text-zinc-400 dark:text-zinc-500">•</span>
          <span className="text-zinc-500 dark:text-zinc-400 font-medium">
            {group.hits.length} match{group.hits.length !== 1 ? "es" : ""}
          </span>
          <Link
            href={`/conversation/${encodeURIComponent(group.compositeId)}`}
            className="ml-auto font-medium text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300"
          >
            View Conversation &rarr;
          </Link>
        </div>

        <div className="space-y-1.5">
          {group.hits.map((hit) => (
            <MatchedMessageSnippet key={hit.document.id} hit={hit} />
          ))}
        </div>
      </div>
    </div>
  );
}

function ConversationGroupWithChildren({
  groupHit,
  childrenByParent,
}: {
  groupHit: ConversationGroupHit;
  childrenByParent: Record<string, ConversationGroupHit[]>;
}) {
  const children = childrenByParent[groupHit.document.conversation_id];
  const [showChildren, setShowChildren] = useState(false);

  return (
    <div>
      <ConversationGroupCard group={groupHit.group} />
      {children && children.length > 0 && (
        <div className="pl-6 border-l-2 border-green-100 dark:border-green-900/30 ml-4">
          <button
            onClick={() => setShowChildren(!showChildren)}
            className="w-full text-left px-4 py-1.5 text-xs text-green-700 dark:text-green-400 hover:bg-green-50 dark:hover:bg-green-900/10 transition-colors"
          >
            {showChildren ? "Hide" : "Show"} {children.length} subagent
            {children.length !== 1 ? "s" : ""} with matches
          </button>
          {showChildren &&
            children.map((child) => (
              <ConversationGroupCard
                key={child.group.conversationId}
                group={child.group}
                indented
              />
            ))}
        </div>
      )}
    </div>
  );
}

function SearchPageContent() {
  const searchParams = useSearchParams();
  const initialQuery = searchParams.get("q") || "";

  const [searchState, setSearchState] = useState<SearchState>({
    query: initialQuery,
    messageHits: [],
    total: 0,
    page: 1,
    totalPages: 0,
    loading: false,
    error: null,
  });

  const [filters, setFilters] = useState<Filters>({
    source: "",
    project: "",
    role: "",
    machineId: "",
  });

  const [inputValue, setInputValue] = useState(initialQuery);
  const [conversations, setConversations] = useState<
    Record<string, Conversation>
  >({});
  const [resolvedParents, setResolvedParents] = useState<
    Record<string, Conversation>
  >({});

  const executeSearch = useCallback(
    async (query: string, page: number = 1) => {
      if (!query.trim()) {
        setSearchState((prev) => ({
          ...prev,
          messageHits: [],
          total: 0,
          page: 1,
          totalPages: 0,
          error: null,
        }));
        setConversations({});
        setResolvedParents({});
        return;
      }

      setSearchState((prev) => ({ ...prev, loading: true, error: null }));

      try {
        const messageFilters: MessageFilters = {};
        if (filters.source) messageFilters.source = filters.source;
        if (filters.project) messageFilters.project = filters.project;
        if (filters.role) messageFilters.role = filters.role;
        if (filters.machineId) messageFilters.machineId = filters.machineId;

        const results = await searchMessages(query, messageFilters, {
          page,
          perPage: 40,
        });

        setSearchState({
          query,
          messageHits: results.hits,
          total: results.found,
          page: results.page,
          totalPages: results.totalPages,
          loading: false,
          error: null,
        });

        // Fetch conversation metadata for all unique conversation_ids
        const uniqueIds = [
          ...new Set(results.hits.map((h) => h.document.conversation_id)),
        ];
        if (uniqueIds.length > 0) {
          try {
            const convData = await fetchConversationsByIds(uniqueIds);
            const convMap: Record<string, Conversation> = {};
            for (const hit of convData.hits) {
              convMap[hit.document.conversation_id] = hit.document;
            }
            setConversations(convMap);
            setResolvedParents({});
          } catch {
            // Non-critical - results still display without conversation metadata
          }
        }
      } catch (err) {
        setSearchState((prev) => ({
          ...prev,
          loading: false,
          error: err instanceof Error ? err.message : "Search failed",
        }));
      }
    },
    [filters]
  );

  // Fetch missing parents for subagent nesting
  useEffect(() => {
    if (Object.keys(conversations).length === 0) return;

    const missingParentIds: string[] = [];
    for (const conv of Object.values(conversations)) {
      if (
        conv.relationship_type === "subagent" &&
        conv.parent_conversation_id &&
        !conversations[conv.parent_conversation_id] &&
        !resolvedParents[conv.parent_conversation_id]
      ) {
        missingParentIds.push(conv.parent_conversation_id);
      }
    }

    if (missingParentIds.length === 0) return;

    fetchConversationsByIds([...new Set(missingParentIds)])
      .then((data) => {
        const newParents: Record<string, Conversation> = {};
        for (const hit of data.hits) {
          newParents[hit.document.conversation_id] = hit.document;
        }
        setResolvedParents((prev) => ({ ...prev, ...newParents }));
      })
      .catch(() => {});
  }, [conversations]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    executeSearch(inputValue, 1);
  };

  const handleFilterChange = (name: keyof Filters, value: string) => {
    setFilters((prev) => ({ ...prev, [name]: value }));
  };

  useEffect(() => {
    if (searchState.query) {
      executeSearch(searchState.query, 1);
    }
  }, [filters]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const q = searchParams.get("q");
    if (q && q !== searchState.query) {
      setInputValue(q);
      executeSearch(q, 1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const handlePageChange = (newPage: number) => {
    if (newPage >= 1 && newPage <= searchState.totalPages) {
      executeSearch(searchState.query, newPage);
    }
  };

  // Build grouped + nested results
  const grouped = groupByConversation(searchState.messageHits);
  const allConvs = { ...conversations, ...resolvedParents };

  const conversationGroups: ConversationGroup[] = [];
  for (const [convId, hits] of grouped) {
    const firstHit = hits[0];
    const compositeId = `${firstHit.document.source}:${firstHit.document.machine_id}:${convId}`;
    conversationGroups.push({
      conversation: allConvs[convId] || null,
      compositeId,
      conversationId: convId,
      hits,
    });
  }

  // Build ConversationGroupHit wrappers for nesting
  const groupHits: ConversationGroupHit[] = conversationGroups.map((g) => ({
    document: g.conversation || {
      id: g.compositeId,
      source: g.hits[0].document.source,
      machine_id: g.hits[0].document.machine_id,
      project: g.hits[0].document.project,
      conversation_id: g.conversationId,
      first_ts: g.hits[0].document.ts,
      last_ts: g.hits[0].document.ts,
      message_count: 0,
      title: "",
      preview: "",
    },
    group: g,
  }));

  // Add resolved parents that aren't already in groupHits (they have no matches but are needed as nesting targets)
  const existingConvIds = new Set(groupHits.map((g) => g.document.conversation_id));
  for (const conv of Object.values(resolvedParents)) {
    if (!existingConvIds.has(conv.conversation_id)) {
      groupHits.push({
        document: conv,
        group: {
          conversation: conv,
          compositeId: conv.id,
          conversationId: conv.conversation_id,
          hits: [],
        },
      });
    }
  }

  const { topLevel, childrenByParent } = nestSubagentGroups(groupHits);

  const conversationCount = conversationGroups.length;

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <div className="mx-auto max-w-4xl px-4 py-8">
        <header className="mb-8">
          <Link
            href="/"
            className="text-sm text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200"
          >
            &larr; Back to Home
          </Link>
          <h1 className="mt-4 text-3xl font-semibold text-zinc-900 dark:text-zinc-50">
            Search Messages
          </h1>
          <p className="mt-2 text-zinc-600 dark:text-zinc-400">
            Full-text search across all AI conversation messages
          </p>
        </header>

        {/* Search Form */}
        <form onSubmit={handleSubmit} className="mb-6">
          <div className="flex gap-2">
            <input
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder="Search messages..."
              className="flex-1 rounded-lg border border-zinc-300 bg-white px-4 py-3 text-zinc-900 placeholder-zinc-500 focus:border-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:placeholder-zinc-400"
            />
            <button
              type="submit"
              disabled={searchState.loading}
              className="rounded-lg bg-zinc-900 px-6 py-3 font-medium text-white transition-colors hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
            >
              {searchState.loading ? "Searching..." : "Search"}
            </button>
          </div>
          <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
            Tip: Use{" "}
            <code className="bg-zinc-100 dark:bg-zinc-800 px-1 rounded">
              "exact phrase"
            </code>{" "}
            to match exact phrases,
            <code className="bg-zinc-100 dark:bg-zinc-800 px-1 rounded ml-1">
              -exclude
            </code>{" "}
            to exclude words.
          </p>
        </form>

        {/* Faceted Filters */}
        <div className="mb-6 flex flex-wrap gap-4 rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
              Source
            </label>
            <select
              value={filters.source}
              onChange={(e) => handleFilterChange("source", e.target.value)}
              className="rounded border border-zinc-300 bg-white px-3 py-1.5 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100"
            >
              <option value="">All Sources</option>
              {SOURCES.filter(Boolean).map((source) => (
                <option key={source} value={source}>
                  {source.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
              Role
            </label>
            <select
              value={filters.role}
              onChange={(e) => handleFilterChange("role", e.target.value)}
              className="rounded border border-zinc-300 bg-white px-3 py-1.5 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100"
            >
              <option value="">All Roles</option>
              {ROLES.filter(Boolean).map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-1 flex-col gap-1">
            <label className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
              Project
            </label>
            <input
              type="text"
              value={filters.project}
              onChange={(e) => handleFilterChange("project", e.target.value)}
              placeholder="Filter by project path..."
              className="rounded border border-zinc-300 bg-white px-3 py-1.5 text-sm text-zinc-900 placeholder-zinc-400 focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100 dark:placeholder-zinc-500"
            />
          </div>

          <div className="flex flex-1 flex-col gap-1">
            <label className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
              Source Machine
            </label>
            <input
              type="text"
              value={filters.machineId}
              onChange={(e) => handleFilterChange("machineId", e.target.value)}
              placeholder="Filter by machine ID..."
              className="rounded border border-zinc-300 bg-white px-3 py-1.5 text-sm text-zinc-900 placeholder-zinc-400 focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100 dark:placeholder-zinc-500"
            />
          </div>
        </div>

        {/* Error Display */}
        {searchState.error && (
          <div className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4 text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400">
            {searchState.error}
          </div>
        )}

        {/* Results Count */}
        {searchState.total > 0 && (
          <div className="mb-4 text-sm text-zinc-600 dark:text-zinc-400">
            {searchState.total.toLocaleString()} matching message
            {searchState.total !== 1 ? "s" : ""} across{" "}
            {conversationCount} conversation
            {conversationCount !== 1 ? "s" : ""}
          </div>
        )}

        {/* Grouped Search Results */}
        <div className="rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900 overflow-hidden">
          {topLevel.map((groupHit) => (
            <ConversationGroupWithChildren
              key={groupHit.group.conversationId}
              groupHit={groupHit}
              childrenByParent={childrenByParent}
            />
          ))}
        </div>

        {/* Empty State */}
        {!searchState.loading &&
          searchState.query &&
          searchState.messageHits.length === 0 &&
          !searchState.error && (
            <div className="py-12 text-center text-zinc-500 dark:text-zinc-400">
              No results found for &ldquo;{searchState.query}&rdquo;
            </div>
          )}

        {/* Pagination */}
        {searchState.totalPages > 1 && (
          <nav className="mt-8 flex items-center justify-center gap-2">
            <button
              onClick={() => handlePageChange(searchState.page - 1)}
              disabled={searchState.page === 1}
              className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
            >
              Previous
            </button>
            <span className="px-4 text-sm text-zinc-600 dark:text-zinc-400">
              Page {searchState.page} of {searchState.totalPages}
            </span>
            <button
              onClick={() => handlePageChange(searchState.page + 1)}
              disabled={searchState.page === searchState.totalPages}
              className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
            >
              Next
            </button>
          </nav>
        )}
      </div>
    </div>
  );
}

export default function SearchPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-zinc-50 dark:bg-black p-8 text-center text-zinc-500">
          Loading search...
        </div>
      }
    >
      <SearchPageContent />
    </Suspense>
  );
}
