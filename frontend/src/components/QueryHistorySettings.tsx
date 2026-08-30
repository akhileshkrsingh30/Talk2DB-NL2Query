import { useQuerySettings } from "../hooks/useQuerySettings";

/**
 * Drop-in "Settings tab" section for controlling per-session query behavior:
 *  - Chat history toggle (use_chat_history)
 *  - History depth (history_limit), only editable while chat history is on
 *  - Explanation toggle (include_explanation)
 *
 * Dependency-free (plain elements, no UI library assumed) so it can be restyled to match
 * the host app's design system. Settings are persisted per session_id via useQuerySettings,
 * and read by lib/querySettings.ts::applyQuerySettings() when building query requests.
 */
export function QueryHistorySettings({ sessionId }: { sessionId: string }) {
  const { settings, setUseChatHistory, setHistoryLimit, setIncludeExplanation } =
    useQuerySettings(sessionId);

  return (
    <section className="settings-section" aria-label="Query context settings">
      <h3>Conversation context</h3>

      <label className="settings-row">
        <input
          type="checkbox"
          checked={settings.useChatHistory}
          onChange={(e) => setUseChatHistory(e.target.checked)}
        />
        <span>
          Remember conversation
          <small>
            Include the last few questions/answers from this session so follow-ups
            ("now filter by last month") resolve correctly. Uses a small amount of
            extra tokens per query.
          </small>
        </span>
      </label>

      <label className="settings-row">
        <span>
          History depth
          <small>Number of prior turns to include (only used when chat history is on).</small>
        </span>
        <input
          type="range"
          min={1}
          max={10}
          step={1}
          value={settings.historyLimit}
          disabled={!settings.useChatHistory}
          onChange={(e) => setHistoryLimit(Number(e.target.value))}
        />
        <span>{settings.historyLimit}</span>
      </label>

      <label className="settings-row">
        <input
          type="checkbox"
          checked={settings.includeExplanation}
          onChange={(e) => setIncludeExplanation(e.target.checked)}
        />
        <span>
          Generate explanation
          <small>
            Turn off to return only SQL + results and skip the natural-language
            explanation step, reducing tokens per query.
          </small>
        </span>
      </label>
    </section>
  );
}
