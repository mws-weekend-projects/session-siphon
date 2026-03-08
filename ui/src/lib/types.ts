/**
 * Shared types for Session Siphon UI.
 *
 * Used by both server-side (typesense.ts) and client-side (api.ts) code.
 */

/**
 * Message document matching CanonicalMessage.to_typesense_doc()
 */
export interface Message {
  id: string;
  source: string;
  machine_id: string;
  project: string;
  conversation_id: string;
  ts: number;
  role: string;
  content: string;
  content_hash: string;
  raw_path: string;
  raw_offset: number;
}

/**
 * Conversation document matching Conversation.to_typesense_doc()
 */
export interface Conversation {
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
  relationship_type?: string; // "fork", "continuation", "subagent"
  compaction_count?: number;
}

/**
 * Pagination options for search requests.
 */
export interface PaginationOptions {
  page?: number;
  perPage?: number;
}

/**
 * Filter options for message searches.
 */
export interface MessageFilters {
  source?: string;
  machineId?: string;
  project?: string;
  conversationId?: string;
  role?: string;
  startTs?: number;
  endTs?: number;
}

/**
 * Filter options for conversation searches.
 */
export interface ConversationFilters {
  source?: string;
  machineId?: string;
  project?: string;
  startTs?: number;
  endTs?: number;
}

/**
 * A single search hit with highlighting information.
 */
export interface SearchHit<T> {
  document: T;
  highlights: Array<{
    field: string;
    snippet: string;
    matchedTokens: string[];
  }>;
  textMatch: number;
}

/**
 * Paginated search results.
 */
export interface SearchResults<T> {
  hits: SearchHit<T>[];
  found: number;
  page: number;
  perPage: number;
  totalPages: number;
  facetCounts?: Record<string, Array<{ value: string; count: number }>>;
}
