import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAppState } from "../context/AppStateContext";
import { useTheme } from "../context/ThemeContext";
import { StatusBadge } from "./StatusBadge";

const navItems = [
  { to: "/", label: "Chat", end: true },
  { to: "/schema", label: "Schema & Tables" },
  { to: "/history", label: "History" },
  { to: "/sharing", label: "Shared Results" },
  { to: "/connections", label: "Connections & LLM" },
];

const SIDEBAR_STORAGE_KEY = "talk2db_sidebar_open";

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-4 w-4">
      <circle cx="12" cy="12" r="4" />
      <path
        strokeLinecap="round"
        d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"
      />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
      <path d="M20.742 13.045a8.088 8.088 0 0 1-2.077.273c-4.492 0-8.13-3.639-8.13-8.13 0-.712.092-1.403.264-2.062a.75.75 0 0 0-.976-.912A9.755 9.755 0 0 0 3 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 0 0 8.856-5.653.75.75 0 0 0-.864-1.038 8.05 8.05 0 0 1 0 -1.264Z" />
    </svg>
  );
}

function SidebarIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-4 w-4">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path strokeLinecap="round" d="M9 4v16" />
    </svg>
  );
}

export function Layout() {
  const { health, healthError } = useAppState();
  const { theme, toggleTheme } = useTheme();
  const [sidebarOpen, setSidebarOpen] = useState(() => localStorage.getItem(SIDEBAR_STORAGE_KEY) !== "false");

  useEffect(() => {
    localStorage.setItem(SIDEBAR_STORAGE_KEY, String(sidebarOpen));
  }, [sidebarOpen]);

  return (
    <div className="flex h-screen w-full overflow-hidden bg-white dark:bg-slate-950">
      <aside
        className={`flex shrink-0 flex-col overflow-hidden border-slate-200 bg-slate-50 transition-all duration-200 dark:border-slate-800 dark:bg-slate-900 ${
          sidebarOpen ? "w-60 border-r" : "w-0 border-r-0"
        }`}
      >
        <div className="w-60 border-b border-slate-200 px-5 py-5 dark:border-slate-800">
          <h1 className="text-lg font-bold text-slate-900 dark:text-slate-100">Talk2DB</h1>
          <p className="text-xs text-slate-500 dark:text-slate-400">Natural language → SQL / Mongo</p>
        </div>
        <nav className="w-60 flex-1 space-y-1 p-3">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `block rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-blue-600 text-white"
                    : "text-slate-600 hover:bg-slate-200/70 dark:text-slate-300 dark:hover:bg-slate-800"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>

      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-3 dark:border-slate-800 dark:bg-slate-950">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSidebarOpen((v) => !v)}
              title={sidebarOpen ? "Hide sidebar" : "Show sidebar"}
              className="rounded-lg border border-slate-200 p-2 text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              <SidebarIcon />
            </button>
            <div className="flex flex-wrap gap-2">
              <StatusBadge label="Database" active={!!health?.database_connected} />
              <StatusBadge label="LLM" active={!!health?.llm_configured} />
            </div>
          </div>
          <div className="flex items-center gap-3">
            {healthError && <span className="text-xs text-red-600 dark:text-red-400">{healthError}</span>}
            <button
              onClick={toggleTheme}
              title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              className="rounded-lg border border-slate-200 p-2 text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              {theme === "dark" ? <SunIcon /> : <MoonIcon />}
            </button>
          </div>
        </header>
        <main className="flex-1 overflow-auto bg-slate-50 dark:bg-slate-950">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
