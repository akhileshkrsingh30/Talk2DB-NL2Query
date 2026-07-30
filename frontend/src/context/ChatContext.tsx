import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, streamQuery } from "../api/client";
import { addLocalHistoryEntry, buildSqlHistoryEntry } from "../lib/localHistory";
import type { QueryResultRow, SQLQuery, StreamEvent } from "../api/types";

type ResultSets = (QueryResultRow[] | QueryResultRow)[];

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  query?: string;
  statusLog: string[];
  sqlQueries?: SQLQuery[];
  results?: ResultSets;
  explanation: string;
  error?: string;
  done: boolean;
  metadata?: Record<string, unknown>;
  shareUrl?: string;
  shareError?: string;
  sharing?: boolean;
}

interface ChatContextValue {
  input: string;
  setInput: (val: string) => void;
  messages: ChatMessage[];
  streaming: boolean;
  handleSend: () => Promise<void>;
  handleStop: () => void;
  handleNewChat: () => void;
  handleShare: (assistantId: string) => Promise<void>;
}

const ChatContext = createContext<ChatContextValue | undefined>(undefined);

function getSessionId(): string {
  const key = "talk2db_session_id";
  let id = sessionStorage.getItem(key);
  if (!id) {
    id = crypto.randomUUID();
    sessionStorage.setItem(key, id);
  }
  return id;
}

function newSessionId(): string {
  const id = crypto.randomUUID();
  sessionStorage.setItem("talk2db_session_id", id);
  sessionStorage.removeItem("talk2db_chat_messages");
  sessionStorage.removeItem("talk2db_chat_input");
  return id;
}

function loadSavedMessages(): ChatMessage[] {
  try {
    const raw = sessionStorage.getItem("talk2db_chat_messages");
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveMessages(msgs: ChatMessage[]) {
  try {
    sessionStorage.setItem("talk2db_chat_messages", JSON.stringify(msgs));
  } catch (err) {
    console.error("Failed to save chat messages to sessionStorage:", err);
  }
}

export function ChatProvider({ children }: { children: ReactNode }) {
  const [input, setInputState] = useState<string>(() => sessionStorage.getItem("talk2db_chat_input") || "");
  const [messages, setMessages] = useState<ChatMessage[]>(loadSavedMessages);
  const [streaming, setStreaming] = useState<boolean>(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    saveMessages(messages);
  }, [messages]);

  const setInput = (val: string) => {
    setInputState(val);
    sessionStorage.setItem("talk2db_chat_input", val);
  };

  function handleNewChat() {
    if (streaming) abortRef.current?.abort();
    setMessages([]);
    setInputState("");
    setStreaming(false);
    newSessionId();
  }

  function handleStop() {
    abortRef.current?.abort();
    setStreaming(false);
  }

  async function handleSend() {
    const query = input.trim();
    if (!query || streaming) return;

    setInput("");

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      query,
      statusLog: [],
      explanation: "",
      done: true,
    };
    const assistantId = crypto.randomUUID();
    const assistantMsg: ChatMessage = {
      id: assistantId,
      role: "assistant",
      statusLog: [],
      explanation: "",
      done: false,
    };

    setMessages((m) => [...m, userMsg, assistantMsg]);
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;
    const sessionId = getSessionId();
    const companyId = crypto.randomUUID();

    let draft: ChatMessage = assistantMsg;

    function updateAssistant(patch: Partial<ChatMessage> | ((prev: ChatMessage) => Partial<ChatMessage>)) {
      const delta = typeof patch === "function" ? patch(draft) : patch;
      draft = { ...draft, ...delta };
      setMessages((prev) => prev.map((m) => (m.id === assistantId ? draft : m)));
    }

    try {
      await streamQuery(
        "sql",
        { query, session_id: sessionId, message_id: assistantId, company_id: companyId },
        (line) => {
          let event: StreamEvent;
          try {
            event = JSON.parse(line) as StreamEvent;
          } catch {
            return;
          }
          switch (event.type) {
            case "status":
              updateAssistant((prev) => ({ statusLog: [...prev.statusLog, event.content] }));
              break;
            case "sql":
              updateAssistant({ sqlQueries: event.content });
              break;
            case "results":
              updateAssistant({ results: event.content });
              break;
            case "explanation_start":
              updateAssistant({ explanation: "" });
              break;
            case "explanation_chunk":
              updateAssistant((prev) => ({ explanation: prev.explanation + event.content }));
              break;
            case "metadata":
              updateAssistant({ done: true, metadata: event as unknown as Record<string, unknown> });
              break;
            case "error":
              updateAssistant({ error: event.content, done: true });
              break;
          }
        },
        controller.signal,
      );
    } catch (err) {
      if (err instanceof ApiError || err instanceof Error) {
        updateAssistant({ error: err.message, done: true });
      }
    } finally {
      updateAssistant((prev) => ({ done: true, statusLog: prev.statusLog }));
      setStreaming(false);
      abortRef.current = null;

      if (!draft.error) {
        const executionTime =
          typeof draft.metadata?.execution_time === "number" ? draft.metadata.execution_time : undefined;
        const totalTokens =
          typeof draft.metadata?.total_tokens === "number" ? draft.metadata.total_tokens : undefined;
        addLocalHistoryEntry(
          buildSqlHistoryEntry({
            sessionId,
            messageId: assistantId,
            companyId,
            query,
            sqlQueries: draft.sqlQueries ?? [],
            results: draft.results ?? [],
            explanation: draft.explanation,
            executionTime,
            totalTokens,
          }),
        );
      }
    }
  }

  async function handleShare(assistantId: string) {
    const idx = messages.findIndex((m) => m.id === assistantId);
    const msg = messages[idx];
    const userMsg = messages[idx - 1];
    if (!msg) return;

    setMessages((prev) => prev.map((m) => (m.id === assistantId ? { ...m, sharing: true } : m)));
    try {
      const res = await api.sharing.create(
        {
          session_id: getSessionId(),
          message_id: msg.id,
          company_id: crypto.randomUUID(),
          query: userMsg?.query ?? "",
          sql_queries: msg.sqlQueries ?? [],
          results: msg.results ?? [],
          explanation: msg.explanation,
          timestamp: new Date().toISOString(),
          execution_time: typeof msg.metadata?.execution_time === "number" ? msg.metadata.execution_time : null,
          total_tokens: typeof msg.metadata?.total_tokens === "number" ? msg.metadata.total_tokens : null,
        },
        24,
      );
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId ? { ...m, sharing: false, shareUrl: res.share_url, shareError: undefined } : m,
        ),
      );
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? { ...m, sharing: false, shareError: err instanceof ApiError ? err.message : "Failed to share" }
            : m,
        ),
      );
    }
  }

  return (
    <ChatContext.Provider
      value={{
        input,
        setInput,
        messages,
        streaming,
        handleSend,
        handleStop,
        handleNewChat,
        handleShare,
      }}
    >
      {children}
    </ChatContext.Provider>
  );
}

export function useChat(): ChatContextValue {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChat must be used within ChatProvider");
  return ctx;
}
