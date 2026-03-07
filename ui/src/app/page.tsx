"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  searchConversations,
  type Conversation,
  type ConversationFilters,
  type SearchResults,
} from "@/lib/api";
import { SearchableSelect } from "@/components/SearchableSelect";

function formatTimestamp(ts: number): string {
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
    claude_code: "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300",
    codex: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
    vscode_copilot: "bg-sky-100 text-sky-800 dark:bg-sky-900/30 dark:text-sky-300",
    gemini_cli: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/30 dark:text-indigo-300",
  };
  return colors[source] || "bg-zinc-100 text-zinc-800 dark:bg-zinc-800 dark:text-zinc-300";
}

function getProjectName(project: string): string {
  if (!project) return "Unknown Project";
  const parts = project.split("/");
  return parts[parts.length - 1] || project;
}

function ProjectNameDisplay({ project }: { project: string }) {
  if (!project) {
    return (
        <span className="font-medium text-zinc-500 italic">
            Unknown Project
        </span>
    );
  }
  const parts = project.split("/");
  const name = parts.pop() || project;
  const path = parts.join("/");

  return (
    <span className="flex items-baseline gap-2 truncate" title={project}>
      <span className="font-medium text-zinc-900 dark:text-zinc-100">
        {name}
      </span>
      {path && (
        <span className="text-xs text-zinc-400 dark:text-zinc-500 font-normal truncate">
          {path}
        </span>
      )}
    </span>
  );
}

interface FiltersProps {
  filters: ConversationFilters;
  sources: string[];
  projects: string[];
  machineIds: string[];
  onFilterChange: (filters: ConversationFilters) => void;
  groupByProject: boolean;
  onGroupByProjectChange: (enabled: boolean) => void;
}

function Filters({
  filters,
  sources,
  projects,
  machineIds,
  onFilterChange,
  groupByProject,
  onGroupByProjectChange,
}: FiltersProps) {
  return (
    <div className="flex flex-wrap gap-4 p-4 border-b border-zinc-200 dark:border-zinc-800 items-end">
      <div className="flex flex-col gap-1 w-48">
        <label
          htmlFor="source-filter"
          className="text-xs font-medium text-zinc-500 dark:text-zinc-400"
        >
          Source
        </label>
        <SearchableSelect
          value={filters.source || ""}
          onChange={(val) =>
            onFilterChange({ ...filters, source: val || undefined })
          }
          options={sources.map(s => ({ value: s, label: formatSourceName(s) }))}
          placeholder="All Sources"
        />
      </div>

      <div className="flex flex-col gap-1 w-48">
        <label
          htmlFor="machine-filter"
          className="text-xs font-medium text-zinc-500 dark:text-zinc-400"
        >
          Source Machine
        </label>
        <SearchableSelect
          value={filters.machineId || ""}
          onChange={(val) =>
            onFilterChange({ ...filters, machineId: val || undefined })
          }
          options={machineIds.map(m => ({ value: m, label: m }))}
          placeholder="All Machines"
        />
      </div>

      <div className="flex flex-col gap-1 w-64">
        <label
          htmlFor="project-filter"
          className="text-xs font-medium text-zinc-500 dark:text-zinc-400"
        >
          Project
        </label>
        <SearchableSelect
          value={filters.project || ""}
          onChange={(val) =>
            onFilterChange({ ...filters, project: val || undefined })
          }
          options={projects.map(p => ({ value: p, label: getProjectName(p) }))}
          placeholder="All Projects"
        />
      </div>

      <div className="flex items-center gap-2 pb-2">
        <input
          type="checkbox"
          id="group-by-project"
          checked={groupByProject}
          onChange={(e) => onGroupByProjectChange(e.target.checked)}
          className="w-4 h-4 text-blue-600 bg-zinc-100 border-zinc-300 rounded focus:ring-blue-500 dark:focus:ring-blue-600 dark:ring-offset-zinc-800 focus:ring-2 dark:bg-zinc-700 dark:border-zinc-600"
        />
        <label
          htmlFor="group-by-project"
          className="text-sm font-medium text-zinc-700 dark:text-zinc-300"
        >
          Group by Project
        </label>
      </div>

      {(filters.source || filters.project || filters.machineId) && (
        <div className="flex items-end">
          <button
            onClick={() => onFilterChange({})}
            className="px-3 py-1.5 text-sm text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100"
          >
            Clear filters
          </button>
        </div>
      )}
    </div>
  );
}

