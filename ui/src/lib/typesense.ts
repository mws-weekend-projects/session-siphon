/**
 * Server-side Typesense client for Session Siphon.
 *
 * This module should only be imported by server components and API routes.
 * Client components should use api.ts instead.
 */

import type {
  Message,
  Conversation,
  MessageFilters,
  ConversationFilters,
  PaginationOptions,
  SearchResults,
  SearchHit,
} from "./types";

// Re-export types for convenience (server-side consumers)
export type {
  Message,
  Conversation,
  MessageFilters,
  ConversationFilters,
  PaginationOptions,
  SearchResults,
  SearchHit,
};

// Server-side configuration from environment
const TYPESENSE_HOST = process.env.TYPESENSE_HOST ?? "localhost";
const TYPESENSE_PORT = process.env.TYPESENSE_PORT ?? "8108";
const TYPESENSE_PROTOCOL = process.env.TYPESENSE_PROTOCOL ?? "http";
const TYPESENSE_API_KEY = process.env.TYPESENSE_API_KEY ?? "dev-api-key";

// Collection names
const MESSAGES_COLLECTION = "messages";
const CONVERSATIONS_COLLECTION = "conversations";

/**
 * Raw Typesense API response shape.
 */
interface TypesenseSearchResponse<T> {
  found: number;
  facet_counts?: Array<{
    field_name: string;
    counts: Array<{
      value: string;
      count: number;
    }>;
  }>;
  hits: Array<{
    document: T;
    highlights?: Array<{
      field: string;
      snippet?: string;
      matched_tokens?: string[];
    }>;
    text_match?: number;
  }>;
  page: number;
  request_params?: {
    per_page?: number;
  };
}

/**
 * Get the base URL for Typesense API requests.
 */
function getBaseUrl(): string {
  return `${TYPESENSE_PROTOCOL}://${TYPESENSE_HOST}:${TYPESENSE_PORT}`;
}

/**
 * Build filter string from message filter options.
 */
function buildMessageFilterString(filters: MessageFilters): string {
  const parts: string[] = [];

  if (filters.source) {
    parts.push(`source:=${filters.source}`);
  }
  if (filters.machineId) {
    parts.push(`machine_id:=${filters.machineId}`);
  }
  if (filters.project) {
    parts.push(`project:=${filters.project}`);
  }
  if (filters.conversationId) {
    parts.push(`conversation_id:=${filters.conversationId}`);
  }
  if (filters.role) {
    parts.push(`role:=${filters.role}`);
  }
  if (filters.startTs !== undefined) {
    parts.push(`ts:>=${filters.startTs}`);
  }
  if (filters.endTs !== undefined) {
    parts.push(`ts:<=${filters.endTs}`);
  }

  return parts.join(" && ");
}

/**
 * Build filter string from conversation filter options.
 */
function buildConversationFilterString(filters: ConversationFilters): string {
  const parts: string[] = [];

  if (filters.source) {
    parts.push(`source:=${filters.source}`);
  }
  if (filters.machineId) {
    parts.push(`machine_id:=${filters.machineId}`);
  }
  if (filters.project) {
    parts.push(`project:=${filters.project}`);
  }
  if (filters.startTs !== undefined) {
    parts.push(`last_ts:>=${filters.startTs}`);
  }
  if (filters.endTs !== undefined) {
    parts.push(`first_ts:<=${filters.endTs}`);
  }

  return parts.join(" && ");
}

/**
 * Execute a search request against Typesense.
 */
