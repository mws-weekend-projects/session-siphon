import {
  getConversationById,
  getConversationMessages,
  getRelatedConversations,
} from "@/lib/typesense";
import { MessageBubble } from "@/components/MessageBubble";
import type { Conversation } from "@/lib/types";
import Link from "next/link";

interface ConversationPageProps {
  params: Promise<{ id: string }>;
}

function formatTimestamp(ts: number): string {
  return new Date(ts * 1000).toLocaleString();
}

function formatSource(source: string): string {
  const sourceNames: Record<string, string> = {
    claude_code: "Claude Code",
    codex: "Codex",
    vscode_copilot: "VS Code Copilot",
    gemini_cli: "Gemini CLI",
  };
  return sourceNames[source] || source;
}

/**
 * Extract the Claude Code session UUID from a raw_path.
 * Main sessions: .../projects/<encoded-path>/<session-uuid>.jsonl
 * Subagents: .../projects/<encoded-path>/<session-uuid>/subagents/<agent-id>.jsonl
 */
function extractClaudeSessionId(rawPath: string, conversationId: string): string {
  const subagentMatch = rawPath.match(
    /\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\/subagents\//
  );
  if (subagentMatch) {
    return subagentMatch[1];
  }
  // For main sessions, the conversation_id is already the UUID
  return conversationId;
}

function getSessionId(source: string, conversationId: string, rawPath: string): string | null {
  switch (source) {
    case "claude_code":
      return extractClaudeSessionId(rawPath, conversationId);
    default:
      return conversationId;
  }
}

function getResumeHint(source: string, sessionId: string, isSubagent: boolean): string | null {
  if (isSubagent) return null;
  switch (source) {
    case "claude_code":
      return `claude --resume ${sessionId}`;
    case "codex":
      return `codex --resume ${sessionId}`;
    case "gemini_cli":
      return `gemini --session ${sessionId}`;
    default:
      return null;
  }
}

function RelationshipBadge({ type }: { type: string }) {
  if (type === "fork") {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300">
        Fork
      </span>
    );
  }
  if (type === "continuation") {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">
        Continuation
      </span>
    );
  }
  if (type === "subagent") {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300">
        Subagent
      </span>
    );
  }
  return null;
}

function RelatedSessionLink({ conv, currentId }: { conv: Conversation; currentId: string }) {
  const isCurrent = conv.id === currentId;
  return (
    <a
      href={isCurrent ? undefined : `/conversation/${encodeURIComponent(conv.id)}`}
      className={`block px-3 py-2 rounded-md text-sm transition-colors ${
        isCurrent
          ? "bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 cursor-default"
          : "hover:bg-zinc-100 dark:hover:bg-zinc-800"
      }`}
    >
      <div className="flex items-center gap-2">
        {conv.relationship_type && (
          <RelationshipBadge type={conv.relationship_type} />
        )}
        <span className={`truncate ${isCurrent ? "font-semibold text-blue-700 dark:text-blue-300" : "text-zinc-700 dark:text-zinc-300"}`}>
          {conv.title || "Untitled"}
        </span>
      </div>
      <div className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
        {conv.message_count} messages
        {conv.compaction_count ? ` · ${conv.compaction_count} compactions` : ""}
      </div>
    </a>
  );
}

