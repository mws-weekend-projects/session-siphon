/**
 * Client-side API functions for Session Siphon.
 *
 * These functions call the Next.js API routes, which proxy to Typesense
 * server-side. Use these in "use client" components instead of importing
 * typesense.ts directly.
 */

import type {
  Message,
  Conversation,
  MessageFilters,
  ConversationFilters,
  PaginationOptions,
  SearchResults,
} from "./types";

// Re-export types for convenience
export type {
  Message,
  Conversation,
  MessageFilters,
  ConversationFilters,
  PaginationOptions,
  SearchResults,
  SearchHit,
} from "./types";

/**
 * Search conversations via the API route.
 */
export async function searchConversations(
  query: string,
  filters: ConversationFilters = {},
  pagination: PaginationOptions = {}
): Promise<SearchResults<Conversation>> {
  const response = await fetch("/api/search/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, filters, pagination }),
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error ?? `Search failed: ${response.status}`);
  }

  return response.json();
}

/**
 * Fetch conversations related to a given conversation (children, siblings, parent).
 */
export async function fetchRelatedConversations(
  conversationId: string,
  parentConversationId?: string
): Promise<SearchResults<Conversation>> {
  const response = await fetch("/api/conversations/related", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conversationId, parentConversationId }),
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error ?? `Fetch failed: ${response.status}`);
  }

  return response.json();
}

/**
 * Fetch conversations by their conversation_id values.
 */
export async function fetchConversationsByIds(
  ids: string[]
): Promise<SearchResults<Conversation>> {
  if (ids.length === 0) {
    return { hits: [], found: 0, page: 1, perPage: 0, totalPages: 0 };
  }

  const response = await fetch("/api/conversations/by-ids", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error ?? `Fetch failed: ${response.status}`);
  }

  return response.json();
}

/**
 * Search messages via the API route.
 */
export async function searchMessages(
  query: string,
  filters: MessageFilters = {},
  pagination: PaginationOptions = {}
): Promise<SearchResults<Message>> {
  const response = await fetch("/api/search/messages", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, filters, pagination }),
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error ?? `Search failed: ${response.status}`);
  }

  return response.json();
}
