# Talk2DB Frontend

React + TypeScript + Vite frontend for the Talk2DB / NL2Query API (`../main.py`).

## Pages

- **Chat** — ask questions in plain English, streamed (NDJSON) SQL/MongoDB generation, execution, and explanation.
- **Schema & Tables** — browse tables in the connected SQL database and preview paginated row data.
- **History** — recent processed queries, expandable to see SQL/results/explanation, with share links.
- **Shared Results** — manage active share links; `/share/:id` is the public read-only view of a shared result.
- **Connections & LLM** — connect/disconnect the SQL database and MongoDB, list/select databases & collections, and configure the LLM.

## Running

Requires Node.js 20+.

```bash
npm install
npm run dev
```

This starts the dev server on `http://localhost:5173`. Requests to `/api/*` are proxied to the backend at
`http://localhost:8080` (configured in `vite.config.ts`), so make sure the FastAPI backend is running there
(`python main.py` from the repo root, or `uvicorn main:app --port 8080`).

To point the frontend at a different backend URL (e.g. in production, where the two aren't served together),
set `VITE_API_URL` in `.env` to the backend's full URL — CORS is open on the backend so no proxy is required:

```
VITE_API_URL=http://your-backend-host:8080
```

## Build

```bash
npm run build   # type-checks and outputs static files to dist/
npm run preview # preview the production build locally
```