function RelatedSessionsPanel({
  conversation,
  relatedConversations,
}: {
  conversation: Conversation;
  relatedConversations: Conversation[];
}) {
  if (relatedConversations.length === 0) return null;

  // Separate into parent, current, children, siblings
  const parent = relatedConversations.find(
    (c) => c.conversation_id === conversation.parent_conversation_id
  );
  const children = relatedConversations.filter(
    (c) =>
      c.parent_conversation_id === conversation.conversation_id &&
      c.id !== conversation.id
  );
  const siblings = relatedConversations.filter(
    (c) =>
      c.parent_conversation_id === conversation.parent_conversation_id &&
      c.id !== conversation.id &&
      c.conversation_id !== conversation.parent_conversation_id
  );

  return (
    <div className="border-t border-zinc-200 dark:border-zinc-800 mt-3 pt-3">
      <h3 className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wide mb-2">
        Session Context
      </h3>
      <div className="space-y-1">
        {parent && (
          <div>
            <div className="text-[10px] font-medium text-zinc-400 dark:text-zinc-500 uppercase mb-0.5">Parent</div>
            <RelatedSessionLink conv={parent} currentId={conversation.id} />
          </div>
        )}
        {siblings.length > 0 && (
          <div>
            <div className="text-[10px] font-medium text-zinc-400 dark:text-zinc-500 uppercase mb-0.5">
              Siblings ({siblings.length})
            </div>
            {siblings.map((s) => (
              <RelatedSessionLink key={s.id} conv={s} currentId={conversation.id} />
            ))}
          </div>
        )}
        {children.length > 0 && (
          <div>
            <div className="text-[10px] font-medium text-zinc-400 dark:text-zinc-500 uppercase mb-0.5">
              Children ({children.length})
            </div>
            {children.map((c) => (
              <RelatedSessionLink key={c.id} conv={c} currentId={conversation.id} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default async function ConversationPage({
  params,
}: ConversationPageProps) {
  const { id } = await params;
  const decodedId = decodeURIComponent(id);

  // The URL id is the composite document ID (e.g., "claude_code:p16:agent-a3f6a2b")
  // Look up the conversation to get the actual conversation_id field
  const conversation = await getConversationById(decodedId);
  const conversationId = conversation?.conversation_id ?? decodedId;

  const results = await getConversationMessages(conversationId, { perPage: 250 });
  const messages = results.hits.map((hit) => hit.document);

  // Fetch related conversations (parent, children, siblings)
  let relatedConversations: Conversation[] = [];
  if (conversation) {
    try {
      const relatedResults = await getRelatedConversations(
        conversation.conversation_id,
        conversation.parent_conversation_id
      );
      relatedConversations = relatedResults.hits.map((h) => h.document);
    } catch {
      // Non-critical - continue without related conversations
    }
  }

  if (messages.length === 0) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-zinc-50 dark:bg-black">
        <div className="text-center">
          <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100">
            Conversation not found
          </h1>
          <p className="mt-2 text-zinc-600 dark:text-zinc-400">
            No messages found for this conversation ID.
          </p>
          <Link
            href="/"
            className="mt-4 inline-block text-blue-600 hover:underline dark:text-blue-400"
          >
            Back to home
          </Link>
        </div>
      </div>
    );
  }

  const firstMessage = messages[0];
  const lastMessage = messages[messages.length - 1];
  const isSubagent = conversation?.relationship_type === "subagent";
  const sessionId = getSessionId(firstMessage.source, conversationId, firstMessage.raw_path);
  const resumeHint = sessionId ? getResumeHint(firstMessage.source, sessionId, isSubagent) : null;

  return (
    <div className="flex min-h-screen flex-col bg-zinc-50 dark:bg-black">
      <header className="sticky top-0 z-10 border-b border-zinc-200 bg-white px-4 py-4 dark:border-zinc-800 dark:bg-zinc-950">
        <div className="mx-auto max-w-4xl">
          <div className="flex items-center gap-4">
            <Link
              href="/"
              className="text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200"
            >
              &larr; Back
            </Link>
            <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
              Conversation
            </h1>
          </div>
          <div className="mt-3 flex flex-wrap gap-x-6 gap-y-2 text-sm text-zinc-600 dark:text-zinc-400">
            <div>
              <span className="font-medium">Source:</span>{" "}
              {formatSource(firstMessage.source)}
            </div>
            {sessionId && (
              <div>
                <span className="font-medium">Session:</span>{" "}
                <code className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-xs dark:bg-zinc-800">
                  {sessionId}
                </code>
              </div>
            )}
            <div>
              <span className="font-medium">Machine:</span>{" "}
              <span className="font-mono text-xs">{firstMessage.machine_id}</span>
            </div>
            <div>
              <span className="font-medium">Project:</span>{" "}
              <span className="font-mono text-xs">{firstMessage.project}</span>
            </div>
            <div>
              <span className="font-medium">Started:</span>{" "}
              {formatTimestamp(firstMessage.ts)}
            </div>
            <div>
              <span className="font-medium">Last message:</span>{" "}
              {formatTimestamp(lastMessage.ts)}
            </div>
            <div>
              <span className="font-medium">Messages:</span> {messages.length}
            </div>
          </div>
          {resumeHint && (
            <div className="mt-2 text-xs text-zinc-500 dark:text-zinc-500">
              Resume:{" "}
              <code className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono dark:bg-zinc-800">
                {resumeHint}
              </code>
            </div>
          )}
          {conversation && relatedConversations.length > 0 && (
            <RelatedSessionsPanel
              conversation={conversation}
              relatedConversations={relatedConversations}
            />
          )}
        </div>
      </header>

      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-4xl px-4 py-6">
          <div className="flex flex-col gap-4">
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}
