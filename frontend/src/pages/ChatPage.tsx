import { useEffect, useRef } from "react";
import { ShareChannelLinks } from "../components/ShareChannelLinks";
import { SqlResultSets } from "../components/SqlResultSets";
import { useChat, type ChatMessage } from "../context/ChatContext";
import { useAppState } from "../context/AppStateContext";

function autosize(el: HTMLTextAreaElement | null) {
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
}

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} className="h-4 w-4">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 19V5M5 12l7-7 7 7" />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className="h-3.5 w-3.5">
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </svg>
  );
}

export function ChatPage() {
  const {
    input,
    setInput,
    messages,
    streaming,
    handleSend,
    handleStop,
    handleNewChat,
    handleShare,
  } = useChat();

  const { health } = useAppState();

  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    autosize(textareaRef.current);
  }, [input]);

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  const dbBadge = (
    <div className="flex items-center gap-2.5 text-xs">
      <span
        className={`h-2 w-2 rounded-full ${
          health?.database_connected ? "bg-emerald-500 animate-pulse" : "bg-amber-500"
        }`}
      />
      <div className="flex items-center gap-2 rounded-lg border border-slate-200/80 bg-slate-100/80 px-3 py-1.5 font-medium text-slate-800 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200">
        <span className="text-slate-500 dark:text-slate-400">Database:</span>
        <span className="font-semibold">{health?.database_name || "SystemDBInvetoryClone"}</span>
        <span className="text-slate-300 dark:text-slate-700">|</span>
        <span className="text-slate-500 dark:text-slate-400">LLM:</span>
        <span className="font-semibold truncate max-w-[320px]">
          {health?.llm_model || "Qwen/Qwen2.5-Coder-32B-Instruct-AWQ"}
        </span>
      </div>
    </div>
  );

  const composer = (
    <div className="flex items-end gap-2 rounded-3xl border border-slate-200 bg-white px-4 py-3 shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <textarea
        ref={textareaRef}
        className="max-h-48 flex-1 resize-none bg-transparent text-[15px] leading-relaxed text-slate-900 placeholder:text-slate-400 focus:outline-none dark:text-slate-100 dark:placeholder:text-slate-500"
        placeholder="Ask anything about your database…"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        rows={1}
      />
      {streaming ? (
        <button
          onClick={handleStop}
          title="Stop"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-slate-800 text-white hover:bg-slate-700 dark:bg-slate-100 dark:text-slate-900"
        >
          <StopIcon />
        </button>
      ) : (
        <button
          onClick={handleSend}
          disabled={!input.trim()}
          title="Send"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-slate-900 text-white hover:bg-slate-700 disabled:opacity-30 dark:bg-slate-100 dark:text-slate-900"
        >
          <SendIcon />
        </button>
      )}
    </div>
  );

  if (messages.length === 0) {
    return (
      <div className="flex h-full flex-col">
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-3 dark:border-slate-800">
          {dbBadge}
        </div>
        <div className="flex flex-1 flex-col items-center justify-center gap-8 px-6">
          <div className="text-center">
            <h1 className="text-3xl font-semibold text-slate-900 dark:text-slate-100">What do you want to know?</h1>
            <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
              Ask a question in plain English — Talk2DB will write and run the query for you.
            </p>
          </div>
          <div className="w-full max-w-2xl">{composer}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-slate-200 px-6 py-3 dark:border-slate-800">
        {dbBadge}
        <button
          onClick={handleNewChat}
          className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          New chat
        </button>
      </div>

      <div className="flex-1 overflow-auto">
        <div className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-6">
          {messages.map((m) =>
            m.role === "user" ? (
              <div key={m.id} className="flex justify-end">
                <div className="max-w-[75%] rounded-3xl bg-slate-100 px-4 py-2.5 text-[15px] text-slate-900 dark:bg-slate-800 dark:text-slate-100">
                  {m.query}
                </div>
              </div>
            ) : (
              <div key={m.id} className="space-y-3 text-[15px] leading-relaxed text-slate-800 dark:text-slate-200">
                {!m.done && (
                  <div className="flex items-center gap-2 text-slate-500 dark:text-slate-400">
                    <span className="h-3 w-3 animate-spin rounded-full border-2 border-slate-300 border-t-slate-600 dark:border-slate-600 dark:border-t-slate-300" />
                    <span>{m.statusLog[m.statusLog.length - 1] ?? "Working…"}</span>
                  </div>
                )}
                {m.error && <p className="text-red-600 dark:text-red-400">{m.error}</p>}
                <SqlResultSets sqlQueries={m.sqlQueries} results={m.results} />
                {m.explanation && <p className="whitespace-pre-wrap">{m.explanation}</p>}
                {m.done && !m.error && (m.results?.length || m.sqlQueries?.length) && (
                  <div className="flex flex-wrap items-center gap-3 pt-1">
                    {m.metadata && (
                      <span className="text-xs text-slate-400 dark:text-slate-500">
                        {typeof m.metadata.execution_time === "number" && `${m.metadata.execution_time.toFixed(2)}s`}
                        {typeof m.metadata.total_tokens === "number" && ` · ${m.metadata.total_tokens} tokens`}
                      </span>
                    )}
                    <button
                      onClick={() => handleShare(m.id)}
                      disabled={m.sharing}
                      className="text-xs font-medium text-blue-600 hover:underline disabled:opacity-50 dark:text-blue-400"
                    >
                      {m.sharing ? "Sharing…" : m.shareUrl ? "Shared ✓" : "Share"}
                    </button>
                    {m.shareUrl && (
                      <>
                        <span className="truncate text-xs text-slate-400 dark:text-slate-500">{m.shareUrl}</span>
                        <ShareChannelLinks url={m.shareUrl} text={userQueryFor(messages, m.id)} />
                      </>
                    )}
                    {m.shareError && <span className="text-xs text-red-500 dark:text-red-400">{m.shareError}</span>}
                  </div>
                )}
              </div>
            ),
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="border-t border-slate-200 px-6 py-4 dark:border-slate-800">
        <div className="mx-auto max-w-3xl">{composer}</div>
      </div>
    </div>
  );
}

function userQueryFor(messages: ChatMessage[], assistantId: string): string | undefined {
  const idx = messages.findIndex((m) => m.id === assistantId);
  return messages[idx - 1]?.query;
}
