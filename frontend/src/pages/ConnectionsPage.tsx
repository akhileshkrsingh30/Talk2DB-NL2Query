import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { useAppState } from "../context/AppStateContext";

const CONNECTION_TYPES = [
  { value: "postgresql", label: "PostgreSQL", defaultPort: "5432" },
  { value: "mysql", label: "MySQL", defaultPort: "3306" },
  { value: "mariadb", label: "MariaDB", defaultPort: "3306" },
  { value: "mssql", label: "SQL Server (mssql)", defaultPort: "1433" },
  { value: "sqlserver", label: "SQL Server (sqlserver)", defaultPort: "1433" },
  { value: "oracle", label: "Oracle", defaultPort: "1521" },
  { value: "mongodb", label: "MongoDB", defaultPort: "27017" },
] as const;

type ConnectionType = (typeof CONNECTION_TYPES)[number]["value"];

function Card({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">{title}</h2>
      {subtitle && <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{subtitle}</p>}
      <div className="mt-4">{children}</div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium text-slate-600 dark:text-slate-300">{label}</span>
      {children}
    </label>
  );
}

const inputCls =
  "rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100";

const secondaryBtnCls =
  "rounded-lg border border-slate-300 px-4 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800";

const chipCls = (active: boolean) =>
  `rounded-full border px-3 py-1 text-xs ${
    active
      ? "border-blue-600 bg-blue-50 text-blue-700 dark:border-blue-500 dark:bg-blue-950 dark:text-blue-300"
      : "border-slate-300 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
  }`;

function Banner({ kind, message }: { kind: "success" | "error"; message: string }) {
  return (
    <div
      className={`mt-3 rounded-lg px-3 py-2 text-sm ${
        kind === "success"
          ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
          : "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300"
      }`}
    >
      {message}
    </div>
  );
}