function RelationshipIndicator({ type }: { type?: string }) {
  if (!type) return null;
  if (type === "fork") {
    return (
      <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300" title="Forked from another session">
        Fork
      </span>
    );
  }
  if (type === "continuation") {
    return (
      <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300" title="Continuation of another session">
        Continuation
      </span>
    );
  }
  if (type === "subagent") {
    return (
      <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300" title="Subagent task from parent session">
        Subagent
      </span>
    );
  }
  return null;
}

function ConversationCard({ conversation, showProject = true, indented = false }: { conversation: Conversation; showProject?: boolean; indented?: boolean }) {
  return (
    <a
      href={`/conversation/${encodeURIComponent(conversation.id)}`}
      className={`block p-4 border-b border-zinc-200 dark:border-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-900 transition-colors group ${indented ? "pl-10" : ""}`}
    >
      <div className="flex justify-between items-start gap-4 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <RelationshipIndicator type={conversation.relationship_type} />
          <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-100 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors line-clamp-1">
            {conversation.title || "Untitled Conversation"}
          </h3>
        </div>
        <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400 whitespace-nowrap">
          {formatTimestamp(conversation.last_ts)}
        </span>
      </div>

      <p className="text-sm text-zinc-600 dark:text-zinc-400 line-clamp-2 mb-3 leading-relaxed">
        {conversation.preview || "No preview available"}
      </p>

      <div className="flex items-center gap-3 text-xs">
        <span className={`px-2 py-0.5 rounded-full font-medium ${getSourceColor(conversation.source)}`}>
          {formatSourceName(conversation.source)}
        </span>
        <span className="text-zinc-500 dark:text-zinc-400 font-mono">
          {conversation.machine_id}
        </span>
        {showProject && (
          <span className="text-zinc-500 dark:text-zinc-400 flex items-center gap-1">
             <span className="opacity-50">in</span>
             <ProjectNameDisplay project={conversation.project} />
          </span>
        )}
        <span className="text-zinc-400 dark:text-zinc-500">•</span>
        <span className="text-zinc-500 dark:text-zinc-400 font-medium">{conversation.message_count} messages</span>
        {conversation.compaction_count ? (
          <>
            <span className="text-zinc-400 dark:text-zinc-500">•</span>
            <span className="text-zinc-400 dark:text-zinc-500">{conversation.compaction_count} compactions</span>
          </>
        ) : null}
      </div>
    </a>
  );
}