async function executeSearch<T>(
  collection: string,
  params: Record<string, string | number>
): Promise<TypesenseSearchResponse<T>> {
  const url = new URL(`${getBaseUrl()}/collections/${collection}/documents/search`);

  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, String(value));
  }

  const response = await fetch(url.toString(), {
    method: "GET",
    headers: {
      "X-TYPESENSE-API-KEY": TYPESENSE_API_KEY,
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Typesense search failed: ${response.status} ${error}`);
  }

  return response.json() as Promise<TypesenseSearchResponse<T>>;
}

/**
 * Transform Typesense response to our SearchResults format.
 */
function transformResponse<T>(
  response: TypesenseSearchResponse<T>,
  perPage: number
): SearchResults<T> {
  const hits: SearchHit<T>[] = response.hits.map((hit) => ({
    document: hit.document,
    highlights: (hit.highlights ?? []).map((h) => ({
      field: h.field,
      snippet: h.snippet ?? "",
      matchedTokens: h.matched_tokens ?? [],
    })),
    textMatch: hit.text_match ?? 0,
  }));

  const totalPages = Math.ceil(response.found / perPage);

  const facetCounts: Record<string, Array<{ value: string; count: number }>> = {};
  if (response.facet_counts) {
    for (const facet of response.facet_counts) {
      facetCounts[facet.field_name] = facet.counts;
    }
  }

  return {
    hits,
    found: response.found,
    page: response.page,
    perPage,
    totalPages,
    facetCounts,
  };
}

/**
 * Search messages by query string.
 */
export async function searchMessages(
  query: string,
  filters: MessageFilters = {},
  pagination: PaginationOptions = {}
): Promise<SearchResults<Message>> {
  const page = pagination.page ?? 1;
  const perPage = pagination.perPage ?? 10;

  const params: Record<string, string | number> = {
    q: query,
    query_by: "content",
    page,
    per_page: perPage,
    sort_by: "ts:desc",
  };

  const filterStr = buildMessageFilterString(filters);
  if (filterStr) {
    params.filter_by = filterStr;
  }

  const response = await executeSearch<Message>(MESSAGES_COLLECTION, params);
  return transformResponse(response, perPage);
}

/**
 * Search conversations by query string.
 */
export async function searchConversations(
  query: string,
  filters: ConversationFilters = {},
  pagination: PaginationOptions = {}
): Promise<SearchResults<Conversation>> {
  const page = pagination.page ?? 1;
  const perPage = pagination.perPage ?? 10;

  const params: Record<string, string | number> = {
    q: query,
    query_by: "title,preview",
    page,
    per_page: perPage,
    sort_by: "last_ts:desc",
    facet_by: "source,project,machine_id",
    max_facet_values: 100,
  };

  const filterStr = buildConversationFilterString(filters);
  if (filterStr) {
    params.filter_by = filterStr;
  }

  const response = await executeSearch<Conversation>(
    CONVERSATIONS_COLLECTION,
    params
  );
  return transformResponse(response, perPage);
}

/**
 * Get all messages in a specific conversation.
 */
export async function getConversationMessages(
  conversationId: string,
  pagination: PaginationOptions = {}
): Promise<SearchResults<Message>> {
  const page = pagination.page ?? 1;
  const perPage = pagination.perPage ?? 50;

  const params: Record<string, string | number> = {
    q: "*",
    query_by: "content",
    filter_by: `conversation_id:=${conversationId}`,
    page,
    per_page: perPage,
    sort_by: "ts:asc",
  };

  const response = await executeSearch<Message>(MESSAGES_COLLECTION, params);
  return transformResponse(response, perPage);
}

/**
 * Get conversations related to a given conversation (children and siblings).
 *
 * Finds conversations that share a parent_conversation_id OR that are children
 * of the given conversation_id.
 */
export async function getRelatedConversations(
  conversationId: string,
  parentConversationId?: string
): Promise<SearchResults<Conversation>> {
  const perPage = 50;
  const filterParts: string[] = [];

  // Find children: conversations whose parent_conversation_id is this one
  filterParts.push(`parent_conversation_id:=${conversationId}`);

  // If this conversation has a parent, also find siblings (same parent)
  // and the parent itself
  if (parentConversationId) {
    filterParts.push(`parent_conversation_id:=${parentConversationId}`);
    filterParts.push(`conversation_id:=${parentConversationId}`);
  }

  const params: Record<string, string | number> = {
    q: "*",
    query_by: "title,preview",
    filter_by: filterParts.join(" || "),
    per_page: perPage,
    sort_by: "last_ts:desc",
  };

  const response = await executeSearch<Conversation>(
    CONVERSATIONS_COLLECTION,
    params
  );
  return transformResponse(response, perPage);
}

/**
 * Get conversations by their conversation_id field values.
 */
export async function getConversationsByConversationIds(
  conversationIds: string[]
): Promise<SearchResults<Conversation>> {
  if (conversationIds.length === 0) {
    return { hits: [], found: 0, page: 1, perPage: 0, totalPages: 0 };
  }

  const filterValue = conversationIds.map((id) => `\`${id}\``).join(",");
  const params: Record<string, string | number> = {
    q: "*",
    query_by: "title,preview",
    filter_by: `conversation_id:=[${filterValue}]`,
    per_page: conversationIds.length,
    sort_by: "last_ts:desc",
  };

  const response = await executeSearch<Conversation>(
    CONVERSATIONS_COLLECTION,
    params
  );
  return transformResponse(response, conversationIds.length);
}

/**
 * Get a single conversation by ID.
 */
export async function getConversationById(
  id: string
): Promise<Conversation | null> {
  const url = `${getBaseUrl()}/collections/${CONVERSATIONS_COLLECTION}/documents/${encodeURIComponent(id)}`;

  const response = await fetch(url, {
    method: "GET",
    headers: {
      "X-TYPESENSE-API-KEY": TYPESENSE_API_KEY,
      "Content-Type": "application/json",
    },
  });

  if (response.status === 404) {
    return null;
  }

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Typesense fetch failed: ${response.status} ${error}`);
  }

  return response.json() as Promise<Conversation>;
}