export function ConnectionsPage() {
  const { health, refreshHealth } = useAppState();

  const [connType, setConnType] = useState<ConnectionType>("postgresql");
  const isMongo = connType === "mongodb";

  // SQL database
  const [dbForm, setDbForm] = useState({
    host: "",
    port: "5432",
    database: "",
    user: "",
    password: "",
  });
  const [dbBusy, setDbBusy] = useState(false);
  const [dbMessage, setDbMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [databases, setDatabases] = useState<string[] | null>(null);
  const [dbStatusText, setDbStatusText] = useState<string>("");
  const [sqlTables, setSqlTables] = useState<string[] | null>(null);

  // MongoDB
  const [mongoForm, setMongoForm] = useState({
    host: "",
    port: "27017",
    database: "",
    username: "",
    password: "",
    auth_source: "admin",
  });
  const [mongoBusy, setMongoBusy] = useState(false);
  const [mongoMessage, setMongoMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [mongoDatabases, setMongoDatabases] = useState<string[] | null>(null);
  const [mongoCollections, setMongoCollections] = useState<string[] | null>(null);
  const [mongoStatusText, setMongoStatusText] = useState<string>("");

  // LLM
  const [llmForm, setLlmForm] = useState({ api_key: "", api_base: "", model: "" });
  const [llmBusy, setLlmBusy] = useState(false);
  const [llmMessage, setLlmMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [llmStatusText, setLlmStatusText] = useState<string>("");

  useEffect(() => {
    api.database
      .status()
      .then((s) => setDbStatusText(`${s.status}: ${s.message}`))
      .catch(() => {});
    api.mongodb
      .status()
      .then((s) => setMongoStatusText(`${s.status}: ${s.message}`))
      .catch(() => {});
    api.llm
      .status()
      .then((s) => setLlmStatusText(`${s.status} (model: ${s.model})`))
      .catch(() => {});
  }, []);

  function handleConnTypeChange(next: ConnectionType) {
    setConnType(next);
    if (next !== "mongodb") {
      const preset = CONNECTION_TYPES.find((t) => t.value === next);
      if (preset) setDbForm((f) => ({ ...f, port: preset.defaultPort }));
    }
  }

  async function handleDbConnect(e: React.FormEvent) {
    e.preventDefault();
    setDbBusy(true);
    setDbMessage(null);
    try {
      const res = await api.database.connect({
        host: dbForm.host,
        port: dbForm.port,
        database: dbForm.database || undefined,
        user: dbForm.user,
        password: dbForm.password,
        db_type: connType,
      });
      setDbMessage({ kind: "success", text: `${res.message}${res.version ? ` (${res.version})` : ""}` });
      setDbStatusText(`connected: ${res.message}`);
      await refreshHealth();
    } catch (err) {
      setDbMessage({ kind: "error", text: err instanceof ApiError ? err.message : "Failed to connect" });
    } finally {
      setDbBusy(false);
    }
  }

  async function handleListDatabases() {
    setDbBusy(true);
    setDbMessage(null);
    try {
      const res = await api.database.list();
      setDatabases(res.databases);
    } catch (err) {
      setDbMessage({ kind: "error", text: err instanceof ApiError ? err.message : "Failed to list databases" });
    } finally {
      setDbBusy(false);
    }
  }

  async function handleSelectDatabase(database: string) {
    setDbBusy(true);
    setDbMessage(null);
    setSqlTables(null);
    try {
      const res = await api.database.select(database);
      setDbMessage({ kind: "success", text: res.message });
      setDbForm((f) => ({ ...f, database }));
      await refreshHealth();
    } catch (err) {
      setDbMessage({ kind: "error", text: err instanceof ApiError ? err.message : "Failed to select database" });
    } finally {
      setDbBusy(false);
    }
  }

  async function handleListTables() {
    setDbBusy(true);
    setDbMessage(null);
    try {
      const res = await api.database.tables();
      setSqlTables(res.tables);
    } catch (err) {
      setDbMessage({ kind: "error", text: err instanceof ApiError ? err.message : "Failed to list tables" });
    } finally {
      setDbBusy(false);
    }
  }

  async function handleDbDisconnect() {
    setDbBusy(true);
    try {
      await api.database.disconnect();
      setDbMessage({ kind: "success", text: "Disconnected" });
      setDatabases(null);
      setSqlTables(null);
      await refreshHealth();
    } finally {
      setDbBusy(false);
    }
  }

  async function handleMongoConnect(e: React.FormEvent) {
    e.preventDefault();
    setMongoBusy(true);
    setMongoMessage(null);
    try {
      const res = await api.mongodb.connect({
        host: mongoForm.host,
        port: mongoForm.port,
        database: mongoForm.database || undefined,
        username: mongoForm.username || undefined,
        password: mongoForm.password || undefined,
        auth_source: mongoForm.auth_source || undefined,
      });
      setMongoMessage({ kind: "success", text: res.message });
      setMongoStatusText(`connected: ${res.message}`);
      await refreshHealth();
    } catch (err) {
      setMongoMessage({ kind: "error", text: err instanceof ApiError ? err.message : "Failed to connect" });
    } finally {
      setMongoBusy(false);
    }
  }

  async function handleListMongoDatabases() {
    setMongoBusy(true);
    setMongoMessage(null);
    try {
      const res = await api.mongodb.list();
      setMongoDatabases(res.databases);
    } catch (err) {
      setMongoMessage({ kind: "error", text: err instanceof ApiError ? err.message : "Failed to list databases" });
    } finally {
      setMongoBusy(false);
    }
  }

  async function handleSelectMongoDatabase(database: string) {
    setMongoBusy(true);
    setMongoMessage(null);
    try {
      const res = await api.mongodb.select(database);
      setMongoMessage({ kind: "success", text: res.message });
      setMongoForm((f) => ({ ...f, database }));
      setMongoCollections(null);
      await refreshHealth();
      // Chain straight into listing collections for the newly selected database
      await handleListCollections();
    } catch (err) {
      setMongoMessage({ kind: "error", text: err instanceof ApiError ? err.message : "Failed to select database" });
    } finally {
      setMongoBusy(false);
    }
  }

  async function handleListCollections() {
    setMongoBusy(true);
    setMongoMessage(null);
    try {
      const res = await api.mongodb.collections();
      setMongoCollections(res.collections);
    } catch (err) {
      setMongoMessage({ kind: "error", text: err instanceof ApiError ? err.message : "Failed to list collections" });
    } finally {
      setMongoBusy(false);
    }
  }

  async function handleSelectCollection(collection: string) {
    setMongoBusy(true);
    setMongoMessage(null);
    try {
      const res = await api.mongodb.selectCollection(collection);
      setMongoMessage({ kind: "success", text: res.message });
    } catch (err) {
      setMongoMessage({ kind: "error", text: err instanceof ApiError ? err.message : "Failed to select collection" });
    } finally {
      setMongoBusy(false);
    }
  }

  async function handleMongoDisconnect() {
    setMongoBusy(true);
    try {
      await api.mongodb.disconnect();
      setMongoMessage({ kind: "success", text: "Disconnected" });
      setMongoDatabases(null);
      setMongoCollections(null);
      await refreshHealth();
    } finally {
      setMongoBusy(false);
    }
  }

  async function handleLlmConfigure(e: React.FormEvent) {
    e.preventDefault();
    setLlmBusy(true);
    setLlmMessage(null);
    try {
      const res = await api.llm.configure({
        api_key: llmForm.api_key || undefined,
        api_base: llmForm.api_base || undefined,
        model: llmForm.model || undefined,
      });
      setLlmMessage({ kind: "success", text: `${res.message} (model: ${res.model})` });
      setLlmStatusText(`configured (model: ${res.model})`);
      await refreshHealth();
    } catch (err) {
      setLlmMessage({ kind: "error", text: err instanceof ApiError ? err.message : "Failed to configure LLM" });
    } finally {
      setLlmBusy(false);
    }
  }

  const busy = isMongo ? mongoBusy : dbBusy;
  const statusText = isMongo ? mongoStatusText : dbStatusText;
  const message = isMongo ? mongoMessage : dbMessage;
  const isConnected = isMongo ? !!health?.mongodb_connected : !!health?.database_connected;

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 p-6">
      <div>
        <h1 className="text-xl font-bold text-slate-900 dark:text-slate-100">Connections & LLM</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Configure a database connection and the LLM used to translate natural language into queries. Any field
          left blank falls back to the server's .env configuration. SQL and MongoDB connections are independent —
          switching the type below only changes which form you're editing; both can stay connected at once (see the
          status badges in the top bar).
        </p>
      </div>

      <Card title="Database connection" subtitle={statusText || "Not checked yet"}>
        <div className="mb-4">
          <Field label="Connection type">
            <select
              className={`${inputCls} max-w-xs`}
              value={connType}
              onChange={(e) => handleConnTypeChange(e.target.value as ConnectionType)}
            >
              {CONNECTION_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </Field>
        </div>

        {isMongo ? (
          <form
            className="grid grid-cols-2 gap-3"
            onSubmit={isConnected ? (e) => e.preventDefault() : handleMongoConnect}
          >
            <fieldset disabled={isConnected} className="col-span-2 grid grid-cols-2 gap-3 disabled:opacity-60">
              <Field label="Host">
                <input
                  className={inputCls}
                  value={mongoForm.host}
                  onChange={(e) => setMongoForm((f) => ({ ...f, host: e.target.value }))}
                  placeholder="localhost"
                />
              </Field>
              <Field label="Port">
                <input
                  className={inputCls}
                  value={mongoForm.port}
                  onChange={(e) => setMongoForm((f) => ({ ...f, port: e.target.value }))}
                  placeholder="27017"
                />
              </Field>
              <Field label="Auth source">
                <input
                  className={inputCls}
                  value={mongoForm.auth_source}
                  onChange={(e) => setMongoForm((f) => ({ ...f, auth_source: e.target.value }))}
                />
              </Field>
              <Field label="Username (optional)">
                <input
                  className={inputCls}
                  value={mongoForm.username}
                  onChange={(e) => setMongoForm((f) => ({ ...f, username: e.target.value }))}
                />
              </Field>
              <Field label="Password (optional)">
                <input
                  type="password"
                  className={inputCls}
                  value={mongoForm.password}
                  onChange={(e) => setMongoForm((f) => ({ ...f, password: e.target.value }))}
                />
              </Field>
            </fieldset>
            <div className="col-span-2 flex flex-wrap gap-2 pt-1">
              {isConnected ? (
                <button
                  type="button"
                  onClick={handleMongoDisconnect}
                  disabled={busy}
                  className="rounded-lg bg-red-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
                >
                  {busy ? "Disconnecting…" : "Disconnect"}
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={busy}
                  className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  {busy ? "Connecting…" : "Connect"}
                </button>
              )}
              {isConnected && (
                <>
                  <button type="button" onClick={handleListMongoDatabases} disabled={busy} className={secondaryBtnCls}>
                    List databases
                  </button>
                  <button type="button" onClick={handleListCollections} disabled={busy} className={secondaryBtnCls}>
                    List collections
                  </button>
                </>
              )}
            </div>
          </form>
        ) : (
          <form className="grid grid-cols-2 gap-3" onSubmit={isConnected ? (e) => e.preventDefault() : handleDbConnect}>
            <fieldset disabled={isConnected} className="col-span-2 grid grid-cols-2 gap-3 disabled:opacity-60">
              <Field label="Host">
                <input
                  className={inputCls}
                  value={dbForm.host}
                  onChange={(e) => setDbForm((f) => ({ ...f, host: e.target.value }))}
                  placeholder="10.199.207.30"
                />
              </Field>
              <Field label="Port">
                <input
                  className={inputCls}
                  value={dbForm.port}
                  onChange={(e) => setDbForm((f) => ({ ...f, port: e.target.value }))}
                />
              </Field>
              <Field label="User">
                <input
                  className={inputCls}
                  value={dbForm.user}
                  onChange={(e) => setDbForm((f) => ({ ...f, user: e.target.value }))}
                />
              </Field>
              <Field label="Password">
                <input
                  type="password"
                  className={inputCls}
                  value={dbForm.password}
                  onChange={(e) => setDbForm((f) => ({ ...f, password: e.target.value }))}
                />
              </Field>
            </fieldset>
            <div className="col-span-2 flex flex-wrap gap-2 pt-1">
              {isConnected ? (
                <button
                  type="button"
                  onClick={handleDbDisconnect}
                  disabled={busy}
                  className="rounded-lg bg-red-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
                >
                  {busy ? "Disconnecting…" : "Disconnect"}
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={busy}
                  className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  {busy ? "Connecting…" : "Connect"}
                </button>
              )}
              {isConnected && (
                <>
                  <button type="button" onClick={handleListDatabases} disabled={busy} className={secondaryBtnCls}>
                    List databases
                  </button>
                  {dbForm.database && (
                    <button type="button" onClick={handleListTables} disabled={busy} className={secondaryBtnCls}>
                      List tables
                    </button>
                  )}
                </>
              )}
            </div>
          </form>
        )}

        {!isMongo && databases && (
          <div className="mt-3">
            <p className="mb-1 text-xs font-medium text-slate-500 dark:text-slate-400">
              Databases — pick one to select it
            </p>
            <div className="flex flex-wrap gap-2">
              {databases.map((d) => (
                <button key={d} onClick={() => handleSelectDatabase(d)} className={chipCls(d === dbForm.database)}>
                  {d}
                </button>
              ))}
            </div>
          </div>
        )}

        {!isMongo && sqlTables && (
          <div className="mt-3">
            <p className="mb-1 text-xs font-medium text-slate-500 dark:text-slate-400">
              Tables in "{dbForm.database}" — pick one to preview it on the Schema page
            </p>
            <div className="flex flex-wrap gap-2">
              {sqlTables.map((t) => (
                <Link key={t} to={`/schema?table=${encodeURIComponent(t)}`} className={chipCls(false)}>
                  {t}
                </Link>
              ))}
            </div>
          </div>
        )}

        {isMongo && mongoDatabases && (
          <div className="mt-3">
            <p className="mb-1 text-xs font-medium text-slate-500 dark:text-slate-400">
              Databases — pick one to select it
            </p>
            <div className="flex flex-wrap gap-2">
              {mongoDatabases.map((d) => (
                <button
                  key={d}
                  onClick={() => handleSelectMongoDatabase(d)}
                  className={chipCls(d === mongoForm.database)}
                >
                  {d}
                </button>
              ))}
            </div>
          </div>
        )}
        {isMongo && mongoCollections && (
          <div className="mt-3">
            <p className="mb-1 text-xs font-medium text-slate-500 dark:text-slate-400">
              Collections in "{mongoForm.database}" — pick one to select it
            </p>
            <div className="flex flex-wrap gap-2">
              {mongoCollections.map((c) => (
                <button key={c} onClick={() => handleSelectCollection(c)} className={chipCls(false)}>
                  {c}
                </button>
              ))}
            </div>
          </div>
        )}

        {message && <Banner kind={message.kind} message={message.text} />}
      </Card>

      <Card title="LLM configuration" subtitle={llmStatusText || "Not checked yet"}>
        <form className="grid grid-cols-2 gap-3" onSubmit={handleLlmConfigure}>
          <Field label="API key (optional, falls back to .env)">
            <input
              type="password"
              className={inputCls}
              value={llmForm.api_key}
              onChange={(e) => setLlmForm((f) => ({ ...f, api_key: e.target.value }))}
              placeholder="sk-…"
            />
          </Field>
          <Field label="API base (optional)">
            <input
              className={inputCls}
              value={llmForm.api_base}
              onChange={(e) => setLlmForm((f) => ({ ...f, api_base: e.target.value }))}
              placeholder="https://api.openai.com/v1"
            />
          </Field>
          <Field label="Model (optional)">
            <input
              className={inputCls}
              value={llmForm.model}
              onChange={(e) => setLlmForm((f) => ({ ...f, model: e.target.value }))}
              placeholder="gpt-4o"
            />
          </Field>
          <div className="col-span-2 flex items-end">
            <button
              type="submit"
              disabled={llmBusy}
              className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {llmBusy ? "Configuring…" : "Configure"}
            </button>
          </div>
        </form>
        {llmMessage && <Banner kind={llmMessage.kind} message={llmMessage.text} />}
      </Card>
    </div>
  );
}