function ProjectGroup({
  projectName,
  hits,
  initiallyExpanded = true,
}: {
  projectName: string;
  hits: { document: Conversation }[];
  initiallyExpanded?: boolean;
}) {
  const [isExpanded, setIsExpanded] = useState(initiallyExpanded);

  return (
    <div className="border-b border-zinc-200 dark:border-zinc-800">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center gap-3 p-4 text-left hover:bg-zinc-50 dark:hover:bg-zinc-900 transition-colors group"
      >
        {isExpanded ? (
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="text-zinc-400 group-hover:text-zinc-600 dark:group-hover:text-zinc-300 transition-colors"
          >
            <path d="m6 9 6 6 6-6" />
          </svg>
        ) : (
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="text-zinc-400 group-hover:text-zinc-600 dark:group-hover:text-zinc-300 transition-colors"
          >
            <path d="m9 18 6-6-6-6" />
          </svg>
        )}
        <div className="flex-1 overflow-hidden">
          <ProjectNameDisplay project={projectName} />
        </div>
        <span className="text-xs font-semibold text-zinc-600 dark:text-zinc-300 bg-zinc-100 dark:bg-zinc-800 px-2.5 py-0.5 rounded-full">
          {hits.length}
        </span>
      </button>

      {isExpanded && (
        <div className="border-l-2 border-zinc-100 dark:border-zinc-800 ml-6 pl-2 mb-2">
          {hits.map((hit) => (
            <ConversationCard
              key={hit.document.id}
              conversation={hit.document}
              showProject={false}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface PaginationProps {
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

function Pagination({ page, totalPages, onPageChange }: PaginationProps) {
  if (totalPages <= 1) return null;

  return (
    <div className="flex justify-center items-center gap-2 p-4 border-t border-zinc-200 dark:border-zinc-800">
      <button
        onClick={() => onPageChange(page - 1)}
        disabled={page <= 1}
        className="px-3 py-1.5 text-sm border border-zinc-300 dark:border-zinc-700 rounded-md disabled:opacity-50 disabled:cursor-not-allowed hover:bg-zinc-50 dark:hover:bg-zinc-900"
      >
        Previous
      </button>
      <span className="text-sm text-zinc-600 dark:text-zinc-400">
        Page {page} of {totalPages}
      </span>
      <button
        onClick={() => onPageChange(page + 1)}
        disabled={page >= totalPages}
        className="px-3 py-1.5 text-sm border border-zinc-300 dark:border-zinc-700 rounded-md disabled:opacity-50 disabled:cursor-not-allowed hover:bg-zinc-50 dark:hover:bg-zinc-900"
      >
        Next
      </button>
    </div>
  );
}

export default function Home() {
  const router = useRouter();
  const [results, setResults] = useState<SearchResults<Conversation> | null>(
    null
  );
  const [searchQuery, setSearchQuery] = useState("");
  const [filters, setFilters] = useState<ConversationFilters>({});
  const [groupByProject, setGroupByProject] = useState(true);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [availableSources, setAvailableSources] = useState<string[]>([]);
  const [availableProjects, setAvailableProjects] = useState<string[]>([]);
  const [availableMachineIds, setAvailableMachineIds] = useState<string[]>([]);

  const fetchConversations = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const data = await searchConversations(searchQuery || "*", filters, {
        page,
        perPage: 20,
      });
      setResults(data);

      // Extract unique sources and projects from facet counts
      // Only update if we have no filters applied (to get full list of options)
      if (data.facetCounts && !filters.source && !filters.project && !filters.machineId) {
        if (data.facetCounts["source"]) {
          setAvailableSources(
            data.facetCounts["source"].map((f) => f.value).sort()
          );
        }
        if (data.facetCounts["project"]) {
          setAvailableProjects(
            data.facetCounts["project"].map((f) => f.value).sort()
          );
        }
        if (data.facetCounts["machine_id"]) {
          setAvailableMachineIds(
            data.facetCounts["machine_id"].map((f) => f.value).sort()
          );
        }
      } else if (!data.facetCounts && !filters.source && !filters.project && !filters.machineId) {
        // Fallback to extraction from hits if facets are missing (should generally not happen)
        const sources = new Set<string>();
        const projects = new Set<string>();
        const machineIds = new Set<string>();
        data.hits.forEach((hit) => {
          sources.add(hit.document.source);
          projects.add(hit.document.project);
          machineIds.add(hit.document.machine_id);
        });
        setAvailableSources(Array.from(sources).sort());
        setAvailableProjects(Array.from(projects).sort());
        setAvailableMachineIds(Array.from(machineIds).sort());
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to fetch conversations"
      );
    } finally {
      setLoading(false);
    }
  }, [filters, page, searchQuery]);

  useEffect(() => {
    const timer = setTimeout(() => {
      fetchConversations();
    }, 300);
    return () => clearTimeout(timer);
  }, [fetchConversations]);

  const handleFilterChange = (newFilters: ConversationFilters) => {
    setFilters(newFilters);
    setPage(1); // Reset to first page when filters change
  };

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      router.push(`/search?q=${encodeURIComponent(searchQuery)}`);
    }
  };

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <header className="bg-white dark:bg-zinc-950 border-b border-zinc-200 dark:border-zinc-800">
        <div className="max-w-4xl mx-auto px-4 py-4 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">
              Session Siphon
            </h1>
            <p className="text-sm text-zinc-600 dark:text-zinc-400">
              AI Conversation History
            </p>
          </div>
          <div className="flex flex-col items-end gap-1 w-full md:w-auto">
            <form onSubmit={handleSearchSubmit} className="flex gap-3 w-full">
              <input
                type="text"
                placeholder="Search conversations..."
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setPage(1);
                }}
                className="px-3 py-1.5 text-sm bg-white dark:bg-zinc-900 border border-zinc-300 dark:border-zinc-700 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 w-full md:w-64"
              />
              <button
                type="submit"
                className="px-3 py-1.5 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 whitespace-nowrap"
              >
                Search Messages
              </button>
            </form>
            <div className="text-[10px] text-zinc-400 dark:text-zinc-500 text-right">
                Supported: "exact phrase", -exclude, prefix*
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto bg-white dark:bg-zinc-950">
        <Filters
          filters={filters}
          sources={availableSources}
          projects={availableProjects}
          machineIds={availableMachineIds}
          onFilterChange={handleFilterChange}
          groupByProject={groupByProject}
          onGroupByProjectChange={setGroupByProject}
        />

        {loading && (
          <div className="p-8 text-center text-zinc-500 dark:text-zinc-400">
            Loading conversations...
          </div>
        )}

        {error && (
          <div className="p-8 text-center">
            <p className="text-red-600 dark:text-red-400 mb-4">{error}</p>
            <button
              onClick={fetchConversations}
              className="px-4 py-2 text-sm bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 rounded-md hover:bg-zinc-700 dark:hover:bg-zinc-300"
            >
              Retry
            </button>
          </div>
        )}

        {!loading && !error && results && (
          <>
            {results.hits.length === 0 ? (
              <div className="p-8 text-center text-zinc-500 dark:text-zinc-400">
                {filters.source || filters.project || filters.machineId
                  ? "No conversations match your filters"
                  : "No conversations found"}
              </div>
            ) : (
              <div>
                <div className="px-4 py-2 text-xs text-zinc-500 dark:text-zinc-400 border-b border-zinc-100 dark:border-zinc-800">
                  {results.found} conversation{results.found !== 1 ? "s" : ""}
                </div>
                {groupByProject ? (
                  Object.entries(
                    results.hits.reduce((acc, hit) => {
                      const project = hit.document.project;
                      if (!acc[project]) acc[project] = [];
                      acc[project].push(hit);
                      return acc;
                    }, {} as Record<string, typeof results.hits>)
                  )
                    .map(([project, hits]) => ({
                      project,
                      hits: hits.sort(
                        (a, b) => b.document.last_ts - a.document.last_ts
                      ),
                      latestTs: Math.max(
                        ...hits.map((h) => h.document.last_ts)
                      ),
                    }))
                    .sort((a, b) => b.latestTs - a.latestTs)
                    .map((group) => (
                      <ProjectGroup
                        key={group.project}
                        projectName={group.project}
                        hits={group.hits}
                      />
                    ))
                ) : (
                  results.hits.map((hit) => (
                    <ConversationCard
                      key={hit.document.id}
                      conversation={hit.document}
                    />
                  ))
                )}
              </div>
            )}

            <Pagination
              page={results.page}
              totalPages={results.totalPages}
              onPageChange={setPage}
            />
          </>
        )}
      </main>
    </div>
  );
}
